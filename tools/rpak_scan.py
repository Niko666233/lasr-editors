"""
Carve resources out of an .rpk.

Verified model: a resource is <4 printable ASCII chars><u32 size><size bytes>,
and consecutive resources chain exactly (entry[n+1] starts where entry[n] ends).

The build treats every offset as a node whose edge goes to off+8+size when that
offset is itself a valid entry start, then takes the longest path in that DAG.
That is O(n) with memoisation and finds the real index/data chain without
guessing where it begins.

Usage:
  python tools/rpak_scan.py <file.rpk> [--dump TAG:OUTDIR]
"""
import collections
import sys
from pathlib import Path

MEMO = {}


def tag_ok(b):
    return len(b) == 4 and all(0x20 <= c < 0x7F for c in b)


def succ(d, off, n):
    if off + 8 > n:
        return None
    tag = d[off:off + 4]
    if not tag_ok(tag):
        return None
    size = int.from_bytes(d[off + 4:off + 8], "little")
    if size == 0 or off + 8 + size > n:
        return None
    return tag.decode("latin1"), size


def longest(d, off, n):
    if off in MEMO:
        return MEMO[off]
    MEMO[off] = (0, [])
    s = succ(d, off, n)
    if s is None:
        return MEMO[off]
    tag, size = s
    rest_cnt, rest_entries = longest(d, off + 8 + size, n)
    MEMO[off] = (1 + rest_cnt, [(tag, off, size)] + rest_entries)
    return MEMO[off]


def main():
    p = Path(sys.argv[1])
    d = p.read_bytes()
    n = len(d)
    print(f"=== {p.name}  {n:,} bytes ===")

    MEMO.clear()
    sys.setrecursionlimit(200000)
    best = (0, [], 0)
    for off in range(0, max(0, n - 8)):
        c, e = longest(d, off, n)
        if c > best[0]:
            best = (c, e, off)
    cnt, entries, start = best
    end = entries[-1][1] + 8 + entries[-1][2] if entries else start
    print(f"longest chain: {cnt} entries from {start:#x} to {end:#x} "
          f"({100*(end-start)/n:.1f}% of file)")

    hist = collections.Counter(t for t, _, _ in entries)
    tot = collections.Counter()
    for t, _, s in entries:
        tot[t] += s
    print(f"\n{len(hist)} distinct tags. Top 30 by bytes:")
    for t, v in tot.most_common(30):
        print(f"   {t!r:8s} count={hist[t]:<6d} bytes={v:,}")
    print("\nfirst 20 entries:")
    for t, o, s in entries[:20]:
        print(f"   {t!r:8s} off {o:#010x}  size {s:#010x} ({s:,})")

    if "--dump" in sys.argv:
        spec = sys.argv[sys.argv.index("--dump") + 1]
        tag, _, outdir = spec.partition(":")
        od = Path(outdir)
        od.mkdir(parents=True, exist_ok=True)
        k = 0
        for t, o, s in entries:
            if t != tag:
                continue
            (od / f"{k:04d}_{t}.bin").write_bytes(d[o + 8:o + 8 + s])
            k += 1
        print(f"\ndumped {k} {tag!r} payloads to {od}")


if __name__ == "__main__":
    main()
