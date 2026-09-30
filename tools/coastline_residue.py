"""
Characterise the ~8.7 MB of the coastline blob that is not 44-byte vertex records.

Approach:
  1. mark every byte that lies inside a real vertex array (44-byte unit-normal
     records) and treat the rest as "unexplained"
  2. for the largest unexplained regions, print per-offset statistics at a
     44-byte stride - if some offset holds large floats, this is a second vertex
     format rather than index data
  3. also score each region as "index-like" (most u16 in range) vs "float-like"
     (most 4-byte windows finite and small)

Usage: python tools/coastline_residue.py
"""
import struct
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

RPK = Path(r"C:\Games\LASR\maps\coastline.rpk")
LO, HI = 0x20282, 0xAB3BBC
REC = 44


def unit_marks(d):
    out = []
    for o in range(0, len(d) - REC, 4):
        nx, ny, nz = struct.unpack_from("<3f", d, o + 28)
        if 0.998 < nx * nx + ny * ny + nz * nz < 1.002:
            out.append(o)
    return out


def main():
    d = RPK.read_bytes()[LO:HI]
    n = len(d)
    marks = unit_marks(d)
    ms = set(marks)

    covered = bytearray(n)
    for o in marks:
        for k in range(REC):
            covered[o + k] = 1
    cov = sum(covered)
    print(f"blob {n:,} B   vertex-record bytes {cov:,} ({100*cov/n:.1f}%)   "
          f"unexplained {n-cov:,} ({100*(n-cov)/n:.1f}%)")

    # contiguous unexplained regions
    regs = []
    i = 0
    while i < n:
        if not covered[i]:
            j = i
            while j < n and not covered[j]:
                j += 1
            if j - i >= 512:
                regs.append((i, j))
            i = j
        else:
            i += 1
    tot = sum(b - a for a, b in regs)
    print(f"unexplained regions >=512 B: {len(regs)}   total {tot:,} B "
          f"({100*tot/n:.1f}%)")

    print(f"\n{'region':>16} {'size':>10} {'u16<512':>8} {'u16<4096':>9} "
          f"{'finite f32':>11} {'dwords==0':>10}")
    for a, b in sorted(regs, key=lambda t: t[1] - t[0], reverse=True)[:14]:
        g = d[a:b]
        n16 = len(g) // 2
        v16 = struct.unpack_from("<%dH" % n16, g, 0)
        s512 = sum(1 for v in v16 if v < 512) * 100 // n16
        s4096 = sum(1 for v in v16 if v < 4096) * 100 // n16
        n32 = len(g) // 4
        f32 = struct.unpack_from("<%df" % n32, g, 0)
        fin = sum(1 for v in f32 if v == v and abs(v) < 1e5) * 100 // n32
        u32 = struct.unpack_from("<%dI" % n32, g, 0)
        z = sum(1 for v in u32 if v == 0) * 100 // n32
        print(f"  0x{a:07x}..0x{b:07x} {b-a:>10,} {s512:>7}% {s4096:>8}% "
              f"{fin:>10}% {z:>9}%")

    # per-offset profile on the largest region at 44-byte stride
    a, b = max(regs, key=lambda t: t[1] - t[0])
    g = d[a:b]
    print(f"\nlargest region 0x{a:07x}..0x{b:07x} ({b-a:,} B): "
          f"per-offset stats at 44-byte stride")
    for off in range(0, 44, 4):
        vals = []
        o = off
        while o + 4 <= len(g):
            v, = struct.unpack_from("<f", g, o)
            vals.append(v)
            o += REC
        fin = [v for v in vals if v == v and abs(v) < 1e5]
        if not fin:
            print(f"  +{off:>2}  all non-finite")
            continue
        print(f"  +{off:>2}  finite {len(fin)*100//len(vals):>3}%  "
              f"mean|v| {sum(abs(v) for v in fin)/len(fin):>11.3f}  "
              f"min {min(fin):>10.3f}  max {max(fin):>10.3f}")

    # do the same at 2-byte stride treating it as u16 lists
    print(f"\nsame region as u16: value histogram buckets")
    n16 = len(g) // 2
    v16 = struct.unpack_from("<%dH" % n16, g, 0)
    buckets = Counter(0 if v == 0 else 1 if v < 16 else 2 if v < 256 else
                      3 if v < 4096 else 4 if v < 32768 else 5
                      for v in v16)
    names = {0: "==0", 1: "1..15", 2: "16..255", 3: "256..4095",
             4: "4096..32767", 5: ">=32768"}
    for k in sorted(buckets):
        print(f"   {names[k]:<12} {buckets[k]:>10,}  "
              f"{100*buckets[k]/n16:5.1f}%")


if __name__ == "__main__":
    main()
