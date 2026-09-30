"""
Recover the per-opcode instruction width by hill-climbing on operand sanity.

Layout established by reading whole record bodies:

    <u8 opcode> <4-byte payload>     for most opcodes
    <u8 opcode>                      for a few (no payload)

So each record's body must decompose into steps of 1 or 5 bytes that land
exactly on its end.  Which opcodes take the 1-byte form is unknown, and
per-record enumeration explodes (each body of length L has ~Fib(L) parses), so
solve it globally instead.

Objective: sum over records of the number of *sane* 4-byte payloads, where a
payload is sane if it is a plausible index (`< 2**24`) or a plausible float
literal (finite, `|v| < 1e6`).  A misaligned parse consumes payload bytes from
the middle of neighbouring instructions, and random 4-byte windows are insane
~99% of the time, so this objective separates the true width table sharply.
Records that do not land exactly on their terminator contribute nothing.

Usage: python tools/opcode_align.py [--rounds 40]
"""
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from opcode_table import chunks, tree_records      # noqa: E402

LIM_INT = 1 << 24
LIM_FLT = 1e6
WIDTHS = (1, 5)
MAX_OP = 0x54          # the .rdata name table has 85 entries, so valid opcode
                       # bytes are 0x00..0x54; a parse that puts anything larger
                       # at an instruction boundary is wrong


def sane(payload):
    if payload < LIM_INT:
        return 1
    v, = struct.unpack("<f", struct.pack("<I", payload))
    if v == v and abs(v) < LIM_FLT:
        return 1
    return 0


def score_body(body, W):
    pos = 0
    n = len(body)
    tot = 0
    while pos < n:
        op = body[pos]
        if op > MAX_OP:
            return -1              # byte cannot be an opcode
        w = W.get(op)
        if w is None:
            return -1
        if pos + w > n:
            return -1
        if w == 5:
            tot += sane(struct.unpack_from("<I", body, pos + 1)[0])
        pos += w
    return tot if pos == n else -1


def main():
    rounds = 40
    if "--rounds" in sys.argv:
        rounds = int(sys.argv[sys.argv.index("--rounds") + 1])

    recs = []
    for f in sorted(Path("extracted").rglob("*.class")):
        try:
            ck = chunks(f.read_bytes())
        except Exception:
            continue
        if "TREE" in ck:
            try:
                recs += [r[:-1] for r in tree_records(ck["TREE"][0])
                         if r and r[-1] == 0x16]
            except Exception:
                pass
    print(f"{len(recs)} terminated TREE records")

    def total(W):
        return sum(t for t in (score_body(b, W) for b in recs) if t > 0)

    W = {k: 5 for k in range(256)}
    for k in (0x03, 0x1B, 0x1C, 0x26, 0x29, 0x2A, 0x2E, 0x36):
        W[k] = 1
    best = total(W)
    print(f"start (seeded): sane payloads = {best:,}")

    for r in range(rounds):
        improved = False
        for op in sorted({b[i] for b in recs for i in range(len(b))}):
            trial = dict(W)
            trial[op] = 5 if W[op] == 1 else 1
            s = total(trial)
            if s > best:
                best, W, improved = s, trial, True
                print(f"  round {r}: opcode {op:#04x} -> width {W[op]}   "
                      f"sane = {s:,}")
        if not improved:
            print(f"converged after {r} rounds")
            break

    w1 = sorted(k for k, v in W.items() if v == 1)
    print(f"\nwidth 1 (no payload): {len(w1)}")
    print("   " + " ".join(f"{v:02x}" for v in w1))

    exact = sum(1 for b in recs if score_body(b, W) > 0)
    print(f"\nrecords parsing exactly: {exact}/{len(recs)} "
          f"({100*exact/len(recs):.1f}%)")

    # how many records still fail, and do they contain unseen opcodes?
    bad = [b for b in recs if score_body(b, W) <= 0]
    print(f"\nrecords that still fail: {len(bad)}")
    for b in bad[:5]:
        print(f"   len={len(b)} {b.hex(' ')}")


if __name__ == "__main__":
    main()
