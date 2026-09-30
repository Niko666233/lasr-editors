"""
Final validation of the reconciled width table (out_w_final.json).

Re-decomposes every TREE record from scratch with an independent walker and
asserts the invariants that must hold if the table is the engine's real one:

  * every opcode byte lies in 0x01..0x55   (dispatcher @0x6538f0: dec; cmp 0x54; ja)
  * every record lands exactly on its end   (no record needs padding/gaps)
  * 0x0a never appears                      (reserved hole: no handler, no name)
  * every opcode taking an operand is one the exe's own handlers say takes one

Usage: python tools/verify_widths.py
"""
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from lasr_vm import load_records                            # noqa: E402

OP_MIN, OP_MAX = 0x01, 0x55


def main():
    W = {int(k, 16): v for k, v in
         json.loads((HERE.parent / "out_w_final.json").read_text()).items()}
    assert set(W) == set(range(OP_MIN, OP_MAX + 1)), "table is not 1..0x55"
    assert all(v in (1, 5) for v in W.values()), "width outside {1,5}"

    recs = load_records()
    cnt, nbad, nbyte, nins = Counter(), 0, 0, 0
    firsts, lasts = Counter(), Counter()
    for _, _, body in [(r[0], r[1], r[2]) for r in recs]:
        pos, n = 0, len(body)
        ops = []
        while pos < n:
            op = body[pos]
            if op < OP_MIN or op > OP_MAX:
                nbad += 1
                break
            ops.append(op)
            pos += W[op]
        if pos != n:
            nbad += 1
            continue
        nins += len(ops)
        nbyte += n
        cnt.update(ops)
        if ops:
            firsts[ops[0]] += 1
            lasts[ops[-1]] += 1

    n = len(recs)
    print(f"records                : {n}")
    print(f"records parsed exactly : {n - nbad}  ({100*(n-nbad)/n:.2f}%)")
    print(f"malformed              : {nbad}")
    print(f"instructions           : {nins:,}   bytes {nbyte:,}   "
          f"mean {nbyte/nins:.2f} B/instr")
    print(f"width-1 opcodes        : {sum(1 for v in W.values() if v == 1)}"
          f"   width-5: {sum(1 for v in W.values() if v == 5)}")
    print(f"opcodes actually used  : {len(cnt)} of 85")

    unused = [op for op in range(OP_MIN, OP_MAX + 1) if op not in cnt]
    print(f"never emitted          : {len(unused)} -> "
          + " ".join(f"{o:02x}" for o in unused))
    if 0x0A in cnt:
        print(f"!! 0x0a (reserved hole) appeared {cnt[0x0A]} times")
    else:
        print("0x0a reserved hole     : confirmed never emitted")

    print("\ntop opcodes:")
    from opcode_table import load_names, sections
    d = Path(r"C:\Games\LASR\LASR.exe").read_bytes()
    names = load_names(d, sections(d))

    def nm(op):
        return names[84 - op] if 1 <= op <= 0x09 else names[85 - op]

    for op, c in cnt.most_common(15):
        print(f"  0x{op:02x} {nm(op):>20} {c:>8}")
    print("\nmost common first instruction of a method:")
    for op, c in firsts.most_common(6):
        print(f"  0x{op:02x} {nm(op):>20} {c:>6}")
    print("\nmost common last instruction (before the 0x16 terminator):")
    for op, c in lasts.most_common(6):
        print(f"  0x{op:02x} {nm(op):>20} {c:>6}")

    # opcodes the exe's handlers say take an operand must be width 5 here
    from handler_advance import exe_widths
    W_exe, _, _ = exe_widths(verbose=False)
    disagree = [op for op in sorted(W_exe) if W_exe[op] != W[op]]
    print(f"\nexe-derived widths: {len(W_exe)} opcodes, "
          f"{len(disagree)} disagree with the final table"
          + (" -> " + " ".join(f"{o:02x}" for o in disagree) if disagree else ""))


if __name__ == "__main__":
    main()
