"""
RPAK extractor.

Verified layout of an .rpk archive:

    "RPAK" <u32 index_size> <index_size bytes>      index (0x200 in all shipped
                                                    archives; 512 bytes)
    then resources:

    <4-byte ASCII tag> <u32 size> <size bytes>

Resources are normally contiguous from the first entry after the index, but a
few archives interleave gaps, so the walker reseeds on the next valid entry
whenever the chain breaks and reports the uncovered bytes.

Tags discovered so far:
    ISCX  mesh   (payload starts with the INVO magic)
    IDDS  texture (payload is a DDS file, DXT5)
    m_ic  nested container block
    RPAK  the archive header itself, treated as an entry

Usage:
  python tools/rpak_extract.py OUTDIR ARCHIVE [ARCHIVE...]
  python tools/rpak_extract.py OUTDIR --all
"""
import collections
import re
import sys
from pathlib import Path

GAME = Path(r"C:\Games\LASR")
MAGICS = (b"DDS ", b"INVO", b"TUFA", b"RPAK")
EXT = {"IDDS": ".dds", "ISCX": ".iscx", "m_ic": ".bin"}
SAFE = re.compile(r"[^A-Za-z0-9_]")


def longest_chain(d, start):
    """Longest strict chain from any offset >= start (clean, no reseeding)."""
    n = len(d)
    memo = {}

    def longest(off):
        if off in memo:
            return memo[off]
        memo[off] = 0
        if off + 8 > n:
            return 0
        tag = d[off:off + 4]
        if not all(0x20 <= c < 0x7F for c in tag):
            return 0
        size = int.from_bytes(d[off + 4:off + 8], "little")
        if size == 0 or off + 8 + size > n:
            return 0
        memo[off] = 1 + longest(off + 8 + size)
        return memo[off]

    best, bestoff = 0, start
    for off in range(start, max(start, n - 8)):
        v = longest(off)
        if v > best:
            best, bestoff = v, off
    return bestoff, best


def entry_at(d, off):
    n = len(d)
    if off + 8 > n:
        return None
    tag = d[off:off + 4]
    if not all(0x20 <= c < 0x7F for c in tag):
        return None
    size = int.from_bytes(d[off + 4:off + 8], "little")
    if size == 0 or off + 8 + size > n:
        return None
    return tag, size


def walk(d, start, end, whitelist):
    """Contiguous walk. Any well-formed entry at the cursor is taken; the
    whitelist / payload magic is only used to decide where to reseed after a
    break, so recovering across gaps cannot drag in random bytes."""
    off = start
    ents = []
    gaps = []
    n = min(len(d), end)
    while off + 8 <= n:
        e = entry_at(d, off)
        if e:
            tag, size = e
            ts = tag.decode("latin1")
            ents.append((SAFE.sub("_", ts), ts, off, size))
            off += 8 + size
            continue
        nxt = off + 1
        while nxt + 8 <= n:
            e2 = entry_at(d, nxt)
            if e2 and (e2[0] in whitelist or d[nxt + 8:nxt + 12] in MAGICS):
                break
            nxt += 1
        if nxt + 8 > n:
            break
        gaps.append((off, nxt))
        off = nxt
    return ents, gaps


def main():
    outdir = Path(sys.argv[1])
    args = sys.argv[2:]
    files = (sorted(GAME.rglob("*.rpk")) if (not args or args == ["--all"])
             else [Path(a) for a in args])

    grand = collections.Counter()
    total_gap = 0
    for f in files:
        d = f.read_bytes()
        idx = int.from_bytes(d[4:8], "little") if d[:4] == b"RPAK" else 0
        start = 8 + idx
        cstart, _ = longest_chain(d, start)
        clean, _ = walk(d, cstart, len(d), set())
        whitelist = {tag for _, tag, _, _ in clean}
        ents, gaps = walk(d, start, len(d), whitelist)
        if not ents:
            print(f"{f.name:32s} no resources")
            continue
        rel = f.relative_to(GAME).with_suffix("")
        dest = outdir / rel
        dest.mkdir(parents=True, exist_ok=True)
        hist = collections.Counter()
        for i, (safe, tag, off, size) in enumerate(ents):
            (dest / f"{i:04d}_{safe}{EXT.get(tag, '.bin')}").write_bytes(
                d[off + 8:off + 8 + size])
            hist[safe] += 1
            grand[safe] += 1
        cov = sum(s + 8 for _, _, _, s in ents)
        total_gap += sum(b - a for a, b in gaps)
        # preserve anything the entry walk could not claim, so no bytes are lost
        for j, (a, b) in enumerate(gaps):
            if b - a >= 64:
                (dest / f"gap{j:02d}_{a:08x}.bin").write_bytes(d[a:b])
        print(f"{f.name:32s} {len(ents):5d} res  {cov:>11,} B extracted  "
              f"{len(gaps)} gaps ({sum(b-a for a,b in gaps):,} B)  "
              f"{dict(hist.most_common(6))}")
    print(f"\ntotal by tag: {dict(grand.most_common(30))}")
    print(f"total uncovered (gap) bytes: {total_gap:,}")


if __name__ == "__main__":
    main()
