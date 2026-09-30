"""
Anatomy of the untagged 11 MB stream in maps/coastline.rpk (0x20282..0xAB3BBC).

Known facts:
  * the scene directory (the `othe` resource) points only at tagged entries
    after this region, so nothing describes this blob
  * 0xffffffff occurs 48,719 times, spaced a dominant 11 dwords (44 B) or
    13 dwords (52 B) apart
  * the recurring float 0x3f7f95f1 (= 0.99837) suggests a near-unit component

Method is the same one that cracked INVO: find the repeated structure
empirically, then prove it with an invariant that a wrong reading breaks.
"""
import struct
import sys
from collections import Counter
from pathlib import Path

RPK = Path(r"C:\Games\LASR\maps\coastline.rpk")
LO, HI = 0x20282, 0xAB3BBC


def main():
    d = RPK.read_bytes()[LO:HI]
    n = len(d)
    print(f"blob 0x{LO:x}..0x{HI:x}  {n:,} B  ({n/1048576:.2f} MB)")
    print(f"  n % 4 = {n % 4}   n % 44 = {n % 44}   n % 52 = {n % 52}\n")

    # --- 1. sentinel spacing, computed on this exact window ---------------
    pos = [i for i in range(0, n - 3, 4) if d[i:i + 4] == b"\xff\xff\xff\xff"]
    print(f"aligned 0xffffffff : {len(pos):,}")
    dif = Counter((pos[i + 1] - pos[i]) // 4 for i in range(len(pos) - 1))
    print(f"  spacing in dwords: {dif.most_common(8)}")

    # --- 2. near-unit float3 at every alignment, spacing histogram --------
    print("\nnear-unit float3 (|v| in [0.99,1.01]) scan:")
    for align in (0, 4, 8, 12, 16, 20, 24, 28):
        hits = []
        for o in range(align, n - 12, 4):
            x, y, z = struct.unpack_from("<3f", d, o)
            if 0.99 < x * x + y * y + z * z < 1.0201:
                hits.append(o)
        if len(hits) < 50:
            continue
        sp = Counter((hits[i + 1] - hits[i]) // 4 for i in range(len(hits) - 1))
        top = sp.most_common(3)
        print(f"  align {align:>2}: {len(hits):>7,} hits  spacing {top}")

    # --- 3. field profile of the repeating record -------------------------
    # Assume a record starts right after each sentinel run.
    print("\ncontent between consecutive sentinels (first 12 records):")
    for i in range(12):
        a, b = pos[i], pos[i + 1]
        seg = d[a + 4:b + 4]
        f = struct.unpack_from("<%df" % (len(seg) // 4), seg, 0)
        u = struct.unpack_from("<%dI" % (len(seg) // 4), seg, 0)
        print(f"  rec {i:>2} len {len(seg):>3}  f32 {[round(v,4) for v in f]}")
        if len(seg) // 4 <= 14:
            print(f"           u32 {[hex(v) for v in u]}")

    # --- 4. magnitude profile at each in-record offset --------------------
    print("\nper-offset statistics over all records (44 B stride assumption):")
    starts = [p - 40 for p in pos if p >= 40]
    starts = [s for s in starts if s + 44 <= n]
    print(f"  candidate record starts: {len(starts):,}")
    for off in range(0, 44, 4):
        vals = []
        for s in starts[:200000]:
            v, = struct.unpack_from("<f", d, s + off)
            vals.append(v)
        fin = [v for v in vals if v == v and abs(v) < 1e6]
        if not fin:
            print(f"   +{off:>2}  all non-finite")
            continue
        avg = sum(abs(v) for v in fin) / len(fin)
        print(f"   +{off:>2}  finite {len(fin)*100//len(vals):>3}%  "
              f"mean|v| {avg:>12.4f}  min {min(fin):>12.4f}  max {max(fin):>12.4f}")


if __name__ == "__main__":
    main()
