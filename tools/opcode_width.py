"""
Solve the per-opcode instruction width by constraint propagation.

Facts we can rely on:

* every TREE method record ends with the terminator byte 0x16 (14796/14805)
* the longest clean records parse as repeated `<u8 opcode><u32 operand>`,
  i.e. width 5 for those opcodes
* but 71% of record bodies are not a multiple of 5, so some opcodes take no
  operand (width 1)

So the widths live in {1, 5} and the terminator gives an exact end condition.
For each record, enumerate every width assignment that consumes the body
exactly and lands on the trailing 0x16.  An opcode whose width is the same in
every surviving assignment is *proven*; iterate to a fixpoint.

Usage: python tools/opcode_width.py [--cap 4000]
"""
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from opcode_table import chunks, tree_records      # noqa: E402

WIDTHS = (1, 5)


def all_parses(body, forced, cap, maxsteps=200000):
    """Every list of (offset, opcode, width) consuming body exactly.

    Iterative: long bodies overflow the Python recursion limit, and width-1
    chains make the depth equal to the body length.

    Returns (parses, complete).  ``complete`` is False when the search was cut
    off, in which case the result is a subset of the real parses and MUST NOT
    be used to force widths.
    """
    L = len(body)
    out = []
    stack = [(0, ())]
    steps = 0
    complete = True
    while stack:
        pos, path = stack.pop()
        steps += 1
        if steps > maxsteps:
            complete = False
            break
        if pos == L:
            out.append(path)
            if len(out) >= cap:
                complete = False
                break
            continue
        if pos > L:
            continue
        op = body[pos]
        ws = (forced[op],) if op in forced else WIDTHS
        for w in ws:
            if pos + w <= L:
                stack.append((pos + w, path + ((pos, op, w),)))
    return out, complete


def main():
    cap = 4000
    if "--cap" in sys.argv:
        cap = int(sys.argv[sys.argv.index("--cap") + 1])

    files = sorted(Path("extracted").rglob("*.class"))
    recs = []
    for f in files:
        try:
            ck = chunks(f.read_bytes())
        except Exception:
            continue
        if "TREE" in ck:
            try:
                recs += [(f.stem, r) for r in tree_records(ck["TREE"][0])]
            except Exception:
                pass
    recs = [(n, r) for n, r in recs if r and r[-1] == 0x16]
    print(f"{len(files)} class files, {len(recs)} terminated TREE records")

    bodies = sorted(((n, r[:-1]) for n, r in recs), key=lambda t: len(t[1]))
    # seeds proven by reading common record bodies directly:
    #   body 12 : "0b 00 00 00 00 10 3f 00 00 00 29"          -> 0x29 is 1 byte
    #   body 22 : "... 2e ... 2e"                             -> 0x2e is 1 byte
    #   body 23 : "... 1c ... 36 ... 1b ..."                   -> 1 byte each
    #   body 16 : "27 .. 2a 08 .."                             -> 0x2a is 1 byte
    forced = {0x03: 1, 0x1B: 1, 0x1C: 1, 0x29: 1, 0x2A: 1, 0x2E: 1, 0x36: 1}
    for it in range(1, 60):
        votes = defaultdict(set)
        unsolved = skipped = 0
        for name, body in bodies:
            ps, complete = all_parses(body, forced, cap)
            if not ps:
                unsolved += 1
                continue
            if not complete:
                skipped += 1        # subset of parses: cannot force anything
                continue
            # opcodes used in EVERY parse -> their width is settled
            common = None
            for p in ps:
                d = {op: w for _, op, w in p}
                common = d if common is None else \
                    {k: v for k, v in common.items() if d.get(k) == v}
                if not common:
                    break
            if common:
                for k, v in common.items():
                    votes[k].add(v)
        new = dict(forced)
        new.update({k: next(iter(v)) for k, v in votes.items() if len(v) == 1})
        if new == forced:
            print(f"fixpoint after {it} iterations; unsolvable records: "
                  f"{unsolved}, enumeration truncated on: {skipped}")
            break
        forced = new
        print(f"iter {it}: {len(forced)} opcodes pinned, "
              f"{unsolved} records without a parse")

    w1 = sorted(k for k, v in forced.items() if v == 1)
    w5 = sorted(k for k, v in forced.items() if v == 5)
    print(f"\nwidth 1 (no operand): {len(w1)}")
    print("   " + " ".join(f"{v:02x}" for v in w1))
    print(f"width 5 (u32 operand): {len(w5)}")
    unused = sorted(set(range(84)) - set(forced))
    print(f"\nnever observed / unresolved: {len(unused)}")
    print("   " + " ".join(f"{v:02x}" for v in unused))

    # final validation: how many records parse exactly with these widths?
    good = bad = 0
    for name, body in bodies:
        pos = 0
        ok = True
        while pos < len(body):
            op = body[pos]
            w = forced.get(op)
            if w is None:
                ok = False
                break
            pos += w
        if ok and pos == len(body):
            good += 1
        else:
            bad += 1
    print(f"\nrecords parsed exactly with the pinned table: {good}/{good+bad}"
          f"  ({100*good/(good+bad):.1f}%)")


if __name__ == "__main__":
    main()
