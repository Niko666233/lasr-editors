"""
coastline stream -> OBJ, v2: pair every *valid* vertex array with *all* the
index lists that follow it.

Two corrections over v1:

1. v1 counted 149 vertex arrays but 75 of them contained 0-4 real vertices -
   they are fragments that merely happen to contain a 0xffffffff word.  Only
   arrays with >= 3 unit-normal records are real sub-meshes, so those fragments
   are dropped instead of being reported as "unpaired".
2. v1 took at most one index list per region.  A sub-mesh can hold several
   strips, so the region is scanned repeatedly: each accepted list is consumed
   and the scan resumes where it ended.

An index list is accepted only if it starts at 0, every value is < vertexCount
(0xffffffff-as-u16 = 0xFFFF is a strip restart and is skipped), its length is a
multiple of three, and it has at least three entries.

Usage: python tools/coastline_index2.py [--png out.png] [--obj out.obj]
"""
import struct
import sys
from pathlib import Path

from PIL import Image, ImageDraw

RPK = Path(r"C:\Games\LASR\maps\coastline.rpk")
LO, HI = 0x20282, 0xAB3BBC
REC = 44
RESTART = 0xFFFF


def vertex_arrays(d):
    """Colour-delimited candidate runs, then keep only real vertex arrays."""
    sent = [i for i in range(0, len(d) - 3, 4) if d[i:i + 4] == b"\xff\xff\xff\xff"]
    raw, cur = [], [sent[0]]
    for i in range(1, len(sent)):
        if sent[i] - sent[i - 1] <= 4 * 64:
            cur.append(sent[i])
        else:
            raw.append((cur[0], cur[-1]))
            cur = [sent[i]]
    raw.append((cur[0], cur[-1]))

    out = []
    for a, b in raw:
        vs = []
        for i in range(a, b + 1, 4):
            s = i + 4 - REC
            if s < 0 or s + REC > len(d):
                continue
            u, v, c1, c2, px, py, pz, nx, ny, nz = struct.unpack_from("<10f", d, s)
            if not (0.999 < nx * nx + ny * ny + nz * nz < 1.001):
                continue
            if px != px or py != py or pz != pz:
                continue
            vs.append((px, py, pz, nx, ny, nz, u, v))
        if len(vs) >= 3:
            out.append((a, b, vs))
    return out


def lists_in(d, a, b, nv):
    """Every valid index list in [a,b), in order.

    Criteria are deliberately loose about where a list may start (v1 style) but
    strict about the bound check, which is the only thing that actually proves
    the pairing: every index must address the preceding vertex array.
    """
    out = []
    p = a
    first = True
    while p + 6 <= b:
        best = None
        for hdr in range(0, (96 if first else 24) + 1, 2):
            o = p + hdr
            if o + 6 > b:
                break
            run, q = [], o
            while q + 1 < b:
                v, = struct.unpack_from("<H", d, q)
                if v == RESTART:
                    q += 2
                    continue
                if v >= nv:
                    break
                run.append(v)
                q += 2
            if len(run) < 3:
                continue
            if best is None or len(run) > len(best[2]):
                best = (o, hdr, run, q)
        if best is None:
            break
        out.append(best)
        p = best[3] + 2
        first = False
    return out


def render(tris, path, sz=(1000, 560)):
    img = Image.new("RGB", sz, (12, 12, 16))
    dr = ImageDraw.Draw(img)
    xs = [t[0][0] for t in tris]
    ys = [t[0][1] for t in tris]
    zs = [t[0][2] for t in tris]
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
                img.putpixel((x, y), (int(215 * t), int(225 * t), int(200 * t)))

    view(0, 2, 0)
    view(2, 1, sz[0] // 2)
    dr.line([(sz[0] // 2, 0), (sz[0] // 2, sz[1])], fill=(70, 70, 90))
    dr.text((8, 6), "coastline terrain v2 - TOP (X vs Z)", fill=(225, 225, 235))
    dr.text((sz[0] // 2 + 8, 6), "SIDE (Z vs Y)", fill=(225, 225, 235))
    img.save(path)
    print(f"  wrote {path}")


def main():
    d = RPK.read_bytes()[LO:HI]
    arrays = vertex_arrays(d)
    print(f"real vertex arrays: {len(arrays)}  "
          f"(vertices {sum(len(v) for _, _, v in arrays):,})")

    paired = unpaired = 0
    total_v = total_t = 0
    nlists = 0
    tris = []
    for k, (a, b, verts) in enumerate(arrays):
        nxt = arrays[k + 1][0] if k + 1 < len(arrays) else len(d)
        ls = lists_in(d, b + 4, nxt, len(verts))
        if not ls:
            unpaired += 1
            continue
        paired += 1
        total_v += len(verts)
        nlists += len(ls)
        for _, _, run, _ in ls:
            total_t += len(run) // 3
            if len(tris) < 2000000:
                for t in range(0, len(run) - 2, 3):
                    for j in (run[t], run[t + 1], run[t + 2]):
                        v = verts[j]
                        tris.append((v[:3], v[3:6]))

    print(f"  paired            : {paired}/{len(arrays)}")
    print(f"  unpaired          : {unpaired}  (fragments with no valid list)")
    print(f"  index lists total : {nlists}  (avg "
          f"{nlists/max(1,paired):.1f} per sub-mesh)")
    print(f"  vertices          : {total_v:,}")
    print(f"  triangles         : {total_t:,}")

    png = sys.argv[sys.argv.index("--png") + 1] if "--png" in sys.argv \
        else "docs/coastline_terrain_v2.png"
    render(tris, png)

    if "--obj" in sys.argv:
        out = sys.argv[sys.argv.index("--obj") + 1]
        with open(out, "w") as fh:
            for p, n in tris:
                fh.write(f"v {p[0]:.4f} {p[1]:.4f} {p[2]:.4f}\n")
        print(f"  wrote {out}")


if __name__ == "__main__":
    main()
