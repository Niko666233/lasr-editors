"""解 RPAK 存档里的 **ASCII 材质表**（`docs/53`）。

LASR 的每个美术存档（车、地图、前端、粒子…）都带一块纯文本材质表：

    mesh 0x00000002            ← 网格/子件 id（与场景块的 mesh 记录 / .iscx 子件对应）
    flags 2048
    shd_center 0.000 0.000 0.000
    shd_diru   0.000 0.000 0.000     ← 阴影投影基（5 组向量）
    shd_dirv   0.000 0.000 0.000
    shd_vbase  0.000 0.000 0.000
    shd_vup    0.000 0.000 0.000
    texture 0x0004001C         ← 贴图引用 0x<page><id>
    texture 0x00000056

`texture 0x<page><id>`：**page** 选一个资源池、**id** 是该池里的资源号。
page 0 = 本存档自己的资源表；其它 page 指向别的存档的资源池（实测 {0,3,4,5}，
由 `build_pages()` 按覆盖率机械判定，不靠猜）。

资源号来自**记录流**（存档里带名字的表，`walk_records`）：

    u16 flags | f32 1.0 | u32 file_off | u32 size | u8 len | name[len]
    u32 kind  // (group<<16)|type ；99=地图贴图、1=全局贴图池、200=前端贴图 …
    u32 index // 该资源在本存档的 id

用法:
    python tools/material_table.py                  # 全部存档 → out_material_tables.json
    python tools/material_table.py --stats           # 覆盖率 + 未解项
    python tools/material_table.py --dump <archive>  # 人类可读表
"""
from __future__ import annotations

import argparse
import json
import re
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

ROOT = Path(__file__).resolve().parent.parent
GAME = Path(r"C:\Games\LASR")

TEX_REF = re.compile(rb"texture 0x([0-9A-Fa-f]{8})")


# ── 记录流 ──────────────────────────────────────────────────────────────────
def walk_records(d: bytes, start: int):
    """从 start 起走带名字的资源记录流（2026-09 逐字节核对，见 docs/53 §1）。

    唯一稳定的记录标记是 `f32 1.0`（首字段不总是 0x04xx，如 `0x000e`，不能当判据）。
    固定 15 字节头 + 8 字节尾，每条 `23 + len(name)` 字节、记录间无间隙。
    """
    recs, off, n = [], start, len(d)
    while off + 23 <= n:
        try:
            one, = struct.unpack_from("<f", d, off + 2)
        except struct.error:
            break
        if abs(one - 1.0) > 1e-6:
            break
        flags, = struct.unpack_from("<H", d, off)
        off_, size, ln = struct.unpack_from("<IIB", d, off + 6)
        if ln < 2 or off + 23 + ln > n or off_ > n:
            break
        raw = d[off + 15:off + 15 + ln]
        if raw[-1] != 0 or any(not (0x20 <= b < 0x7F) for b in raw[:-1]):
            break
        kind, idx = struct.unpack_from("<II", d, off + 15 + ln)
        recs.append({"off": off, "flags": flags, "file_off": off_, "size": size,
                     "name": raw[:-1].decode("ascii"), "kind": kind,
                     "type": kind & 0xFFFF, "group": kind >> 16, "index": idx})
        off += 23 + ln
    return recs, off


def record_streams(d: bytes, min_len: int = 5):
    """全文扫 `1.0` 标记 → 该文件里所有记录流（一个存档可能有多条，如 frontend）。"""
    chains = []
    for m in re.finditer(re.escape(b"\x00\x00\x80\x3f"), d):
        cand = m.start() - 2
        if cand < 0:
            continue
        recs, end = walk_records(d, cand)
        if len(recs) >= min_len:
            chains.append((cand, len(recs), end))
    chains.sort()
    merged = []
    for c in chains:
        if merged and c[0] < merged[-1][2]:
            continue
        merged.append(c)
    return [(s, *walk_records(d, s)) for s, _l, _e in merged]


_CACHE: dict = {}


