"""把 OBJ + `.mtl`（tools/rpak_assets.py --mtl 产物）渲染成带贴图的 PNG。

用途：验证 `docs/53` 解出的 **网格 → 贴图** 绑定是真的（UV + 图集对得上），
不是"名字看起来对"。纯 PIL：逐三角面用仿射变换把贴图糊上去（画家算法，按深度排序）。

    python tools/preview_textured.py assets/meshes/maps/boulevard/track_trees.obj \
                                    -o preview_tmp/track_trees_tex.png --view top --size 900
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent


def load_obj(p: Path):
    verts, uvs, faces, cur = [], [], [], None
    for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.startswith("v "):
            x, y, z = (float(t) for t in line.split()[1:4])
            verts.append((x, y, z))
        elif line.startswith("vt "):
            a, b = (float(t) for t in line.split()[1:3])
            uvs.append((a, b))
        elif line.startswith("f "):
            idx = []
            for tok in line.split()[1:]:
                parts = tok.split("/")
                vi = int(parts[0]) - 1
                ti = int(parts[1]) - 1 if len(parts) > 1 and parts[1] else None
                idx.append((vi, ti))
            if len(idx) >= 3:
                for k in range(1, len(idx) - 1):      # 三角扇
                    faces.append([idx[0], idx[k], idx[k + 1]])
        elif line.startswith("usemtl "):
            cur = line.split(None, 1)[1].strip()
    return verts, uvs, faces, cur


def mtl_map(p: Path):
    """读回 .mtl → {材质名: [贴图路径…]}（相对 mtl 所在目录）。"""
    out, cur = {}, None
    if not p.exists():
        return out
    for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
        t = line.split()
        if not t:
            continue
        if t[0] == "newmtl":
            cur = t[1]
            out[cur] = []
        elif t[0] in ("map_Kd", "map_Ka") and cur:
            out[cur].append((p.parent / " ".join(t[1:])).resolve())
    return out


def render(obj: Path, out: Path, view: str, size: int, bg=(24, 24, 28), use_tex=True,
           max_faces=0):
    verts, uvs, faces, mat = load_obj(obj)
    if max_faces and len(faces) > max_faces:
        faces = faces[::max(len(faces) // max_faces, 1)]
    if not verts or not faces:
        print(f"[tex] {obj} 无几何"); return 1
    mtls = mtl_map(obj.with_suffix(".mtl"))
    imgs = {}
    for texs in mtls.values():
        for i, tp in enumerate(texs):
            if tp.exists() and i < 3:
                try:
                    imgs[tp] = Image.open(tp).convert("RGBA")
                except Exception as e:                        # noqa: BLE001
                    print(f"[tex] 读不了贴图 {tp}: {e}")
    # 相机：正交投影（top=XZ / side=YZ / front=XY），深度轴取第三维
    ax = {"top": (0, 2, 1), "side": (1, 2, 0), "front": (0, 1, 2)}[view]
    lo = [min(v[i] for v in verts) for i in range(3)]
    hi = [max(v[i] for v in verts) for i in range(3)]
    spanx, spany = hi[ax[0]] - lo[ax[0]], hi[ax[1]] - lo[ax[1]]
    s = (size * 0.94) / max(spanx, spany, 1e-6)
    ox = size / 2 - (lo[ax[0]] + hi[ax[0]]) / 2 * s
    oy = size / 2 - (lo[ax[1]] + hi[ax[1]]) / 2 * s

    def proj(v):
        return (v[ax[0]] * s + ox, size - (v[ax[1]] * s + oy))

    canvas = Image.new("RGBA", (size, size), bg + (255,))
    order = sorted(range(len(faces)),
                   key=lambda i: sum(verts[v][ax[2]] for v, _ in faces[i]) / 3.0)
    d = ImageDraw.Draw(canvas)
    tex = (imgs or {}).get(next(iter(mtls.get(mat, [])), None)) if mtls else None
    if use_tex and tex is None:
        for tp in imgs:
            tex = imgs[tp]; break
    tw, th = (tex.size if tex else (0, 0))
    for fi in order:
        tri = faces[fi]
        pts = [proj(verts[v]) for v, _ in tri]
        if tex is not None and all(t is not None for _, t in tri):
            # 仿射：把贴图 UV(px) 映射到屏幕三角；只处理该三角的屏幕 bbox（否则每面都要
            # 变换整张画布，6 万面的地图网格跑不完 —— 见 docs/53 §3 的渲染验证）
            (x0, y0), (x1, y1), (x2, y2) = pts
            (u0, v0), (u1, v1), (u2, v2) = [uvs[t] for _, t in tri]
            U = [(u0 * tw, (1 - v0) * th), (u1 * tw, (1 - v1) * th), (u2 * tw, (1 - v2) * th)]
            det = ((U[1][0] - U[0][0]) * (U[2][1] - U[0][1])
                   - (U[2][0] - U[0][0]) * (U[1][1] - U[0][1]))
            if abs(det) < 1e-9:
                continue
            a = ((x1 - x0) * (U[2][1] - U[0][1]) - (x2 - x0) * (U[1][1] - U[0][1])) / det
            b = ((x2 - x0) * (U[1][0] - U[0][0]) - (x1 - x0) * (U[2][0] - U[0][0])) / det
            c = ((y1 - y0) * (U[2][1] - U[0][1]) - (y2 - y0) * (U[1][1] - U[0][1])) / det
            e = ((y2 - y0) * (U[1][0] - U[0][0]) - (y1 - y0) * (U[2][0] - U[0][0])) / det
            fx = x0 - a * U[0][0] - b * U[0][1]
            fy = y0 - c * U[0][0] - e * U[0][1]
            bx0 = max(int(min(x0, x1, x2)) - 1, 0)
            by0 = max(int(min(y0, y1, y2)) - 1, 0)
            bx1 = min(int(max(x0, x1, x2)) + 2, size)
            by1 = min(int(max(y0, y1, y2)) + 2, size)
            if bx1 <= bx0 or by1 <= by0:
                continue
            w, h = bx1 - bx0, by1 - by0
            patch = tex.transform((w, h), Image.AFFINE,
                                  (a, b, fx + a * bx0 + b * by0,
                                   c, e, fy + c * bx0 + e * by0), resample=Image.BILINEAR)
            mask = Image.new("L", (w, h), 0)
            ImageDraw.Draw(mask).polygon([(px - bx0, py - by0) for px, py in pts], fill=255)
            canvas.paste(patch, (bx0, by0), mask)
        else:
            d.polygon(pts, fill=(150, 150, 160, 255), outline=(60, 60, 70, 255))
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(out)
    print(f"[tex] {obj.name} → {out}  （{len(faces)} 三角，贴图 "
          f"{tex.size if tex else '无'}，材质 {mat}，视角 {view}）")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("obj")
    ap.add_argument("-o", "--out", default=None)
    ap.add_argument("--view", default="front", choices=["top", "side", "front"])
    ap.add_argument("--size", type=int, default=800)
    ap.add_argument("--flat", action="store_true", help="不上贴图，只看几何")
    ap.add_argument("--max-faces", type=int, default=0, help="只渲前 N 个三角（0=全部）")
    a = ap.parse_args()
    obj = Path(a.obj)
    if not obj.is_absolute():
        obj = ROOT / obj
    out = Path(a.out) if a.out else ROOT / "preview_tmp" / (obj.stem + f"_{a.view}_tex.png")
    return render(obj, out if out.is_absolute() else ROOT / out, a.view, a.size,
                  use_tex=not a.flat, max_faces=a.max_faces)


if __name__ == "__main__":
    sys.exit(main())
