#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mesh_assembly.py — 车身网格装配链（docs/57）

回答：零件/车辆的**外观**是怎么绑上去的？
  · **网格**：`configureMesh(new java.util.resource.ResourceRef("<车包>.rpk", <mesh_id>))`
  · **视觉类型**：`configureVisual(new RenderType("<车包>.rpk", <visual_id>), 6×float)`
  · **贴图**：`configureTexture(ResourceRef(..., <tex_id>))` + 类静态字段 `maskTexture` / `shadowTexture`
  · **贴花**：`mypd = new java.game.parts.PartDecal(a, b, c)`（`applyDecal(maskTexture/shadowTexture, mypd)`）
  · **几何/物理**：`configureType("<key>\t<params>")` 字符串（slot / body / wing / … 共 52 种键）

id 空间 = **车包内的资源 id**：用 `remaster/data/materials.json`（docs/53 材质表）把 id 翻成网格名，
再用 `out_rpak_meshes.json` 翻成导出的 OBJ 路径 ⇒ 三方对齐（零件类 → id → 名字 → 文件）。

输出：out_mesh_assembly.json（`--json` 可改路径；`--report` 打印汇总/抽样）。
"""
from __future__ import annotations
import argparse, collections, json, pathlib, re, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
PSEUDO = ROOT / "out_pseudo" / "vehicles"
MATERIALS = ROOT / "remaster" / "data" / "materials.json"
MESHES = ROOT / "out_rpak_meshes.json"
OUT = ROOT / "out_mesh_assembly.json"

FAMILY_KW = {"Bumper": "bumper", "Hood": "hood", "sideskirt": "sideskirt", "R_wing": "wing",
             "Trunk": "trunk", "Door": "door", "Muffler": "muffler", "Rim": "rim", "Tyre": "rim",
             "Interior": "interior", "SteeringWheel": "steering", "Chassis": "chassis"}

REF = re.compile(r'new java\.util\.resource\.(ResourceRef|RenderType)\.<init>\("([^"]+)",\s*(\d+)\)')
CM = re.compile(r'configureMesh\(')
CV = re.compile(r'configureVisual\(')
CT = re.compile(r'configureTexture\(')
CONF = re.compile(r'configureType\((?:"([^"]*)"|(\(\("([^"]+)"))')
STRAIGHT = re.compile(r'configureType\("([^"]*)"\);')
FLT = re.compile(r'-?\d+(?:\.\d+)?')

# configureType 键的语义表：✓ = 已由数据/文档证明，推断 = 由值形态推断，✗ = 未定
KEY_DOC = {
    "slot": ("装配", "物理槽的位姿 + id（docs/56）"), "slottype": ("装配", "槽类型号（11 / 其他）"),
    "slotdmgmode": ("装配", "槽的损伤模式位"), "slotdeform": ("装配", "槽的形变开关"),
    "use_mesh": ("外观", "网格使用开关/变体号（`0 0` 最常见；真正的网格见 configureMesh）"),
    "lods": ("外观", "LOD 表：级数 6 + 6 个距离阈值 + 6 个级标志（全库恒定，只有一条取值）"),
    "lod": ("外观", "LOD 生效区间 [first, last]（1 4 / 0 5）"),
    "flags": ("外观", "标志位（0x400 / 0x004 / 0x404 / 0x401）"),
    "dirt_texture": ("外观", "泥污贴图：组 id + 变体数 + 变体 id 列表"),
    "damage": ("外观", "损伤倍率（1.7 = 可损，0.0 = 不可损）"),
    "flexible": ("外观", "柔性参数：刚度 + 阻尼（用于可动件形变）"),
    "bone": ("外观", "骨骼绑定标记（无参）"),
    "noclick": ("外观", "关闭鼠标点选（无参）"), "nocollision": ("外观", "关闭碰撞（无参）"),
    "flap": ("外观", "可动盖板/翼的铰点：pos + 轴向 + 开合量"),
    "body": ("物理", "碰撞体：pos + rot + 质量因子 + 形状（sphere/box）+ 尺寸/半径"),
    "wing": ("物理", "气动/受力点：类型号 + pos + 方向 + 2 个系数"),
    "wheel": ("物理", "轮位/悬挂硬点：pos + rot + 半径/宽度类 4 值"), "wheelbones": ("物理", "轮骨骼开关"),
    "spring": ("物理", "弹簧：刚度 + 行程 + 预压"),
    "type": ("物理", "质量/形状类型（`10.000 sphere 0.650`）"),
    "controller": ("物理", "控制器索引组（`0 1 2 6`）"),
    "linked": ("物理", "联动标记"), "steering": ("物理", "方向盘/转向柱位姿"), "pedals": ("物理", "踏板位"),
    "seat": ("物理", "座椅位姿"), "shifter": ("物理", "排挡杆位姿"),
    "steerhelp": ("物理", "转向助力参数（6 值）"), "maxsteer": ("物理", "最大转向角（3 值）"),
    "steerspeed": ("物理", "转向速度（3 值）"),
    "camera": ("相机", "相机位：pos + rot + FOV/标志"), "ext_camera": ("相机", "外部相机位 + 距离"),
    "cockpit_rpm": ("座舱", "转速表针网格（RenderType 引用）"),
    "cockpit_speed": ("座舱", "速度表针网格（RenderType 引用）"),
    "osd_gauge": ("HUD", "HUD 仪表：网格 id 对 + 位置"), "osd_rpmpin": ("HUD", "HUD 转速针 + 量程"),
    "osd_spdpin": ("HUD", "HUD 速度针"), "osd_speed": ("HUD", "HUD 速度数字：网格 + 位置 + 格式串"),
    "osd_gear": ("HUD", "HUD 挡位：网格 + 位置 + 字符集"),
    "osd_gearplate": ("HUD", "HUD 挡位底板"), "osd_gearlever": ("HUD", "HUD 挡杆指示"),
}


def parse_class(text: str, stem: str):
    """→ dict（零件的资源绑定 + 全部 configureType）"""
    refs = collections.Counter()
    for m in REF.finditer(text):
        refs[m.group(1)] += 1
    cm = REF.search(text[text.find("configureMesh("):text.find("configureMesh(") + 200]) if CM.search(text) else None
    cv = None
    if CV.search(text):
        seg = text[CV.search(text).start():][:260]
        cv = REF.search(seg)
    ct = None
    if CT.search(text):
        seg = text[CT.search(text).start():][:200]
        ct = REF.search(seg)
    statics = {}
    for fld in ("maskTexture", "shadowTexture"):
        m = re.search(r'\.%s\s*=\s*new java\.util\.resource\.ResourceRef\.<init>\("([^"]+)",\s*(\d+)\)' % fld, text)
        if m:
            statics[fld] = {"rpck": m.group(1), "id": int(m.group(2))}
    decal = re.search(r'new java\.game\.parts\.PartDecal\.<init>\(([\d\s,]+)\)', text)
    desc = re.search(r'\n\s*return "([^"\n]{3,90})";', text)
    cfgs = collections.defaultdict(list)
    for line in text.splitlines():
        if "configureType(" not in line:
            continue
        s = line.split("configureType(", 1)[1]
        vals = []
        if s.startswith('"'):
            vals.append(s.split('"', 2)[1])
        else:                                  # (("key\t0x22 " + RenderType(...).id()) + "\t…")
            head = re.search(r'\(\("([a-z_0-9]+)', s)
            if head:
                vals.append(head.group(1))
                tail = re.findall(r'\+\s*"([^"]*)"', s)
                vals.extend(tail)
        head_key = None
        for v in vals:
            v = v.replace("\\t", "\t")
            k = v.split("\t")[0].strip()
            if k:
                head_key = k
            elif head_key:
                k, v = head_key, head_key + v      # 拼接式配置的尾段（以 \t 开头）
            rest = "\t".join(v.split("\t")[1:]).strip()
            if rest:
                cfgs[k].append(rest)
    return {
        "mesh_ref": {"rpck": cm.group(2), "id": int(cm.group(3))} if cm else None,
        "visual_ref": {"rpck": cv.group(2), "id": int(cv.group(3))} if cv else None,
        "texture_ref": {"rpck": ct.group(2), "id": int(ct.group(3))} if ct else None,
        "statics": statics,
        "decal": [int(x) for x in FLT.findall(decal.group(1))] if decal else None,
        "description": desc.group(1) if desc else None,
        "config": {k: v for k, v in cfgs.items()},
        "slot_ids": sorted({int(FLT.findall(p.replace("\t", " "))[-1]) for p in cfgs.get("slot", [])
                            if len(FLT.findall(p.replace("\t", " "))) >= 7}),
        "refs_seen": dict(refs),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="车身网格装配链（docs/57）")
    ap.add_argument("--json", metavar="PATH")
    ap.add_argument("--report", action="store_true")
    a = ap.parse_args(argv)

    # id → 网格名（按车包）
    mat = json.loads(MATERIALS.read_text(encoding="utf-8"))
    id2name = {}
    for arch, recs in mat["archives"].items():
        d = {}
        for r in recs:
            d.setdefault(r["mesh_id"], r["mesh"])
        id2name[arch] = d
    # 网格名 → OBJ
    mj = json.loads(MESHES.read_text(encoding="utf-8"))
    obj_of = {}
    for m in mj["meshes"]:
        p = pathlib.PureWindowsPath(m["obj"])
        obj_of.setdefault((p.parent.name, p.stem), m)

    parts, models, keyvals = {}, {}, collections.defaultdict(collections.Counter)
    unres_mesh, unres_vis, join_ok, names_ok, no_obj = [], [], 0, 0, []
    fam_ok, fam_bad, fam_skip, bad_ex = 0, 0, 0, []
    for p in sorted(PSEUDO.rglob("*.java")):
        t = p.read_text(encoding="utf-8", errors="ignore")
        if "configureType(" not in t and not CM.search(t):
            continue
        rec = parse_class(t, p.stem)
        car = p.parts[p.parts.index("vehicles") + 1] if "vehicles" in p.parts else "?"
        rec["car"], rec["archive"] = car, None
        for k, vals in rec["config"].items():
            for v in vals:
                keyvals[k][v[:32]] += 1
        rk = (rec["mesh_ref"] or {}).get("rpck")
        if rk:
            rec["archive"] = rk
        # 语义校验：引用的网格名是否含该零件族关键词（检验「材质表 id 空间」是否对口）
        kw = next((v for k, v in FAMILY_KW.items() if k in p.stem), None)
        if rec["mesh_ref"] and kw:
            _nm = id2name.get(rk, {}).get(rec["mesh_ref"]["id"])
            if _nm is None:
                fam_skip += 1
            elif kw in _nm.lower():
                fam_ok += 1
            else:
                fam_bad += 1
                if len(bad_ex) < 12:
                    bad_ex.append({"class": p.stem, "car": car, "id": rec["mesh_ref"]["id"], "table_name": _nm})
        if rec["mesh_ref"]:
            nid = rec["mesh_ref"]["id"]
            nm = id2name.get(rk, {}).get(nid)
            rec["mesh_name"] = nm
            if nm:
                names_ok += 1
                o = obj_of.get((car, nm))
                rec["mesh_obj"] = o["obj"] if o else None
                rec["mesh_geo"] = {"verts": o["verts"], "tris": o["tris"]} if o else None
                if o:
                    join_ok += 1
                else:
                    no_obj.append((p.stem, car, nm))
            else:
                unres_mesh.append((p.stem, rk, nid))
        if rec["visual_ref"] and rec["visual_ref"]["id"] not in id2name.get(rk, {}):
            unres_vis.append((p.stem, rec["visual_ref"]["id"]))
        (models if p.stem.startswith("Model_") else parts)[p.stem] = rec

    have_mesh = sum(1 for r in parts.values() if r["mesh_ref"])
    doc = {
        "_meta": {
            "tool": "tools/mesh_assembly.py", "doc": "docs/57_MESH_ASSEMBLY.md",
            "chain": "零件类 configureMesh(ResourceRef(车包, mesh_id)) → 材质表 id→网格名 → 导出 OBJ",
            "id_space": "车包内资源 id（同 id 在不同车包指向不同网格）",
            "config_note": "configureType 字符串里的 `\\t` 在 out_pseudo 里是转义两字符",
        },
        "summary": {
            "part_classes": len(parts), "model_classes": len(models),
            "parts_with_mesh_ref": have_mesh,
            "mesh_id_resolved_to_name": names_ok, "mesh_id_unresolved": len(unres_mesh),
            "mesh_name_resolved_to_obj": join_ok, "mesh_name_without_obj": len(no_obj),
            "visual_id_count": len(unres_vis),
            "mesh_name_family_match": fam_ok, "mesh_name_family_mismatch": fam_bad,
            "mesh_name_family_skipped": fam_skip,
            "config_keys": len(keyvals),
            "id_space_note": "configureMesh 的 id = 车包内 grid 资源 id；材质表 id 空间对口（同族 style 变体 4/4 对齐）"
                             "但 **id↔名配对存在系统性错位**（例：FL_Door_stock→158，材质表 FL_door=160）⇒ 名字仅供提示",
            "slot_ids_total": len({s for r in parts.values() for s in r["slot_ids"]}),
        },
        "resource_ops": {
            "configureMesh": "网格（本例 F_bumper_style_II → id 142 = `F_bumper_2`）",
            "configureVisual": "渲染/视觉类型（id 与网格相邻，如 142/143；6 个 float 参数）",
            "configureTexture": "主体贴图（车包内贴图 id，多数 = item_icons(18)）",
            "maskTexture/shadowTexture": "类静态字段：涂装遮罩 / 阴影贴图，配合 PartDecal.applyDecal",
        },
        "config_key_vocabulary": {
            k: {"count": sum(c.values()), "group": KEY_DOC.get(k, ("?", ""))[0],
                "meaning": KEY_DOC.get(k, ("?", "未归类"))[1],
                "samples": dict(c.most_common(4))}
            for k, c in sorted(keyvals.items(), key=lambda kv: -sum(kv[1].values()))},
        "parts": parts,
        "models": models,
        "unresolved": {"mesh": unres_mesh[:40], "mesh_without_obj": no_obj[:40], "visual": unres_vis[:20]},
        "family_mismatch_examples": bad_ex,
        "remaster_rules": [
            "零件外观 = configureMesh 的网格 + configureVisual 的视觉类型 + 3 张贴图（主体/遮罩/阴影）+ PartDecal 贴花。",
            "网格变体不看名字看 **id**：同族 style_* 靠 configureMesh 的 id 区分（style_III 可能对应 `_2`），必须查材质表。",
            "无 configureMesh 的零件（如原厂引擎盖）没有独立网格 ⇒ 属于车体网格的一部分。",
            "几何摆放仍看 `configureType(\"slot …\")`（docs/56）；外观与几何是两条独立链路。",
            "LOD：`lods` 全库恒定（6 级 + 距离 0.001/0.025/0.1/1.1/2.5/3.5 + 标志），`lod` 给生效区间。",
        ],
    }
    path = pathlib.Path(a.json) if a.json else OUT
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    s = doc["summary"]
    print("网格装配链 → %s" % path)
    print("  零件类 %d（有 configureMesh 的 %d）/ Model 类 %d / configureType 键 %d 种"
          % (s["part_classes"], s["parts_with_mesh_ref"], s["model_classes"], s["config_keys"]))
    print("  mesh_id → 材质表名 %d 条（未解 %d）→ 导出 OBJ %d 条（无 OBJ %d）；configureVisual 引用 %d 处（独立 id 空间）"
          % (s["mesh_id_resolved_to_name"], s["mesh_id_unresolved"],
             s["mesh_name_resolved_to_obj"], s["mesh_name_without_obj"], s["visual_id_count"]))
    if a.report:
        print("\nconfigureType 键（前 14）：")
        for k, v in list(doc["config_key_vocabulary"].items())[:14]:
            print("   %-14s %-5d %-5s %s" % (k, v["count"], v["group"], v["meaning"][:52]))
        print("\n样例（零件 → 网格 id/名 → OBJ）：")
        for stem, r in list(parts.items()):
            if r.get("mesh_name"):
                print("   %-44s id=%-4s %-16s %s" % (stem, r["mesh_ref"]["id"], r["mesh_name"],
                                                      (r.get("mesh_obj") or "-").split("\\")[-1]))
            if sum(1 for x in parts.values() if x.get("mesh_name")) > 6 and stem > "Coupe_TornadoR_L_sideskirt_style_III":
                break
    return 0


if __name__ == "__main__":
    sys.exit(main())
