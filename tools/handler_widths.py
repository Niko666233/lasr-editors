"""
Derive every opcode's operand width from its real dispatch handler.

tools/opcode_handlers.py found the 85-entry dispatch table at VA 0x00654b70.
Each handler is the ground truth for how many bytes the opcode consumes:

  * it reads the operand out of the instruction stream at a small positive
    displacement off the stream pointer (edi) -> the opcode carries an operand
  * it just advances the stream pointer / touches only the stack -> no operand

This is independent of the statistical width solver, so the two can be compared
per opcode.
"""
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path

from capstone import Cs, CS_ARCH_X86, CS_MODE_32
from capstone.x86_const import X86_OP_MEM, X86_OP_REG

sys.path.insert(0, str(Path(__file__).parent))
from opcode_table import load_names, sections          # noqa: E402
from lasr_vm import load_records, solve_widths          # noqa: E402

EXE = r"C:\Games\LASR\LASR.exe"
IB = 0x400000
TABLE_VA = 0x00654B70
NENT = 85


def va2off(secs, va):
    r = va - IB
    for nm, sva, vsz, raw, rsz in secs:
        if sva <= r < sva + max(vsz, rsz):
            return raw + (r - sva)
    return None


def sweep(md, code, base):
    out, off, n = [], 0, len(code)
    while off < n:
        for ins in md.disasm(code[off:off + 48], base + off):
            out.append(ins)
            off += ins.size
            break
        else:
            off += 1
    return out


def handler_width(md, secs, d, addr, limit=48):
    """-> (nbytes_consumed, evidence) where nbytes is 1 or 5."""
    o = va2off(secs, addr)
    if o is None:
        return 5, "no code"
    insns = sweep(md, d[o:o + 320], addr)[:limit]
    reads, adv = None, None
    for ins in insns:
        if ins.mnemonic in ("mov", "movzx", "movsx") and len(ins.operands) == 2:
            s = ins.operands[1]
            if s.type == X86_OP_MEM and s.mem.base != 0 and s.mem.disp in (1, 2, 3):
                reads = (s.mem.disp, s.size, f"{ins.mnemonic} {ins.op_str}")
        if ins.mnemonic == "add" and len(ins.operands) == 2:
            if ins.operands[0].type == X86_OP_REG and ins.operands[1].size == 1:
                m = ins.op_str
                for w in (5, 4, 3, 2, 1):
                    if m.split(",")[-1].strip() == str(w):
                        adv = w
                        break
    if reads and reads[0] == 1 and reads[1] == 4:
        return 5, f"[edi+1] dword via {reads[2]}"
    if adv == 5:
        return 5, f"add stream,5"
    if reads and reads[0] == 1 and reads[1] == 2:
        return 5, f"[edi+1] word via {reads[2]}"
    return 1, "no operand read"


def main():
    d = Path(EXE).read_bytes()
    secs = sections(d)
    names = load_names(d, secs)
    off = va2off(secs, TABLE_VA)
    entries = [struct.unpack_from("<I", d, off + i * 4)[0] for i in range(NENT)]
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    md.detail = True

    recs = load_records()
    W, ex, tot = solve_widths(recs)
    print(f"aligner widths: {ex}/{tot} exact parse\n")

    hw, ev = {}, {}
    for i, a in enumerate(entries):
        w, e = handler_width(md, secs, d, a)
        hw[i], ev[i] = w, e

    print(f"{'slot':>4} {'name(=84-i)':>18} {'aligner':>7} {'handler':>7} {'same':>5}  evidence")
    agree = dis = 0
    for i in range(NENT):
        aw = W.get(i, 5)
        ok = (aw == hw[i])
        agree += ok
        dis += (not ok)
        mark = "  " if ok else "!!"
        print(f"{i:>4} {names[84-i]:>18} {aw:>7} {hw[i]:>7} {mark:>4}  {ev[i][:58]}")
    print(f"\n>>> aligner and handlers agree on {agree}/{NENT}; disagree on {dis}")

    print("\n=== does forcing the handler widths parse better? ===")
    Wh = {i: hw[i] for i in range(NENT)}
    ex2 = sum(1 for _, _, b in recs if __import__("lasr_vm").walk(b, Wh) is not None)
    print(f"  handler-derived widths: {ex2}/{len(recs)} = {ex2*100/len(recs):.2f}%")

    print("\n=== is opcode 0x16 a 1-byte terminator or a 5-byte JMP? ===")
    for v in (1, 5):
        W2 = dict(W)
        W2[0x16] = v
        e2 = sum(1 for _, _, b in recs if __import__("lasr_vm").walk(b, W2) is not None)
        print(f"  W[0x16]={v} -> {e2}/{len(recs)} = {e2*100/len(recs):.2f}%")


if __name__ == "__main__":
    main()
