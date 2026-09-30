"""
Plot every recovered map object top-down, one panel per map.

A correct extraction of `gametype`/`params` should produce sane level layouts:
objects should cluster along roads and around buildings, not scatter randomly,
and the world bounds should match the terrain those maps use.

Usage: python tools/plot_objects.py [csv] [png]
"""
import csv
import sys
from collections import defaultdict, Counter
from pathlib import Path

from PIL import Image, ImageDraw

CSV = sys.argv[1] if len(sys.argv) > 1 else "docs/map_objects.csv"
PNG = sys.argv[2] if len(sys.argv) > 2 else "docs/map_objects.png"

PALETTE = 12
COLS = (0xE8, 0x6A, 0x5C, 0xE8, 0xC3, 0x4A, 0x7E, 0xC8, 0x6E, 0x5C, 0xA8, 0xD8,
        0x8A, 0x6E, 0xC8, 0xD8, 0x8A, 0x5C, 0x6E, 0xC8, 0xC8, 0x4A, 0x9E, 0xE8,
        0xE8, 0x9A, 0x4A, 0x4A, 0xB8, 0xE8, 0xC8, 0x4A, 0xE8, 0x5C, 0x5C, 0x8A)


def main():
    per = defaultdict(list)
    gset = Counter()
    with open(CSV, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if not row["px"]:
                continue
            try:
                x, y, z = float(row["px"]), float(row["py"]), float(row["pz"])
            except ValueError:
                continue
            per[row["map"]].append((x, z, row["gametype"]))
            gset[row["gametype"]] += 1

    maps = sorted(per, key=lambda m: -len(per[m]))
    print(f"{len(maps)} maps, {sum(len(v) for v in per.values()):,} objects, "
          f"{len(gset)} distinct gametypes")
    top = [g for g, _ in gset.most_common(PALETTE)]
    colour = {g: COLS[i * 3:i * 3 + 3] for i, g in enumerate(top)}

    PW, PH = 340, 300
    cols = 5
    rows = (len(maps) + cols - 1) // cols
    img = Image.new("RGB", (PW * cols, PH * rows), (14, 14, 18))
    dr = ImageDraw.Draw(img)

    for i, m in enumerate(maps):
        pts = per[m]
        ox, oy = (i % cols) * PW, (i // cols) * PH
        xs = [p[0] for p in pts]
        zs = [p[1] for p in pts]
        span = max(max(xs) - min(xs), max(zs) - min(zs), 1)
        sc = (min(PW, PH) - 34) / span
        cx, cz = (max(xs) + min(xs)) / 2, (max(zs) + min(zs)) / 2
        for x, z, g in pts:
            px = int(ox + PW / 2 + (x - cx) * sc)
            py = int(oy + PH / 2 + (z - cz) * sc)
            if ox < px < ox + PW - 1 and oy < py < oy + PH - 1:
                c = colour.get(g, (110, 110, 120))
                img.putpixel((px, py), c)
                if len(pts) < 900:
                    dr.point((px + 1, py), fill=c)
        dr.rectangle([ox, oy, ox + PW - 1, oy + PH - 1], outline=(48, 48, 58))
        dr.text((ox + 6, oy + 4), f"{m}   {len(pts):,} obj", fill=(230, 230, 240))
        dr.text((ox + 6, oy + 16), f"x[{min(xs):.0f},{max(xs):.0f}] "
                                   f"z[{min(zs):.0f},{max(zs):.0f}]",
                fill=(150, 150, 165))

    img.save(PNG)
    print(f"wrote {PNG} {img.size}")
    print("legend (top gametypes):")
    for g in top:
        print(f"   {g}  {gset[g]:>6}  rgb{colour[g]}")


if __name__ == "__main__":
    main()