def archive_table(rel: str):
    """该存档的资源表 {index: (type, name)} + 全部记录。"""
    if rel in _CACHE:
        return _CACHE[rel]
    p = GAME / rel
    table, allrec = {}, []
    if p.exists():
        for _s, recs, _e in record_streams(p.read_bytes()):
            allrec.extend(recs)
            for r in recs:
                table.setdefault(r["index"], (r["type"], r["name"]))
    _CACHE[rel] = (table, allrec)
    return _CACHE[rel]


def known_archives():
    return sorted(p.relative_to(GAME).as_posix() for p in GAME.rglob("*.rpk"))


# ── 材质表 ──────────────────────────────────────────────────────────────────
TOKEN = re.compile(rb"(mesh 0x([0-9A-Fa-f]{8})|flags (?:0x)?([0-9A-Fa-f]+)|"
                   rb"shd_([a-z]+) ([-\d. ]+)|texture 0x([0-9A-Fa-f]{8}))")


def material_blocks(d: bytes):
    """解一个存档里的材质表（车包换行是 `\\r\\r\\n`、条目间夹 NUL，故按 token 扫）。"""
    m = re.search(rb"mesh 0x[0-9A-Fa-f]{8}", d)
    if not m:
        return []
    seg = d[m.start():m.start() + 400_000]
    items, cur = [], None
    for t in TOKEN.finditer(seg):
        body = t.group(0)
        if body.startswith(b"mesh "):
            if cur:
                items.append(cur)
            cur = {"mesh_id": int(t.group(2), 16), "flags": None,
                   "shadow": {}, "textures": []}
        elif cur is None:
            continue
        elif body.startswith(b"flags"):
            v = body.split(b" ", 1)[1]
            cur["flags"] = int(v, 16) if v.lower().startswith(b"0x") else int(v)
        elif body.startswith(b"shd_"):
            cur["shadow"][t.group(4).decode()] = [float(x) for x in t.group(5).split()]
        else:
            v = int(t.group(6), 16)
            cur["textures"].append({"page": v >> 16, "id": v & 0xFFFF, "raw": f"0x{v:08X}"})
    if cur:
        items.append(cur)
    return [{"offset": m.start(), "materials": items}] if items else []


def build_pages():
    """page → 资源池。

    实测结论（每个引用方存档逐 page 做覆盖率探测，见 docs/53 §2）：

    | page | 池 | 依据 |
    |---|---|---|
    | 0 | **本存档自己的资源表** | 全部 39 个存档里本档自解覆盖率最高（0.83–1.00） |
    | 2 | 本存档（车件第二层：mask/glow 类） | 车包的 page 2 id 在本档表里 4/4 命中 |
    | 3/4/5 | `maps/texture.rpk`（全球地图贴图池 64 张） | 地图存档的 page 4/5 id 覆盖率 1.00、名字 94–97% 是贴图 |

    `own` 这一项由调用方按当前存档替换；这里只给非 0 页。
    """
    global_pool = "maps/texture.rpk"
    table, _ = archive_table(global_pool)
    return {
        0: {"archive": None, "note": "本存档自己的资源表", "table": {}},
        2: {"archive": None, "note": "本存档（车件第二层 mask/glow）", "table": {}},
        3: {"archive": global_pool, "table": dict(table)},
        4: {"archive": global_pool, "table": dict(table)},
        5: {"archive": global_pool, "table": dict(table)},
    }


def _full_map(rel: str):
    """`maps/xxx_b.rpk`（精简图）会引用完整图 `maps/xxx.rpk` 的图集 —— 见 docs/53 §2 注。"""
    if rel.endswith("_b.rpk"):
        return rel[:-6] + ".rpk"
    return None


