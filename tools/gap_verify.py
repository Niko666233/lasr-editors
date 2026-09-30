"""
Decode the map-archive "scene/resource directory" and verify it against the
original .rpk.

Record layout, proven by the autofit walk + column diff (tools/gap_fields.py):
    u16 type ; u16 group ; u32 A ; u32 B ; f32 scale(=1.0) ; u32 offset ; u32 size
    u8 nameLen ; char name[nameLen]        (nameLen includes the NUL)
    22 bytes fixed.

The column diff showed size == offset(next) - offset(this) exactly, which is the
signature of a resource directory with absolute file offsets.  This tool checks
that every offset lands on a well-formed `<tag><u32 size>` entry in the real
.rpk and that the declared size matches.
"""
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from gap_walk import autofit  # noqa: E402

RPK = Path(r"C:\Games\LASR")


def printable(b):
    return all(0x20 <= c < 0x7F for c in b)


def entry_at(d, off):
    if off + 8 > len(d):
        return None
    tag = d[off:off + 4]
    if not printable(tag):
        return None
    size, = struct.unpack_from("<I", d, off + 4)
    if not 0 < size <= len(d) - off - 8:
        return None
    return tag.decode(), size


def top_entries(d):
    """Top-level `<tag><u32 size>` entries of an .rpk (continuous walk)."""
    out = []
    off = 0x208
    while off + 8 <= len(d):
        e = entry_at(d, off)
        if not e:
            break
        out.append((off, e[0], e[1]))
        off += 8 + e[1]
    return out


def main():
    gap = Path(sys.argv[1])
    rel = str(gap).replace("\\", "/")
    parts = rel.split("extracted_rpak/", 1)[-1].split("/")
    rpk = RPK.joinpath(*parts[:-1]).with_name(parts[-2] + ".rpk")
    print(f"gap : {gap}")
    print(f"rpk : {rpk}  ({'OK' if rpk.exists() else 'MISSING'}) "
          f"{rpk.stat().st_size:,} B" if rpk.exists() else "")
    d = rpk.read_bytes()

    start, fixed, recs, end = autofit(gap.read_bytes())
    tops = top_entries(d)
    print(f"records: {len(recs)}   layout start={start} fixed={fixed}")
    print(f"top-level rpk entries: {len(tops)}")
    import collections
    print(f"  {dict(collections.Counter(t for _, t, _ in tops))}\n")

    g = gap.read_bytes()
    inside = collections.Counter()
    exact = plus8 = miss = 0
    print(f"  {'#':>3} {'type':>4} {'grp':>3} {'A':>6} {'B':>5} "
          f"{'offset':>12} {'size':>12}  containment        name")
    for i, r in enumerate(recs):
        raw = g[r[0]:r[0] + fixed]
        typ, grp = struct.unpack_from("<HH", raw, 0)
        a, b = struct.unpack_from("<II", raw, 4)
        off, size = struct.unpack_from("<II", raw, 14)
        e = entry_at(d, off)
        if e and e[1] + 8 == size:
            plus8 += 1
            cont = f"top {e[0]} (exact)"
        elif e:
            exact += 1
            cont = f"top {e[0]} (size {e[1]:,})"
        else:
            miss += 1
            holder = [t for t in tops if t[0] < off < t[0] + 8 + t[2]]
            if holder:
                h = holder[0]
                cont = f"inside {h[1]}+{off-h[0]:,} (hdr {h[0]:,})"
                inside[h[1]] += 1
            else:
                cont = "?? unowned"
        if i < 24 or i > len(recs) - 4:
            print(f"  {i:>3} {typ:>4} {grp:>3} {a:>6} {b:>5} "
                  f"{off:>12,} {size:>12,}  {cont:<30} {r[8]}")

    print(f"\n  size == entry.size + 8 (exact)     : {plus8}/{len(recs)}")
    print(f"  size == entry.size (no header)     : {exact}")
    print(f"  offset not a top-level entry       : {miss}")
    print(f"  ...of those, inside a container    : {dict(inside)}")
    print(f"  scale values: "
          f"{sorted({struct.unpack_from('<f', g, r[0]+10)[0] for r in recs})[:5]}")
    print(f"  type histogram: "
          f"{sorted(collections.Counter(struct.unpack_from('<H', g, r[0])[0] for r in recs).items())}")


if __name__ == "__main__":
    main()
