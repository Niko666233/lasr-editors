"""
Dump the VM opcode dispatch table (85 entries @ VA 0x00654b70) and classify
each handler.

Found by tools/dispatch_table.py: exactly 85 pointers, all into .text - the
same count as the opcode name table.  Slots share handlers where opcodes are
handled by common code, so grouping the identical addresses is itself a signal
about the enum's structure.

For every handler we look for evidence that it consumes the 4-byte operand
that follows the opcode byte in the instruction stream: a dword load from a
small positive displacement off the stream pointer (e.g. `mov eax,[esi+1]`),
or an instruction-pointer advance of 5.
"""
import struct
import sys
from collections import Counter, OrderedDict
from pathlib import Path

from capstone import Cs, CS_ARCH_X86, CS_MODE_32
from capstone.x86_const import X86_OP_MEM

sys.path.insert(0, str(Path(__file__).parent))
from opcode_table import chunks, load_names, sections   # noqa: E402

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


def main():
    d = Path(EXE).read_bytes()
    secs = sections(d)
    names = load_names(d, secs)
    t = next(s for s in secs if s[0] == ".text")
    code = d[t[3]:t[3] + t[4]]
    base = IB + t[1]

    off = va2off(secs, TABLE_VA)
    entries = [struct.unpack_from("<I", d, off + i * 4)[0] for i in range(NENT)]
    print(f"dispatch table @ 0x{TABLE_VA:08x}: {NENT} entries")
    cnt = Counter(entries)
    print(f"distinct handlers: {len(cnt)}")
    dup = {a: c for a, c in cnt.items() if c > 1}
    print(f"shared slots: {sum(dup.values())} across {len(dup)} handlers")
    for a, c in sorted(dup.items(), key=lambda kv: -kv[1])[:10]:
        idxs = [i for i, e in enumerate(entries) if e == a]
        print(f"   0x{a:x} x{c}  slots {idxs}")

    md = Cs(CS_ARCH_X86, CS_MODE_32)
    md.detail = True
    body = {}
    for a in sorted(set(entries)):
        o = va2off(secs, a)
        if o is None:
            body[a] = []
            continue
        body[a] = sweep(md, d[o:o + 200], a)[:26]

    print(f"\n=== per-slot handler analysis ===")
    print(f"{'slot':>4} {'name(=84-i)':>18} {'handler':>10} {'operand?':>9} {'adv5?':>6}  first insns")
    for i in range(NENT):
        a = entries[i]
        insns = body.get(a, [])
        operand = adv5 = 0
        for ins in insns:
            if ins.mnemonic in ("mov", "movzx", "movsx") and len(ins.operands) == 2:
                s = ins.operands[1]
                if s.type == X86_OP_MEM and s.mem.disp in (1, 2, 3, 4):
                    operand += 1
            if ins.mnemonic in ("add", "lea") and "5" in ins.op_str.split(",")[-1].strip():
                adv5 += 1
        txt = " | ".join(f"{x.mnemonic} {x.op_str}" for x in insns[:3])
        nm = names[84 - i] if 0 <= 84 - i < len(names) else "?"
        print(f"{i:>4} {nm:>18} 0x{a:x} {operand:>9} {adv5:>6}  {txt[:70]}")


if __name__ == "__main__":
    main()