def resolve(items, pages, own_table, records=None, rel=None):
    """把 `texture 0x<page><id>` 解成文件名。

    回退链（每一步都记在 `pool` 里，便于审计）::

        page 0     : 本存档
        page 2     : 本存档 → vehicles.rpk（共用车件层，**推断**）
        page 3/4/5 : maps/texture.rpk → 本存档 → 完整图（`xxx_b` → `xxx`）
    """
    full = _full_map(rel) if rel else None
    veh = archive_table("vehicles.rpk")[0]
    for it in items:
        rec = (records or {}).get(it["mesh_id"])
        it["mesh_name"] = rec["name"] if rec else None
        it["mesh_type"] = rec["type"] if rec else None
        for t in it["textures"]:
            ent, pool = None, None
            if t["page"] in (0, 2):
                ent = own_table.get(t["id"])
                pool = "own"
                if ent is None and t["page"] == 2 and t["id"] in veh:
                    ent, pool = veh[t["id"]], "vehicles.rpk(fallback,推断)"
            else:
                pool_tbl = (pages.get(t["page"]) or {}).get("table", {})
                ent = pool_tbl.get(t["id"])
                pool = (pages.get(t["page"]) or {}).get("archive")
                if ent is None:
                    ent = own_table.get(t["id"])
                    pool = "own(fallback)" if ent else None
                if ent is None and full:
                    ent = archive_table(full)[0].get(t["id"])
                    pool = f"{full}(fallback)" if ent else None
            t["pool"] = pool
            t["file"] = ent[1] if ent else None
            t["src_type"] = ent[0] if ent else None
            t["resolved"] = bool(t["file"])
    return items


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", metavar="ARCHIVE")
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--out", default="out_material_tables.json")
    args = ap.parse_args()

    if args.dump:
        pages = build_pages()
        d = (GAME / args.dump).read_bytes()
        own_table, allrec = archive_table(args.dump)
        records = {}
        for x in allrec:
            records.setdefault(x["index"], x)
        for blk in material_blocks(d):
            resolve(blk["materials"], pages, own_table, records, args.dump)
            print(f"=== {args.dump} 材质表 @{blk['offset']:,} "
                  f"{len(blk['materials'])} 条 ===")
            for it in blk["materials"]:
                files = [t["file"] or f"?{t['page']}:{t['id']}" for t in it["textures"]]
                print(f"  mesh 0x{it['mesh_id']:04X} [{it['mesh_name'] or '?'}"
                      f"/type {it['mesh_type']}] flags={it['flags']} "
                      f"贴图×{len(files)}: {files[:8]}")
        return 0

    pages = build_pages()
    result = {"_source": "tools/material_table.py",
              "page_map": {str(k): {kk: vv for kk, vv in v.items() if kk != "table"}
                           for k, v in pages.items()},
              "archives": {}}
    tot = Counter()
    for rel in known_archives():
        d = (GAME / rel).read_bytes()
        if b"mesh 0x" not in d or b"texture 0x" not in d:
            continue
        blocks = material_blocks(d)
        if not blocks:
            continue
        own_table, allrec = archive_table(rel)
        records = {}
        for x in allrec:
            records.setdefault(x["index"], x)
        for blk in blocks:
            resolve(blk["materials"], pages, own_table, records, rel)
            tot["materials"] += len(blk["materials"])
            for it in blk["materials"]:
                tot["meshes_named"] += bool(it["mesh_name"])
                for t in it["textures"]:
                    tot["refs"] += 1
                    tot["resolved"] += t["resolved"]
                    if not t["resolved"]:
                        tot["unresolved_nonnull"] += t["id"] != 0
        result["archives"][rel] = blocks
        tot["archives"] += 1
    result["stats"] = {k: v for k, v in tot.items()}

    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=1),
                              encoding="utf-8")
    print(f"[materials] {tot['archives']} 存档 / {tot['materials']} 条材质 / 贴图引用 "
          f"{tot['resolved']}/{tot['refs']} "
          f"({tot['resolved'] / max(tot['refs'], 1) * 100:.1f}%) → {args.out}")
    print("  page 映射:", {k: (v.get("archive") or "本存档")
                           for k, v in pages.items()})
    print(f"  材质条目 {tot['materials']}（其中 {tot['meshes_named']} 条能对回网格记录名）；"
          f"未解引用里非 0 号 id 只有 {tot['unresolved_nonnull']} 条")
    if args.stats:
        miss = Counter()
        for rel, blocks in result["archives"].items():
            for blk in blocks:
                for it in blk["materials"]:
                    for t in it["textures"]:
                        if not t["resolved"]:
                            miss[(t["page"], t["id"])] += 1
        for k, v in miss.most_common(20):
            print("   未解:", k, "×", v)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
