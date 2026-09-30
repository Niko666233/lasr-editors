"""
Field-level diff of the recovered map "scene table".

Autofit (gap_walk.py) proved the record layout:
    22 bytes fixed  +  u8 nameLen  +  name[nameLen]     (nameLen includes NUL)
and recovered 61 real object names from maps/boulevard.  This tool prints the
22 fixed bytes of every record so the varying columns can be identified.
"""
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from gap_walk import walk, autofit  # noqa: E402


def main():
    p = Path(sys.argv[1])
    d = p.read_bytes()
    start, fixed, recs, end = autofit(d)
    print(f"{p.name}: start={start} fixed={fixed}  {len(recs)} records, "
          f"ends at {end:#x}\n")

    print("  #   raw 22 bytes                                                       name")
    for i, r in enumerate(recs):
        off = r[0]
        raw = d[off:off + fixed]
        print(f"  {i:3d} {raw.hex(' ')}  {r[8]}")

    print("\n=== column variance across the whole table ===")
    for col in range(fixed):
        vals = [d[r[0] + col] for r in recs]
        unch = len(set(vals)) == 1
        print(f"  +{col:2d}  {'CONST' if unch else 'varies':6s}  "
              f"{sorted(set(vals))[:6]}{' ...' if len(set(vals)) > 6 else ''}")

    print("\n=== per-offset readout of record 0 ===")
    raw = d[recs[0][0]:recs[0][0] + fixed]
    for o in range(fixed - 3):
        u32, = struct.unpack_from("<I", raw, o)
        f32, = struct.unpack_from("<f", raw, o)
        print(f"  +{o:2d}  u32 {u32:<12}  f32 {f32:<16.6g}")


if __name__ == "__main__":
    main()
