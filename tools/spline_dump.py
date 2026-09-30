"""Export every AI route spline (.spl2) into JSON for the remake.

.spl2 is plain text: one line per route SEGMENT, TAB-separated, CRLF terminated.
Track-route lines have 9 columns; camera splines use a 10-column layout.

    [0] x y z            start point of the segment
    [1] x y z            tangent at the start (magnitude ~= this segment's length,
                         direction shared with the neighbouring segment's tangent
                         scaled by ITS length - i.e. Catmull-Rom style)
    [2] x y z            end point  (== next line's [0], verified exact)
    [3] x y z            tangent at the end
    [4] wl wr wl' wr'    left/right half-width at start, then at end
                         (continuous across segments: [2],[3] == next [0],[1])
    [5] v0 v1            per-endpoint scalar, chained like [4]
    [6] 0x...            flags (hills_fast uses 0x0 / 0x20000000 / 0x30000000)
    [7] int              unused in the shipped data (all 0)
    [8] 0 0 0 0          extra quadruple (all 0 in the shipped data)

Used by java.util.resource.GroundRef natives:
    loadSpline(int id, String file) -> id
    getSplineLength / getSplinePos(id,t,off) / getSplineDir(id,t) / getSplineVal
    / getSplinePerp / getSplineDist / getSplineWidth(id,t,side) / getSplineRake
    / getNearestSpline(pos[,from,to])

    python tools/spline_dump.py --dump
    python tools/spline_dump.py --map hills
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GAME = Path("C:/Games/LASR")


def parse(path):
    """Parse one .spl2.

    Column layouts differ between track routes and camera splines (and a few
    maps put the hex flag elsewhere), so classify by CONTENT rather than index:
    a column whose tokens start with '0x' is a flag column, everything else is a
    numeric vector.  Track routes then come out as
    [p0, t0, p1, t1, width4, v2, flag, int, extra4].
    """
    raw = path.read_bytes().replace(b"\r\n", b"\n").decode("latin1")
    segs = []
    for ln in raw.split("\n"):
        if not ln.strip():
            continue
        cols = [c for c in ln.split("\t")]
        nums, flags, ints = [], [], []
        for c in cols:
            toks = c.split()
            if not toks:
                continue
            if any(t.startswith("0x") for t in toks):
                flags.append([int(t, 16) if t.startswith("0x") else t for t in toks])
            elif all(t.lstrip("+-").replace(".", "").isdigit() for t in toks):
                nums.append([float(t) for t in toks])
            else:
                try:
                    nums.append([float(t) for t in toks])
                except ValueError:
                    ints.append([int(t) for t in toks])
        seg = {"vecs": nums, "flags": flags, "ints": ints}
        if len(nums) >= 4:
            seg.update(p0=nums[0], t0=nums[1], p1=nums[2], t1=nums[3])
        if len(nums) >= 5:
            seg["w"] = nums[4]
        if len(nums) >= 6:
            seg["v"] = nums[5]
        if len(nums) >= 7:
            seg["extra"] = nums[6]
        segs.append(seg)
    return segs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", action="store_true")
    ap.add_argument("--map")
    a = ap.parse_args()
    files = sorted(GAME.glob("maps/*/*.spl2")) + sorted(GAME.glob("frontend/**/*.spl2"))
    if a.map:
        files = [f for f in files if a.map in str(f)]
    result = {}
    for f in files:
        try:
            segs = parse(f)
        except Exception as e:                                  # noqa: BLE001
            print(f"  !! {f}: {e}")
            continue
        key = str(f.relative_to(GAME)).replace("\\", "/")
        result[key] = segs
    print(f"spl2 文件 {len(result)} 个")
    tot = 0
    for k, v in sorted(result.items()):
        tot += len(v)
        flags = sorted({f for s in v for g in s["flags"] for f in g if isinstance(f, int)})
        print(f"  {k:<45} {len(v):>4} 段  向量列{len(v[0]['vecs']) if v else 0}  标志位 {[hex(x) for x in flags[:6]]}")
    print(f"合计 {tot} 段")
    if a.dump:
        p = ROOT / "out_routes.json"
        p.write_text(json.dumps(result, separators=(",", ":")))
        print(f"wrote {p.name} ({p.stat().st_size:,} B)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
