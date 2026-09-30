"""
INVO v4 mesh -> OBJ, plus a tiny software renderer for visual verification.

Verified vertex layout (60/60 meshes of Takura_Tornado_2002 pass the
"all indices < vertexCount and size == 16 + count*stride" consistency check):

  block kind=4   u32 kind, u32 size, u32 vertexCount, u32 flags
                 then vertexCount vertices, stride = (size-16)//vertexCount
                 stride in {36, 60, 64} bytes
      +0   float3 position
      +12  float3 normal
      +24  u32    packed colour (stride 36 uses +24..+27; 60/64 too)
      ...  float3 tangent / float3 bitangent on the wide strides
      -8   float2 uv        (always the LAST 8 bytes of the vertex)

  block kind=5   u32 kind, u32 size, u32 indexCount, u32 flags
                 then indexCount u16 triangle-list indices

Usage:
  python tools/invo_obj.py FILE.iscx OUT.obj
  python tools/invo_obj.py FILE.iscx OUT.png --render
"""
import struct
import sys
from pathlib import Path

TRI = {36: (0, 12, 28, 12, 12, 8), 60: (0, 12, 24, 12, 12, 8),
       64: (0, 12, 24, 12, 12, 8), 68: (0, 12, 24, 12, 12, 8)}
# position @0, normal @+12, uv = last 8 bytes holds for every stride seen so far
# (36, 60, 64, 68).  Any 4-aligned stride in [32,128] is accepted; the render
# step is what validates the layout.
#
# 紧凑布局（无 normal）：24 = pos(12)+色(4)+uv(8)，28 = pos(12)+中间 8B+uv(8)。
# 见 maps/boulevard/{far,mirror,mirror_black}.iscx（实测 pos/uv 都合理）。


def layout(stride):
    """→ (has_normal, colour_offset or None)。uv 恒为最后 8 字节。"""
    if stride >= 36:
        return True, 24
    return False, 12          # 24/28：紧跟位置的 4 字节是打包色


def stride_ok(s):
    return s % 4 == 0 and 24 <= s <= 128


def descriptors(d):
    if d[:4] != b"INVO":
        raise ValueError("not INVO")
    ver, n = struct.unpack_from("<2I", d, 4)
    pr = [struct.unpack_from("<2I", d, 0x0C + 8 * i) for i in range(n)]
    offs = sorted({o for _, o in pr if 0 < o < len(d)} | {len(d)})
    return [(k, o, next((b for b in offs if b > o), len(d))) for k, o in pr]


def read_submeshes(d):
    regs = descriptors(d)
    out = []
    for i, (kind, a, b) in enumerate(regs):
        if kind != 4:
            continue
        blk = d[a:b]
        k, size, nv, flags = struct.unpack_from("<4I", blk, 0)
        stride = (size - 16) // nv if nv else 0
        if not stride_ok(stride) or nv == 0 or 16 + nv * stride > len(blk):
            out.append({"kind": kind, "off": a, "ok": False,
                        "why": f"nv={nv} stride={stride} size={size}"})
            continue
        has_n, col_off = layout(stride)
        verts = []
        for v in range(nv):
            o = 16 + v * stride
            px, py, pz = struct.unpack_from("<3f", blk, o)
            if has_n:
                nx, ny, nz = struct.unpack_from("<3f", blk, o + 12)
            else:
                nx = ny = nz = None
            u, w = struct.unpack_from("<2f", blk, o + stride - 8)
            col = struct.unpack_from("<I", blk, o + col_off)[0]
            verts.append((px, py, pz, nx, ny, nz, u, w, col))
        # the index buffer is the next kind=5 descriptor
        idx = []
        for kind2, a2, b2 in regs[i + 1:]:
            if kind2 != 5:
                continue
            blk2 = d[a2:b2]
            _, size2, ni, _ = struct.unpack_from("<4I", blk2, 0)
            if 12 + ni * 2 <= len(blk2):
                idx = list(struct.unpack_from("<%dH" % ni, blk2, 12))
            break
        out.append({"kind": kind, "off": a, "ok": True, "stride": stride,
                    "verts": verts, "idx": idx, "flags": flags})
    return out


def write_obj(subs, path):
    lines = ["# L.A. Street Racing INVO v4 mesh, extracted by tools/invo_obj.py"]
    base = 1
    for si, s in enumerate(subs):
        if not s.get("ok"):
            continue
        has_n = s["verts"] and s["verts"][0][3] is not None
        lines.append(f"o submesh_{si}_stride{s['stride']} "
                     f"verts{len(s['verts'])} tris{len(s['idx'])//3}"
                     + ("" if has_n else " (无法线)"))
        for (px, py, pz, nx, ny, nz, u, w, c) in s["verts"]:
            lines.append(f"v {px:.6f} {py:.6f} {pz:.6f}")
        if has_n:
            for (px, py, pz, nx, ny, nz, u, w, c) in s["verts"]:
                lines.append(f"vn {nx:.6f} {ny:.6f} {nz:.6f}")
        for (px, py, pz, nx, ny, nz, u, w, c) in s["verts"]:
            lines.append(f"vt {u:.6f} {w:.6f}")
        n = len(s["verts"])
        idx = s["idx"]
        for t in range(0, len(idx) - 2, 3):
            a, b, c = idx[t] + base, idx[t + 1] + base, idx[t + 2] + base
            if has_n:
                lines.append(f"f {a}/{a}/{a} {b}/{b}/{b} {c}/{c}/{c}")
            else:
                lines.append(f"f {a}/{a} {b}/{b} {c}/{c}")
        base += n
    Path(path).write_text("\n".join(lines) + "\n")


