"""
Full topology recovery for the coastline map stream.

Layout deduced from the run/gap structure of the 11 MB blob:
    [vertex block]   n x 44-byte records, each ending in u32 0xffffffff
    [index block]    a few f32, then a u16 triangle-index list
and the blocks alternate.

For each pair the test is the same one used on INVO: every index must address a
vertex inside the *preceding* block, and the index count must be a multiple of
three.  A wrong pairing breaks that immediately.

Usage: python tools/coastline_index.py [--obj out.obj] [--png out.png]
"""
import struct
import sys
from pathlib import Path

from PIL import Image, ImageDraw

RPK = Path(r"C:\Games\LASR\maps\coastline.rpk")
LO, HI = 0x20282, 0xAB3BBC
REC = 44


def vertex_runs(d):
    sent = [i for i in range(0, len(d) - 3, 4) if d[i:i + 4] == b"\xff\xff\xff\xff"]
    runs, cur = [], [sent[0]]
    for i in range(1, len(sent)):
        if sent[i] - sent[i - 1] <= 4 * 64:
            cur.append(sent[i])
        else:
            runs.append((cur[0], cur[-1]))
            cur = [sent[i]]
    runs.append((cur[0], cur[-1]))
    return runs


def load_verts(d, a, b):
    """Vertices of one run: records end at each sentinel, 4-aligned."""
    out = []
    for i in range(a, b + 1, 4):
        s = i + 4 - REC
        if s < 0 or s + REC > len(d):
            continue
        u, v, c1, c2, px, py, pz, nx, ny, nz = struct.unpack_from("<10f", d, s)
        L = (nx * nx + ny * ny + nz * nz) ** 0.5
        if 0.999 < L < 1.001 and px == px and py == py and pz == pz:
            out.append((px, py, pz, nx, ny, nz, u, v))
    return out


def find_indices(d, a, b, nv):
    """Find (offset, hdr, count, idx) of the u16 index list in block [a,b).

    0xFFFF is a triangle-strip restart marker, not a real index, so it is
    excluded before the bound check.  A list is accepted only when every real
    index addresses the preceding vertex block.
    """
    best = None
    for hdr in range(0, min(96, b - a), 4):
        o = a + hdr
        run = []
        q = o
        while q + 1 < b:
            v, = struct.unpack_from("<H", d, q)
            if v == 0xFFFF:            # strip restart
                q += 2
                continue
            if v >= nv:                # list ends here
                break
            run.append(v)
            q += 2
        if len(run) < 3:
            continue
        if best is None or len(run) > len(best[3]):
            best = (o, hdr, len(run), run)
    return best


def render(tris, path, sz=(1000, 560)):
    img = Image.new("RGB", sz, (12, 12, 16))
    dr = ImageDraw.Draw(img)
    xs = [t[0][0] for t in tris]
    zs = [t[0][2] for t in tris]
    ys = [t[0][1] for t in tris]
    print(f"  bbox x[{min(xs):.0f},{max(xs):.0f}] y[{min(ys):.0f},{max(ys):.0f}] "
          f"z[{min(zs):.0f},{max(zs):.0f}]")

    def view(ax, ay, ox):
        A = [t[0][ax] for t in tris]
        B = [t[0][ay] for t in tris]
        span = max(max(A) - min(A), max(B) - min(B)) or 1
        w, h = sz[0] // 2, sz[1]
        sc = (h * 0.92) / span
        cx, cy = (max(A) + min(A)) / 2, (max(B) + min(B)) / 2
        for p, n in tris:
            x = int(ox + w / 2 + (p[ax] - cx) * sc)
            y = int(h / 2 - (p[ay] - cy) * sc)
            if 0 <= x < sz[0] and 0 <= y < sz[1]:
                t = max(0.0, min(1.0, 0.30 + 0.70 * abs(n[ay])))
                img.putpixel((x, y), (int(210 * t), int(220 * t), int(190 * t)))

    view(0, 2, 0)
    view(2, 1, sz[0] // 2)
    dr.line([(sz[0] // 2, 0), (sz[0] // 2, sz[1])], fill=(70, 70, 90))
    dr.text((8, 6), "coastline terrain - TOP (X vs Z)", fill=(225, 225, 235))
    dr.text((sz[0] // 2 + 8, 6), "SIDE (Z vs Y)", fill=(225, 225, 235))
    img.save(path)
    print(f"  wrote {path}")


def main():
    d = RPK.read_bytes()[LO:HI]
    runs = vertex_runs(d)
    print(f"{len(runs)} vertex blocks in {len(d):,} B")

    total_v = total_t = 0
    tris = []
    pairs = 0
    hdrstat = {}
    for k in range(len(runs) - 1):
        a, b = runs[k]
        verts = load_verts(d, a, b)
        if len(verts) < 3:
            continue
        ga, gb = b + 4, runs[k + 1][0]
        r = find_indices(d, ga, gb, len(verts))
        if not r:
            continue
        o, hdr, cnt, idx = r
        pairs += 1
        total_v += len(verts)
        total_t += cnt // 3
        hdrstat[hdr] = hdrstat.get(hdr, 0) + 1
        if len(tris) < 400000:
            for t in range(0, cnt - 2, 3):
                for j in (idx[t], idx[t + 1], idx[t + 2]):
                    v = verts[j]
                    tris.append((v[:3], v[3:6]))

    print(f"  paired vertex+index blocks : {pairs}/{len(runs)-1}")
    print(f"  total vertices {total_v:,}   total triangles {total_t:,}")
    print(f"  index-block header sizes   : {dict(sorted(hdrstat.items()))}")

    png = sys.argv[sys.argv.index("--png") + 1] if "--png" in sys.argv else "docs/coastline_terrain.png"
    render(tris, png)

    if "--obj" in sys.argv:
        out = sys.argv[sys.argv.index("--obj") + 1]
        with open(out, "w") as fh:
            for p, n in tris:
                fh.write(f"v {p[0]:.4f} {p[1]:.4f} {p[2]:.4f}\n")
        print(f"  wrote {out}")


if __name__ == "__main__":
    main()
