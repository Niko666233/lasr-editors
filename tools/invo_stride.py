"""
Fit the INVO vertex stride by looking for runs of unit-length float32 triples
(vertex normals).  A regular spacing between consecutive unit triples is the
stride; the offset of the run is the normal attribute's offset.

Usage: python tools/invo_stride.py FILE
"""
import struct
import sys
from pathlib import Path


def regions(d):
    ver, n = struct.unpack_from("<2I", d, 4)
    pairs = [struct.unpack_from("<2I", d, 0x0C + 8 * i) for i in range(n)]
    offs = sorted({o for _, o in pairs if 0 < o < len(d)} | {len(d)})
    out = []
    for kind, off in pairs:
        nxt = next((b for b in offs if b > off), len(d))
        out.append((kind, off, nxt))
    return ver, n, pairs, out


def unit_runs(blk, lo=0.98, hi=1.02):
    """All start offsets where 3 consecutive floats form a unit vector."""
    hits = []
    n = len(blk) // 4
    f = struct.unpack_from("<%df" % n, blk, 0)
    for i in range(n - 2):
        x, y, z = f[i], f[i + 1], f[i + 2]
        m = (x * x + y * y + z * z) ** 0.5
        if lo <= m <= hi:
            hits.append(i * 4)
    return hits


def main():
    p = Path(sys.argv[1])
    d = p.read_bytes()
    ver, n, pairs, regs = regions(d)
    print(f"=== {p.name}  {len(d):,} B  N={n}")
    print("   pairs:", [(k, hex(o)) for k, o in pairs])

    for kind, a, b in regs:
        blk = d[a:b]
        tag = f"kind={kind} {a:#x}..{b:#x} ({len(blk):,}B)"
        if len(blk) < 16:
            print(f"\n  {tag}\n     {blk.hex(' ')}")
            continue
        hdr = struct.unpack_from("<4I", blk, 0)
        print(f"\n  {tag}  hdr(kind,size,count,x)="
              f"{[hex(v) for v in hdr]}")
        hits = unit_runs(blk)
        if not hits:
            print(f"     units: none")
            continue
        gaps = [hits[i + 1] - hits[i] for i in range(len(hits) - 1)]
        small = [g for g in gaps if 0 < g <= 256]
        from collections import Counter
        print(f"     unit float3 at {len(hits)} offsets; "
              f"spacing histogram {Counter(small).most_common(6)}")
        if small:
            stride, cnt = Counter(small).most_common(1)[0]
            print(f"     -> dominant stride {stride} ({cnt} runs), "
                  f"first unit triple at +{hits[0]:#x} "
                  f"(in-vertex offset {hits[0] % stride if stride else 0})")
            print(f"     -> implied vertex count ~ {len(blk)//stride}")


if __name__ == "__main__":
    main()
