"""
Reconcile the two derived width tables and pick the final one.

Two independent sources now exist:

  * DATA  - hill-climbed so that every TREE record decomposes exactly and the
            operands look like plausible operands (tools/opcode_align2.py).
  * EXE   - read off each handler's stream-advance (tools/handler_advance.py):
            a handler reaching 0x653d9f advances 5, one reaching 0x653da3
            advances 1.  Authoritative but only resolvable for single-exit
            handlers.

For the 10 ambiguous/unresolved opcodes (conditional-branch style handlers with
two exits) the exe says nothing, so the data decides.  This script scores the
candidate tables under one common metric - how many of the 14,796 records
decompose exactly, then how many operands look sane - and writes the winner to
out_w_final.json.

Usage: python tools/reconcile_widths.py
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from handler_advance import exe_widths                      # noqa: E402
from lasr_vm import load_records                            # noqa: E402
from opcode_align2 import lands, score_body                 # noqa: E402

OP_MIN, OP_MAX = 0x01, 0x55


def load_data():
    return {int(k, 16): v for k, v in
            json.loads((HERE.parent / "out_w.json").read_text()).items()}


def measure(tag, W, bodies):
    exact = sum(1 for b in bodies if lands(b, W))
    sane = sum(max(0, score_body(b, W)) for b in bodies)
    print(f"  {tag:<34} exact = {exact:>5}/{len(bodies)} "
          f"({100*exact/len(bodies):6.2f}%)   sane = {sane:>9,}")
    return exact, sane


def main():
    data = load_data()
    W_exe, ambiguous, lost = exe_widths()
    bodies = [r[2] for r in load_records()]

    amb = [op for op, _ in ambiguous] + [op for op, _ in lost]
    print(f"\ndata table: {len(data)} opcodes   exe table: {len(W_exe)} opcodes")
    print(f"deferring to data for: {' '.join(f'{o:02x}' for o in sorted(amb))}")

    # W1: exe wins wherever it speaks, data fills the rest
    W1 = {op: W_exe.get(op, data.get(op)) for op in range(OP_MIN, OP_MAX + 1)}
    # W1a: same, but trust the exe on the two opcodes where it disagrees with
    # the hill-climb (it costs nothing: the data scores them identically, so
    # only the binary can settle them)
    W1a = dict(W1)
    for op in range(OP_MIN, OP_MAX + 1):
        if op in W_exe:
            W1a[op] = W_exe[op]

    cands = [("V0 data only (baseline)", dict(data)),
             ("V1 exe where it speaks", dict(W1)),
             ("V1a exe-authoritative (primary)", dict(W1a))]

    for op in (0x3A, 0x3C):                     # exe=1, data=5
        if W_exe.get(op) == 1 and data.get(op) == 5:
            v = dict(W1); v[op] = 1
            cands.append((f"V1 + force 0x{op:02x}={1} (exe)", v))
    for op in (0x3E, 0x3F):                     # ambiguous: exe sees {1,5}
        v = dict(W1); v[op] = 5
        cands.append((f"V1 + force 0x{op:02x}=5 (operand path)", v))
    for op in (0x16, 0x17):                     # ambiguous / unresolved
        v = dict(W1); v[op] = 5
        cands.append((f"V1 + force 0x{op:02x}=5", v))

    print("\nscoring candidates:")
    scored = [(measure(tag, W, bodies), tag, W) for tag, W in cands]

    top = max(s[0][0] for s in scored)
    tied = [s for s in scored if s[0][0] == top]
    # On a tie prefer the exe-informed table: reading each handler's stream
    # advance out of the binary is stronger evidence than fitting the data, and
    # the data cannot separate the two (e.g. the rare 0x3a/0x3c score the same
    # at width 1 or 5, so only the binary can settle them).
    pref = [s for s in tied if s[1].startswith("V1a")] or \
           [s for s in tied if s[1].startswith("V1")] or tied
    (be, bs), tag, W = pref[0]
    print(f"\n>>> winner: {tag}   exact={be}  sane={bs:,}")
    if len(tied) > 1:
        print(f"    ({len(tied)} candidates tied at the top; exe-informed preferred)")

    # ---- consistency checks on the winner ---------------------------------
    w1 = [op for op in range(OP_MIN, OP_MAX + 1) if W[op] == 1]
    print(f"\nwidth 1 ({len(w1)}): " + " ".join(f"{o:02x}" for o in w1))
    print("width 5: " + " ".join(f"{o:02x}" for o in range(OP_MIN, OP_MAX + 1)
                                 if W[op] == 5))
    bad = [op for op in range(OP_MIN, OP_MAX + 1) if W.get(op) not in (1, 5)]
    if bad:
        print("!! widths not in {1,5}: " + " ".join(f"{o:02x}" for o in bad))

    # opcode 0x0a must never be emitted and has no handler; 0x16 terminates
    (HERE.parent / "out_w_final.json").write_text(
        json.dumps({f"{op:02x}": W[op] for op in range(OP_MIN, OP_MAX + 1)},
                   indent=0))
    print("\nwritten: out_w_final.json")


if __name__ == "__main__":
    main()
