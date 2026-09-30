#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RPAK → 引擎可用资产（命名解包 / 纹理 PNG / 网格 OBJ）。

三个可独立重跑的阶段：

    --extract   RPAK → assets_raw/<archive>/<名字>.<ext>       （按名字解包，保留原名）
    --textures  DDS  → assets/textures/<archive>/<名字>.png     （PIL 解 DXT1/3/5）
    --meshes    INVO → assets/meshes/<archive>/<名字>.obj(+.mtl)（复用 tools/invo_obj.py 的布局）

名字来源（本轮解出，见 docs/52）：存档索引与"目录块"里的记录

    u16 flags(0x04xx)  f32 1.0  u32 file_offset  u32 total_size(=payload+8)  u8 len  char name[len]

`file_offset` 与数据区的条目偏移逐条精确对齐（车包 322/322），于是条目拿到了名字。

用法：
  python tools/rpak_assets.py --extract                  # 全部 52 个存档
  python tools/rpak_assets.py --extract --archive vehicles/Hornet_Wega_2006.rpk
  python tools/rpak_assets.py --textures --meshes
"""
from __future__ import annotations

import collections
import os
import json
import re
import struct
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
GAME = Path(r"C:\Games\LASR")
RAW = ROOT / "assets_raw"
ASSETS = ROOT / "assets"
sys.path.insert(0, str(TOOLS))

MAGICS = {b"DDS ": "dds", b"INVO": "mesh", b"TUFA": "tufa", b"RPAK": "rpak",
          b"OggS": "ogg", b"RIFF": "riff", b"FMOD": "fmod"}
EXT = {"dds": ".dds", "mesh": ".iscx", "rpak": ".rpk", "ogg": ".ogg", "riff": ".wav",
       "tufa": ".class"}
SAFE = re.compile(r"[^A-Za-z0-9_.\-]")


# ── 解析 ────────────────────────────────────────────────────────────────────
def parse_archive(p: Path):
    """→ (d, data_start, entries, records)。解析全在 tools/rpak_export.scan_archive()。"""
    import rpak_export as rx
    sc = rx.scan_archive(p)
    entries = []
    for e in sc["entries"]:
        entries.append({"tag": e["tag"], "off": e["off"], "size": e["size"],
                        "kind": MAGICS.get(sc["data"][e["off"] + 8:e["off"] + 12], e["tag"]),
                        "payload": e["off"] + 8,
                        "names": list(e.get("names", []))})
    return sc["data"], sc["data_start"], entries, sc["records"]


def bind_names(entries, records):
    """记录 → 条目：起止偏移都对齐（记录的 size = 条目 size + 8）。"""
    by_off = {}
    for e in entries:
        by_off.setdefault(e["off"], []).append(e)
    for r in records:
        e = next((x for x in by_off.get(r["off"], []) if x["size"] == r["size"] - 8), None)
        if e is not None:
            e.setdefault("names", []).append(r["name"])
    return entries


def invo_mesh_name(d: bytes, payload: int, size: int):
    blk = d[payload:payload + size]
    if blk[:4] != b"INVO":
        return None
    try:
        _, n = struct.unpack_from("<2I", blk, 4)
        pairs = [struct.unpack_from("<2I", blk, 0x0C + 8 * i) for i in range(n)]
    except struct.error:
        return None
    for _, o in pairs:
        if 0 < o < len(blk) - 1:
            ln = blk[o]
            s = blk[o + 1:o + 1 + ln]
            if 1 <= ln <= 64 and all(32 <= c < 127 for c in s):
                return s.decode()
    return None


KNOWN_EXT = re.compile(r"(?i)(\.dds|\.tga|\.png|\.bmp|\.jpg|\.iscx|\.iscy|\.obj|\.ogg|\.wav|\.fsb|\.rpk|\.bin)$")


def safe_name(base: str, i: int, ext: str):
    base = SAFE.sub("_", base).strip("_") or f"unnamed_{i:04d}"
    base = KNOWN_EXT.sub("", base)      # 游戏资源名里常带扩展名（`track_comb.png` 其实是 DDS），
    if len(base) > 96:                  # 先剥掉再按 tag 追加，否则会落成 `x.png.dds` / `x.png.png`
        base = base[:96]
    return base if base.lower().endswith(ext) else base + ext


# ── 阶段 1：解包 ────────────────────────────────────────────────────────────
def stage_extract(only=None):
    files = sorted(GAME.rglob("*.rpk"))
    if only:
        files = [f for f in files if f.relative_to(GAME).as_posix() in only]
    manifest = {"_source": "tools/rpak_assets.py --extract", "archives": {}}
    tot = collections.Counter()
    for f in files:
        rel = f.relative_to(GAME).as_posix()
        d, data, entries, records = parse_archive(f)
        bind_names(entries, records)
        dest = RAW / rel[:-4]
        dest.mkdir(parents=True, exist_ok=True)
        recs_out, used = [], set()
        for i, e in enumerate(entries):
            nm = (e.get("names") or [None])[0]
            if not nm and e["kind"] == "mesh":
                nm = invo_mesh_name(d, e["payload"], e["size"])
                if nm:
                    nm = f"{nm}.iscx"
            stem = safe_name(nm or f"{i:04d}_{e['tag']}", i, EXT.get(e["kind"], ".bin"))
            while stem in used:
                stem = f"{Path(stem).stem}_{i}{Path(stem).suffix}"
            used.add(stem)
            (dest / stem).write_bytes(d[e["payload"]:e["payload"] + e["size"]])
            recs_out.append({"file": stem, "name": nm, "tag": e["tag"], "kind": e["kind"],
                             "off": e["off"], "size": e["size"],
                             "named": bool(nm)})
            tot["assets"] += 1
            tot["named"] += bool(nm)
            tot[e["kind"]] += 1
        # 目录块里"没有对应条目"的命名资源（如 sound.rpk 的整套音效索引块）
        ent_offs = {e["off"] for e in entries}
        loose = []
        for r in records:
            if r["off"] in ent_offs or r["size"] == 0:
                continue
            if r["off"] + r["size"] > len(d):
                continue
            nm = safe_name(r["name"], len(loose), ".bin")
            (dest / nm).write_bytes(d[r["off"]:r["off"] + r["size"]])
            loose.append({"file": nm, "name": r["name"], "size": r["size"]})
            tot["loose"] += 1
        manifest["archives"][rel] = {
            "file_size": len(d), "index_size": data - 8,
            "dir_records": len(records), "entries": len(entries),
            "named_entries": sum(1 for e in entries if e.get("names")),
            "assets": recs_out, "loose_named": loose,
        }
    (ROOT / "out_rpak_assets.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[extract] 存档 {len(files)} / 资产 {tot['assets']:,}（带名 {tot['named']:,}）"
          f" / 目录块独立命名块 {tot['loose']}")
    print("  按类型:", {k: v for k, v in tot.items() if k not in ("assets", "named", "loose")})
    return 0


# ── 阶段 2：纹理 ───────────────────────────────────────────────────────────
def dds_info(b: bytes):
    try:
        sz, flags, h, w, pitch, depth, mips = struct.unpack_from("<7I", b, 4)
        fourcc = b[84:88].decode("latin1").strip("\x00")
        return {"width": w, "height": h, "mips": mips, "fourcc": fourcc}
    except struct.error:
        return {}


def stage_textures():
    from PIL import Image
    out = ASSETS / "textures"
    stats = collections.Counter()
    fails, table = [], []
    for src in sorted(RAW.rglob("*.dds")):
        rel = src.relative_to(RAW)
        dst = out / rel.with_suffix(".png")
        dst.parent.mkdir(parents=True, exist_ok=True)
        b = src.read_bytes()
        info = dds_info(b)
        try:
            im = Image.open(src)
            im.load()
            info = dds_info(b)
            if (info.get("fourcc") or "") == "DXT1":
                # BC1 的 1-bit 透空：Pillow 把透明纹素解成纯洋红 (255,0,255)，
                # 这里还原成 alpha=0，免得重制时贴图上出现洋红边（实测 sign.png 就是这情况）。
                im = im.convert("RGBA")
                px = im.load()
                for y in range(im.size[1]):
                    for x in range(im.size[0]):
                        r, g, bl, a = px[x, y]
                        if r == 255 and g == 0 and bl == 255:
                            px[x, y] = (0, 0, 0, 0)
            elif im.mode != "RGB":
                im = im.convert("RGBA")
            im.save(dst)
            stats["ok"] += 1
            stats[info.get("fourcc") or "?"] += 1
            table.append({"src": str(rel), "png": str(dst.relative_to(ROOT)),
                          "w": im.size[0], "h": im.size[1],
                          "fourcc": info.get("fourcc"), "mips": info.get("mips")})
        except Exception as ex:
            fails.append({"src": str(rel), "error": f"{type(ex).__name__}: {ex}"})
    (ROOT / "out_rpak_textures.json").write_text(json.dumps(
        {"_source": "tools/rpak_assets.py --textures", "count": len(table),
         "stats": dict(stats), "failures": fails, "textures": table},
        ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[textures] 成功 {stats['ok']} / 失败 {len(fails)}  格式 {dict(stats)}")
    for f in fails[:5]:
        print("   ✗", f)
    return 0


# ── 阶段 3：网格 ───────────────────────────────────────────────────────────
def mtl_for(mesh: Path, tex_dir: Path):
    """把网格目录里出现的贴图名（.dds）写成 mtl 引用（有同名 PNG 就指过去）。"""
    txt = mesh.read_bytes()
    names = sorted({m.group().decode() for m in
                    re.finditer(rb"[A-Za-z0-9_\-]{2,60}\.(?:dds|tga|png)", txt)})
    lines = [f"# materials referenced by {mesh.name} (名字串取自 INVO 材质块)"]
    mats = []
    for i, n in enumerate(names):
        stem = Path(n).stem
        png = tex_dir / (stem[0].upper() + stem[1:] + ".png")
        if not png.exists():
            cands = list(tex_dir.glob(f"{stem}.png")) or list(tex_dir.glob(f"[{stem[0].upper()}{stem[0]}]" + stem[1:] + ".png"))
            png = cands[0] if cands else None
        lines.append(f"newmtl mat_{i}_{re.sub(r'[^A-Za-z0-9_]', '_', stem)[:48]}")
        if png is not None:
            lines.append(f"map_Kd ../textures/{png.name}")
        mats.append(n)
    return "\n".join(lines) + "\n", mats


def stage_mtl():
    """把 `out_material_tables.json` 的绑定写成 OBJ 可用的 `.mtl`（docs/53）。

    一个存档的材质表里 `mesh <id>` 的记录名 == 导出的 `<name>.obj` 文件名，
    于是每个 OBJ 拿到自己的材质：`newmtl <name>` + 若干 `map_Kd`（按材质表顺序）。
    """
    man = ROOT / "out_material_tables.json"
    if not man.exists():
        print("[mtl] 缺 out_material_tables.json（先跑 tools/material_table.py）")
        return 1
    tables = json.loads(man.read_text(encoding="utf-8"))["archives"]
    tot = collections.Counter()
    for arch, blocks in tables.items():
        base = arch[:-4]
        out_dir = ASSETS / "meshes" / base
        tex_dir = ASSETS / "textures" / base
        mats = {}
        for blk in blocks:
            for it in blk["materials"]:
                if it["mesh_name"]:
                    mats.setdefault(it["mesh_name"], []).extend(
                        [t["file"] for t in it["textures"] if t["file"]])
        for name, files in mats.items():
            obj = out_dir / f"{name}.obj"
            if not obj.exists():
                continue
            seen, lines = set(), []
            for f in files:
                if f in seen:
                    continue
                seen.add(f)
                png = tex_dir / (Path(f).stem + ".png")
                if not png.exists():
                    continue
                rel = os.path.relpath(png, obj.parent).replace("\\", "/")
                # 第 1 张当漫反射，其余当附加层（保留顺序，导入器可自选）
                key = "map_Kd" if not any(l.startswith("map_Kd") for l in lines) else "map_Ka"
                lines.append(f"{key} {rel}")
            mtl = obj.with_suffix(".mtl")
            mtl.write_text(f"# {arch} :: {name}（tools/material_table.py）\n"
                           f"newmtl {name}\n" + "".join(l + "\n" for l in lines),
                           encoding="utf-8")
            body = obj.read_text(encoding="utf-8", errors="ignore")
            if "mtllib" not in body.split("\n")[1]:
                body = body.replace("\n", f"\nmtllib {name}.mtl\nusemtl {name}\n", 1)
                obj.write_text(body, encoding="utf-8")
            tot["mtl"] += 1
            tot["layers"] += len(lines)
    print(f"[mtl] 写 {tot['mtl']} 个 .mtl（贴图层合计 {tot['layers']}）")
    return 0


def stage_meshes():
    import invo_obj
    out = ASSETS / "meshes"
    tot = collections.Counter()
    fails, table, containers = [], [], []
    for src in sorted(RAW.rglob("*.iscx")):
        rel = src.relative_to(RAW)
        dst = out / rel.with_suffix(".obj")
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            data = src.read_bytes()
            subs = invo_obj.read_submeshes(data)
            ok = [s for s in subs if s.get("ok")]
            if not ok:
                # 没有 kind=4 顶点块的多半是**场景/分组节点**（garazs00、map.iscx…），
                # 几何在别的资源里 —— 不当失败，单独列出来。
                desc = invo_obj.descriptors(data)
                containers.append({"src": str(rel), "sub_streams": len(desc),
                                   "kinds": dict(collections.Counter(k for k, _, _ in desc))})
                continue
            invo_obj.write_obj(subs, dst)
            tri = sum(len(s["idx"]) // 3 for s in ok)
            vert = sum(len(s["verts"]) for s in ok)
            strides = sorted({s["stride"] for s in ok})
            tex_dir = ASSETS / "textures" / rel.parent
            mtl, refs = mtl_for(src, tex_dir)
            mtl_path = dst.with_suffix(".mtl")
            if refs:
                mtl_path.write_text(mtl, encoding="utf-8")
            table.append({"obj": str(dst.relative_to(ROOT)), "submeshes": len(ok),
                          "verts": vert, "tris": tri, "strides": strides,
                          "texture_refs": refs,
                          "mtl": str(mtl_path.relative_to(ROOT)) if refs else None})
            tot["meshes"] += 1
            tot["tris"] += tri
            tot["verts"] += vert
            tot["with_tex"] += bool(refs)
        except Exception as ex:
            fails.append({"src": str(rel), "error": f"{type(ex).__name__}: {ex}"})
    (ROOT / "out_rpak_meshes.json").write_text(json.dumps(
        {"_source": "tools/rpak_assets.py --meshes", "stats": dict(tot),
         "failures": fails, "scene_containers": containers, "meshes": table},
        ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[meshes] 导出 {tot['meshes']} 个网格  顶点 {tot['verts']:,}  三角 {tot['tris']:,}"
          f"  带贴图引用 {tot['with_tex']}  场景容器 {len(containers)}  失败 {len(fails)}")
    for f in fails[:5]:
        print("   ✗", f)
    return 0


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 1
    only = None
    if "--archive" in args:
        only = set(args[args.index("--archive") + 1].split(","))
    if "--extract" in args:
        stage_extract(only)
    if "--textures" in args:
        stage_textures()
    if "--meshes" in args:
        stage_meshes()
    if "--mtl" in args:
        stage_mtl()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