def render(subs, path, W=700, H=520):
    from PIL import Image
    tris = []
    for s in subs:
        if not s.get("ok"):
            continue
        V, I = s["verts"], s["idx"]
        for t in range(0, len(I) - 2, 3):
            tris.append((V[I[t]], V[I[t + 1]], V[I[t + 2]]))
    if not tris:
        raise SystemExit("no triangles")
    xs = [v[0] for tri in tris for v in tri]
    ys = [v[1] for tri in tris for v in tri]
    zs = [v[2] for tri in tris for v in tri]
    print(f"  triangles={len(tris)}  bbox x[{min(xs):.2f},{max(xs):.2f}] "
          f"y[{min(ys):.2f},{max(ys):.2f}] z[{min(zs):.2f},{max(zs):.2f}]")

    img = Image.new("RGB", (W, H), (24, 26, 32))
    px = img.load()
    zbuf = [[1e30] * W for _ in range(H)]

    views = [(0, 1, 2, "X-Y"), (2, 1, 0, "Z-Y")]
    for k, (ai, bi, ci, label) in enumerate(views):
        ox = k * (W // 2)
        w2, h2 = W // 2, H
        ax = [v[ai] for tri in tris for v in tri]
        ay = [v[bi] for tri in tris for v in tri]
        az = [v[ci] for tri in tris for v in tri]
        mnx, mxx = min(ax), max(ax)
        mny, mxy = min(ay), max(ay)
        sc = min((w2 - 30) / max(mxx - mnx, 1e-6), (h2 - 30) / max(mxy - mny, 1e-6))
        for tri in tris:
            p = []
            for v in tri:
                sx = ox + 15 + (v[ai] - mnx) * sc
                sy = H - 15 - (v[bi] - mny) * sc
                p.append((sx, sy, v[ci], v[3], v[4], v[5]))
            x0 = max(0, int(min(q[0] for q in p)))
            x1 = min(W - 1, int(max(q[0] for q in p)) + 1)
            y0 = max(0, int(min(q[1] for q in p)))
            y1 = min(H - 1, int(max(q[1] for q in p)) + 1)
            (ax0, ay0, az0, nx0, ny0, nz0) = p[0]
            (ax1, ay1, az1, _, _, _) = p[1]
            (ax2, ay2, az2, _, _, _) = p[2]
            d = (ay1 - ay2) * (ax0 - ax2) + (ax2 - ax1) * (ay0 - ay2)
            if abs(d) < 1e-9:
                continue
            # analytic face normal for flat shading
            q0 = tri[0]
            q1 = tri[1]
            q2 = tri[2]
            e1 = (q1[0] - q0[0], q1[1] - q0[1], q1[2] - q0[2])
            e2 = (q2[0] - q0[0], q2[1] - q0[1], q2[2] - q0[2])
            fn = (e1[1] * e2[2] - e1[2] * e2[1],
                  e1[2] * e2[0] - e1[0] * e2[2],
                  e1[0] * e2[1] - e1[1] * e2[0])
            fl = (fn[0] ** 2 + fn[1] ** 2 + fn[2] ** 2) ** 0.5 or 1.0
            fn = (fn[0] / fl, fn[1] / fl, fn[2] / fl)
            lit = abs(fn[0] * 0.4 + fn[1] * 0.8 + fn[2] * 0.45)
            shade = int(40 + 195 * min(1.0, lit))
            for yy in range(y0, y1 + 1):
                for xx in range(x0, x1 + 1):
                    w0 = ((ay1 - ay2) * (xx - ax2) + (ax2 - ax1) * (yy - ay2)) / d
                    w1 = ((ay2 - ay0) * (xx - ax2) + (ax0 - ax2) * (yy - ay2)) / d
                    w2_ = 1 - w0 - w1
                    if w0 < -1e-6 or w1 < -1e-6 or w2_ < -1e-6:
                        continue
                    z = w0 * az0 + w1 * az1 + w2_ * az2
                    if z < zbuf[yy][xx]:
                        zbuf[yy][xx] = z
                        px[xx, yy] = (shade, shade, min(255, shade + 18))
    img.save(path)
    print(f"  rendered -> {path}")


def main():
    src = Path(sys.argv[1])
    dst = Path(sys.argv[2])
    d = src.read_bytes()
    subs = read_submeshes(d)
    print(f"=== {src.name}: {len(subs)} kind=4 block(s)")
    for i, s in enumerate(subs):
        if s.get("ok"):
            print(f"   [{i}] stride={s['stride']} verts={len(s['verts'])} "
                  f"idx={len(s['idx'])} tris={len(s['idx'])//3}")
        else:
            print(f"   [{i}] skipped: {s.get('why')}")
    if dst.suffix.lower() == ".obj":
        write_obj(subs, dst)
        print(f"  wrote {dst}")
    else:
        render(subs, dst)
        write_obj(subs, dst.with_suffix(".obj"))
        print(f"  wrote {dst.with_suffix('.obj')}")


if __name__ == "__main__":
    main()
