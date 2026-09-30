"""
Read each opcode handler's *stream advance* straight out of the exe, and use it
as an independent width oracle.

The dispatcher at 0x6538f0 loads the instruction-stream pointer from [esi+0x28]
into edi.  Every handler ends by jumping to one of two shared epilogues:

    0x653d9f  add dword ptr [esi+0x28], 4     ; an operand was consumed
    0x653da3  inc dword ptr [esi+0x28]        ; +1 for the opcode byte itself
      (0x653d9f falls through into 0x653da3, so entering there advances 5)

So a handler that reaches 0x653d9f occupies 5 bytes and one that reaches
0x653da3 occupies 1 byte - readable mechanically, with no statistics and no
guesswork about names.  Recursive descent from each handler entry, following
intra-handler jumps and conditional branches, collecting epilogue outcomes.

Usage: python tools/handler_advance.py
"""
import struct
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from capstone import Cs, CS_ARCH_X86, CS_MODE_32          # noqa: E402
from opcode_table import load_names, sections              # noqa: E402

EXE = r"C:\Games\LASR\LASR.exe"
IB = 0x400000
TABLE = 0x00654B70
EP_OP1 = 0x653DA3          # inc [esi+0x28]                  -> 1 byte total
EP_OP5 = 0x653D9F          # add [esi+0x28],4 ; falls through -> 5 bytes total
LOOP_HEAD = 0x6538F0       # dispatch loop head (handler finished its work)
LO, HI = 0x653000, 0x656000


def opcode_name(names, op):
    if op == 0x0A:
        return "(reserved)"
    if 1 <= op <= 0x09:
        return names[84 - op]
    if 0x0B <= op <= 0x55:
        return names[85 - op]
    return "?"


def exe_widths(verbose=True):
    """Read every handler's stream-advance out of the exe.

    Returns (W, ambiguous, lost): W maps opcode -> {1,5} where the handler has a
    single exit, otherwise the opcode is absent (listed in `ambiguous` when both
    1 and 5 are reachable, in `lost` when the trace could not resolve it).
    """
    d = Path(EXE).read_bytes()
    secs = sections(d)

    def v2o(va):
        r = va - IB
        for _, sva, vsz, raw, rsz in secs:
            if sva <= r < sva + max(vsz, rsz):
                return raw + (r - sva)
        return None

    off = v2o(TABLE)
    entries = [struct.unpack_from("<I", d, off + 4 * i)[0] for i in range(85)]
    md = Cs(CS_ARCH_X86, CS_MODE_32)

    def decode(addr):
        o = v2o(addr)
        if o is None:
            return None
        for ins in md.disasm(d[o:o + 16], addr):
            return ins
        return None

    def trace(addr):
        seen, stack = set(), [addr]
        eps, inline, lost = set(), 0, False
        while stack:
            a = stack.pop()
            while True:
                if a in seen:
                    break
                seen.add(a)
                if a == EP_OP1:
                    eps.add(1)
                    break
                if a == EP_OP5:
                    eps.add(5)
                    break
                if a == LOOP_HEAD:
                    eps.add(0)
                    break
                if not (LO <= a < HI):
                    lost = True
                    break
                ins = decode(a)
                if ins is None:
                    lost = True
                    break
                m, ops, nxt = ins.mnemonic, ins.op_str, ins.address + ins.size
                if "[esi + 0x28]" in ops:
                    if m == "add" and ops.rstrip().endswith(", 4"):
                        inline += 4
                    elif m == "inc":
                        inline += 1
                if m in ("ret", "retf", "iret"):
                    eps.add(0)
                    break
                if m == "jmp":
                    if "[" in ops:
                        eps.add(0)
                        break
                    tgt = ops.split()[-1]
                    if not tgt.startswith("0x"):
                        eps.add(0)
                        break
                    a = int(tgt, 16)
                    continue
                if m.startswith("j"):
                    tgt = ops.split()[-1]
                    if tgt.startswith("0x"):
                        stack.append(int(tgt, 16))
                    a = nxt
                    continue
                a = nxt
        return sorted({inline + e for e in eps}), lost

    W, ambiguous, lost = {}, [], []
    for op in range(1, 86):
        cands, was_lost = trace(entries[op - 1])
        if len(cands) == 1 and cands[0] in (1, 5):
            W[op] = cands[0]
        elif len(cands) == 1:
            lost.append((op, f"advance={cands[0]}" + (" lost" if was_lost else "")))
        else:
            ambiguous.append((op, cands))
    if verbose:
        print(f"{len(entries)} handlers read from VA 0x{TABLE:x}")
        print(f"  single-exit (authoritative): {len(W)}   "
              f"ambiguous: {len(ambiguous)}   unresolved: {len(lost)}")
        if lost:
            print("  unresolved: " + ", ".join(f"{o:02x}({w})" for o, w in lost))
        if ambiguous:
            print("  ambiguous:  " + " ".join(f"{o:02x}={c}" for o, c in ambiguous))
    return W, ambiguous, lost


def main():
    d = Path(EXE).read_bytes()
    names = load_names(d, sections(d))
    w_from_exe, both, lost = exe_widths()

    # ---- compare with the data-solved table -------------------------------
    from lasr_vm import load_records
    recs = load_records()
    bodies = [r[2] for r in recs]

    try:
        import json
        solved = {int(k, 16): v for k, v in
                  json.loads(Path("out_w.json").read_text()).items()}
    except Exception:
        solved = {}

    cnt = defaultdict(int)
    for b in bodies:
        p = 0
        while p < len(b):
            cnt[b[p]] += 1
            p += w_from_exe.get(b[p]) or 5

    print(f"\n{'op':>4} {'name':>20} {'exe':>4} {'data':>5} {'agree':>6} {'count':>8}")
    mism = []
    for op in range(1, 86):
        dat = solved.get(op)
        agree = ""
        if dat is not None and w_from_exe.get(op) is not None:
            agree = "OK" if dat == w_from_exe[op] else "**"
            if agree == "**":
                mism.append((op, w_from_exe[op], dat, cnt.get(op, 0)))
        print(f"0x{op:02x} {opcode_name(names, op):>20} "
              f"{str(w_from_exe.get(op)):>4} {str(dat):>5} {agree:>6} {cnt.get(op,0):>8}")
    if mism:
        print("\n>>> disagreements (exe vs data):")
        for op, e, dt, c in mism:
            print(f"    0x{op:02x} {opcode_name(names, op):>20} "
                  f"exe={e} data={dt} count={c}")
    n_ok = sum(1 for op in range(1, 86)
               if w_from_exe.get(op) is not None and solved.get(op) == w_from_exe[op])
    print(f"\n>>> agreement: {n_ok} opcodes, {len(mism)} disagreements "
          f"(single-exit handlers only)")


if __name__ == "__main__":
    main()
