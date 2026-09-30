"""
Extract the coastline vertex stream and render it for visual proof.

Record (44 bytes, proven):
    f32 u ; f32 v ; f32 c1 ; f32 c2 ; f32 px,py,pz ; f32 nx,ny,nz ; u32 0xffffffff
The trailing u32 is 0xffffffff in all 48,719 records and is used as the record
delimiter.  48,428 of them carry an exactly unit-length normal, which is the
invariant that pins the field offsets.

Usage: python tools/coastline_mesh.py [--obj out.obj] [--png out.png]
"""
import struct
import sys
from pathlib import Path

from PIL import Image, ImageDraw

RPK = Path(r"C:\Games\LASR\maps\coastline.rpk")
LO, HI = 0x20282, 0xAB3BBC
REC = 44
SENT = b"\xff\xff\xff\xff"


def records(d):
    """Walk sentinel-delimited records; require a unit normal to accept one."""
    out = []
    o = 0
    n = len(d)
    while True:
        i = d.find(SENT, o)
        if i < 0 or i + 4 > n:
            break
        o = i + 1
        if i % 4:                      # records are 4-aligned
            continue
        s = i + 4 - REC
        if s >= 0:
            u, v, c1, c2, px, py, pz, nx, ny, nz = struct.unpack_from("<10f", d, s)
            L = (nx * nx + ny * ny + nz * nz) ** 0.5
            if 0.999 < L < 1.001:
                out.append((s, u, v, c1, c2, px, py, pz, nx, ny, nz))
    return out


def render(pts, path, sz=(1000, 560)):
    img = Image.new("RGB", sz, (12, 12, 16))
    dr = ImageDraw.Draw(img)
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    zs = [p[2] for p in pts]
    print(f"  bbox x [{min(xs):.1f}, {max(xs):.1f}] "
          f"y [{min(ys):.1f}, {max(ys):.1f}] z [{min(zs):.1f}, {max(zs):.1f}]")

    def view(ax, ay, ox):
        """ax, ay: which world axes to project."""
        a = [p[ax] for p in pts]
        b = [p[ay] for p in pts]
        zz = [p[2] for p in pts]
        span = max(max(a) - min(a), max(b) - min(b)) or 1
        w, h = sz[0] // 2, sz[1]
        sc = (h * 0.92) / span
        cx = (max(a) + min(a)) / 2
        cy = (max(b) + min(b)) / 2
        for i, p in enumerate(pts):
            x = int(ox + w / 2 + (p[ax] - cx) * sc)
            y = int(h / 2 - (p[ay] - cy) * sc)
            if 0 <= x < sz[0] and 0 <= y < sz[1]:
                # shade by the normal, so a coherent surface reads as a gradient
                t = max(0.0, min(1.0, 0.45 + 0.55 * abs(p[5])))
                col = (int(200 * t + 30), int(210 * t + 40), int(255 * t + 20))
                img.putpixel((x, y), col)

    view(0, 2, 0)          # top view: X vs Z
    view(2, 1, sz[0] // 2)  # side view: Z vs Y
    dr.line([(sz[0] // 2, 0), (sz[0] // 2, sz[1])], fill=(70, 70, 90))
    dr.text((8, 6), f"coastline vertex stream - TOP (X vs Z)", fill=(220, 220, 230))
    dr.text((sz[0] // 2 + 8, 6), "SIDE (Z vs Y)", fill=(220, 220, 230))
    img.save(path)
    print(f"  wrote {path} {img.size}")


def main():
    z = RPK.read_bytes()
    raw = z[LO:HI]
    recs = records(raw)
    print(f"blob {len(raw):,} B  ->  {len(recs):,} valid vertex records "
          f"({len(recs)*REC:,} B of vertex data)")
    # r = (s, u, v, c1, c2, px, py, pz, nx, ny, nz)
    pts = [(r[5], r[6], r[7], r[8], r[9], r[10], r[1], r[2]) for r in recs]
    for idx, nm in ((1, "u"), (2, "v"), (3, "c1"), (4, "c2")):
        vals = [r[idx] for r in recs]
        lo, hi = min(vals), max(vals)
        print(f"  {nm:<3} range [{lo:.4f}, {hi:.4f}]  "
              f"distinct {len({round(x,4) for x in vals}):,}  "
              f"in [0,1] {sum(1 for x in vals if 0 <= x <= 1)*100//len(vals)}%")

    png = sys.argv[sys.argv.index("--png") + 1] if "--png" in sys.argv else "docs/coastline_points.png"
    render(pts, png)

    if "--obj" in sys.argv:
        out = sys.argv[sys.argv.index("--obj") + 1]
        with open(out, "w") as fh:
            fh.write("# coastline vertex stream (points, no topology recovered)\n")
            for p in pts:
                fh.write(f"v {p[0]:.4f} {p[1]:.4f} {p[2]:.4f}\n")
                fh.write(f"vn {p[3]:.4f} {p[4]:.4f} {p[5]:.4f}\n")
        print(f"  wrote {out} ({len(pts):,} verts)")


if __name__ == "__main__":
    main()
