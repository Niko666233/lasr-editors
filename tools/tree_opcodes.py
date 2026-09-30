"""
Recover the TREE blob opcode format by sound constraint propagation.

Model: a blob is a sequence of frames; a frame is <u8 opcode> optionally
followed by an operand.  Operand width is unknown; candidates are {0,1,2,4,8}.

Sound algorithm
---------------
For a blob B, a frame (position i, opcode B[i], width w) is *on a valid path*
iff i is forward-reachable and i+1+w is backward-co-finishable, both computed
over the free model (widths unconstrained, monotone BFS).

If in some blob an opcode occurs on valid paths with only ONE width, and that
holds in every blob it occurs in, then that width is the opcode's real width
(a width is a property of the opcode, not of a blob).  Pinning opcodes shrinks
the free model, which can make previously ambiguous blobs unambiguous, so we
iterate to a fixpoint.  Whatever is still ambiguous is reported as ambiguous,
never guessed.

Usage:
  python tools/tree_opcodes.py                -> opcode table (markdown)
  python tools/tree_opcodes.py --dump NAME    -> frame dump of one class
"""
import collections
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EX = ROOT / "extracted"
CAND = (0, 4)


def tufa_chunks(data):
    off = 12
    while off + 8 <= len(data):
        tag = data[off:off + 4].decode("latin1")
        size = struct.unpack_from("<I", data, off + 4)[0]
        yield tag, data[off + 8:off + 8 + size]
        off += 8 + size


def tree_blobs(data):
    for tag, payload in tufa_chunks(data):
        if tag != "TREE":
            continue
        n = struct.unpack_from("<I", payload, 0)[0]
        off = 4
        for _ in range(n):
            s = struct.unpack_from("<I", payload, off)[0]
            off += 4
            blob = payload[off:off + s]
            off += s
            if blob:
                yield blob


def load_blobs():
    out = []
    for p in sorted(EX.rglob("*.class")):
        d = p.read_bytes()
        if d[:4] != b"TUFA":
            continue
        out.extend(tree_blobs(d))
    return out


def reach(b, pinned):
    n = len(b)
    wa = [pinned.get(b[i]) or CAND for i in range(n)]
    fwd = bytearray(n + 1)
    fwd[0] = 1
    for i in range(n):
        if not fwd[i]:
            continue
        for w in wa[i]:
            if i + 1 + w <= n:
                fwd[i + 1 + w] = 1
    bwd = bytearray(n + 1)
    bwd[n] = 1
    for i in range(n - 1, -1, -1):
        for w in wa[i]:
            if i + 1 + w <= n and bwd[i + 1 + w]:
                bwd[i] = 1
                break
    return wa, fwd, bwd


def analyse(blobs, pinned):
    weights = collections.defaultdict(collections.Counter)
    appear = collections.Counter()
    for b in blobs:
        wa, fwd, bwd = reach(b, pinned)
        local = collections.defaultdict(set)
        for i in range(len(b)):
            if not fwd[i]:
                continue
            for w in wa[i]:
                if i + 1 + w <= len(b) and bwd[i + 1 + w]:
                    local[b[i]].add(w)
        for op, ws in local.items():
            appear[op] += 1
            for w in ws:
                weights[op][w] += 1
    return weights, appear


def main():
    blobs = load_blobs()
    print(f"{len(blobs)} TREE records loaded", file=sys.stderr)

    if "--dump" in sys.argv:
        target = sys.argv[sys.argv.index("--dump") + 1]
        p = next(EX.rglob(target))
        d = p.read_bytes()
        print(f"=== {p.relative_to(EX)} ({len(d)} B) ===")
        for k, b in enumerate(tree_blobs(d)):
            print(f"\n--- TREE record {k} ({len(b)} B)")
            i = 0
            while i < len(b):
                print(f"   {i:5d}  {b[i]:#04x}  {b[i+1:i+5].hex(' ')}")
                i += 5
        return

    pinned = {}
    for it in range(30):
        weights, appear = analyse(blobs, pinned)
        new = {op: next(iter(ws)) for op, ws in weights.items()
               if len(ws) == 1 and op not in pinned}
        if not new:
            print(f"fixpoint after {it} iterations", file=sys.stderr)
            break
        pinned.update(new)
        print(f"iter {it}: +{len(new)} pinned -> {len(pinned)} total",
              file=sys.stderr)

    bad = 0
    for b in blobs:
        _, fwd, _ = reach(b, pinned)
        if not fwd[len(b)]:
            bad += 1
    print(f"blobs failing to close under pinned widths: {bad}/{len(blobs)}",
          file=sys.stderr)

    weights, appear = analyse(blobs, pinned)
    ambiguous = {op: sorted(ws) for op, ws in weights.items() if len(ws) > 1}

    print("# TREE opcode table\n")
    print(f"Analysed **{len(blobs)} TREE records** from 2224 decoded classes.\n")
    print(f"Resolved: **{len(pinned)}** opcodes.  "
          f"Still ambiguous: **{len(ambiguous)}**.  "
          f"Distinct opcodes observed: **{len(appear)}**.\n")
    print("## Resolved operand widths\n")
    print("| opcode | operand bytes | records where seen |")
    print("|---|---|---|")
    for op in sorted(pinned):
        print(f"| `{op:#04x}` | {pinned[op]} | {appear[op]} |")
    print("\n## Still ambiguous\n")
    print("| opcode | possible widths | records where seen |")
    print("|---|---|---|")
    for op in sorted(ambiguous):
        print(f"| `{op:#04x}` | {ambiguous[op]} | {appear[op]} |")


if __name__ == "__main__":
    main()
