"""
Dump the scene/object directory of every map archive.

Each map's first "gap" blob begins with a record table:
    u16 type ; u16 group ; u32 A ; u32 B ; f32 scale ; u32 fileOffset ; u32 size
    u8 nameLen ; char name[nameLen]       (22 bytes fixed + name)
`fileOffset`/`size` are absolute positions in the original .rpk; for the records
that point at top-level resources the size equals (entry size + 8), and the
chain closes exactly on EOF.  Everything else points inside untagged
sub-archives (scene instance data).

Usage: python tools/map_scene.py [--csv out.csv]
"""
import collections
import csv
import glob
import os
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from gap_walk import autofit  # noqa: E402

TYPE_HINT = {
    1: "level/root", 2: "track-surface mesh", 3: "container/group",
    4: "track-piece instance", 7: "group", 8: "object instance",
    9: "reflection/mirror set", 11: "light set", 30: "collision?",
    64: "texture?", 67: "texture?", 99: "texture",
}


def main():
    rows = []
    per_map = {}
    for g in sorted(glob.glob("extracted_rpak/maps/*/gap*.bin")):
        d = open(g, "rb").read()
        start, fixed, recs, start_off = None, None, None, None
        best = None
        for f in range(16, 33):
            for s in range(0, 6):
                from gap_walk import walk
                r, _ = walk(d, s, f)
                if best is None or len(r) > len(best[2]):
                    best = (s, f, r)
        s, f, recs = best
        if len(recs) < 4:
            continue
        m = g.replace("\\", "/").split("/")[2]
        per_map[m] = []
        for r in recs:
            raw = d[r[0]:r[0] + f]
            typ, grp = struct.unpack_from("<HH", raw, 0)
            a, b = struct.unpack_from("<II", raw, 4)
            scale, = struct.unpack_from("<f", raw, 10)
            off, size = struct.unpack_from("<II", raw, 14)
            per_map[m].append((typ, grp, a, b, off, size, r[8]))
            rows.append([m, typ, grp, a, b, off, size, r[8]])

    tot = sum(len(v) for v in per_map.values())
    print(f"{len(per_map)} maps, {tot} scene records\n")
    print(f"{'map':<14} {'recs':>5} {'top-types'}")
    alltypes = collections.Counter()
    for m, v in sorted(per_map.items(), key=lambda kv: -len(kv[1])):
        tc = collections.Counter(t for t, *_ in v)
        alltypes.update(tc)
        print(f"{m:<14} {len(v):>5} {dict(tc.most_common(6))}")

    print(f"\n=== type histogram over the whole game ===")
    for t, c in alltypes.most_common():
        print(f"   type {t:>3} : {c:>6}   {TYPE_HINT.get(t, '')}")

    names = collections.Counter(r[7] for r in rows)
    print(f"\n=== {len(names)} distinct object names; most reused ===")
    for n, c in names.most_common(30):
        print(f"   {c:>6}  {n}")

    if "--csv" in sys.argv:
        out = sys.argv[sys.argv.index("--csv") + 1]
        with open(out, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["map", "type", "group", "A", "B", "offset", "size", "name"])
            w.writerows(rows)
        print(f"\nwrote {out} ({len(rows)} rows)")


if __name__ == "__main__":
    main()
