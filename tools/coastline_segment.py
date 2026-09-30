"""
Re-segment the coastline stream by the unit-normal invariant instead of by the
white vertex colour.

The earlier pass found vertex blocks by looking for u32 0xffffffff (a white
vertex colour).  That misses every sub-mesh whose vertices are not white, which
is most of the 11 MB.  A vertex record has a unit-length normal at +28, so the
block structure can be found colour-blind:

    mark(o) = |float3 @ o+28| == 1   (o 4-aligned)
    a vertex array is a maximal run of marks spaced exactly 44 bytes

Usage: python tools/coastline_segment.py
"""
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

RPK = Path(r"C:\Games\LASR\maps\coastline.rpk")
LO, HI = 0x20282, 0xAB3BBC
REC = 44


def unit_at(d, o):
    if o + 44 > len(d):
        return False
    nx, ny, nz = struct.unpack_from("<3f", d, o + 28)
    L = nx * nx + ny * ny + nz * nz
    return 0.998 < L < 1.002


def main():
    d = RPK.read_bytes()[LO:HI]
    n = len(d)
    marks = [o for o in range(0, n - REC, 4) if unit_at(d, o)]
    markset = set(marks)
    print(f"blob {n:,} B   marks {len(marks):,} ({100*len(marks)*REC/n:.1f}% of "
          f"the blob is inside unit-normal records)")

    # maximal runs of consecutive marks spaced REC apart
    runs = []
    i = 0
    while i < len(marks):
        j = i
        while j + 1 < len(marks) and marks[j + 1] - marks[j] == REC:
            j += 1
        if j > i:
            runs.append((marks[i], marks[j]))
        i = j + 1
    runs = [(a, b) for a, b in runs if (b - a) // REC + 1 >= 3]
    print(f"vertex arrays: {len(runs):,}")
    tot_v = sum((b - a) // REC + 1 for a, b in runs)
    print(f"total vertices: {tot_v:,}  ({tot_v*REC:,} B = "
          f"{100*tot_v*REC/n:.1f}% of the blob)")
    sizes = sorted(((b - a) // REC + 1 for a, b in runs), reverse=True)
    print(f"array sizes: max {sizes[0]:,} median {sizes[len(sizes)//2]:,} "
          f"min {sizes[-1]:,}")

    # what lies between the arrays?
    gaps = []
    for k in range(len(runs) - 1):
        ga, gb = runs[k][1] + REC, runs[k + 1][0]
        if gb > ga:
            gaps.append((ga, gb))
    print(f"\n{len(gaps)} inter-array regions; "
          f"total {sum(b-a for a,b in gaps):,} B")
    import collections
    h = collections.Counter((b - a) // 2 for a, b in gaps)
    print("  size/2 histogram (top 10):", h.most_common(10))
    print("  smallest 12:")
    for a, b in sorted(gaps, key=lambda t: t[1] - t[0])[:12]:
        print(f"    0x{a:07x}  {b-a:>8,} B   head {d[a:a+24].hex(' ')}")

    return runs, gaps


if __name__ == "__main__":
    main()
