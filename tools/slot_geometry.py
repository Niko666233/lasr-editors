#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""slot_geometry.py — 零件槽「几何来源」普查器（docs/56）

回答的问题：谁给 `SlotMap.slot`（物理槽 id）提供位姿？

结论（本工具自证）：
  · 车辆 `Model_*.java` 声明**骨架槽 + 默认装配件**的位姿；
  · **造型/结构零件类自带槽位姿**（如 `Coupe_TornadoR_F_Bumper_stock` 声明 1000 的 pos/rot）；
  · 纯参数件（引擎/变速箱/差速器/排气/氮气/悬挂/传动）**一个 configureType 都不调**
    ⇒ 无网格（无 `use_mesh`）、无 slot 声明 ⇒ 表里为它们定义的物理槽是**记账用的逻辑槽**；
  · 游戏从未出货的零件族（护栏/防滚架/座椅/刹车/散热器/中冷/车顶翼…）对应的槽 = **死槽**。

声明格式（`out_pseudo` 里的字符串字面量，`\t` 为转义两字符）：
    configureType("slot\\t\\t<x y z>\\t\\t<rx ry rz>\\t\\t<id>")
"""
from __future__ import annotations
import argparse, collections, json, pathlib, re, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
PSEUDO = ROOT / "out_pseudo" / "vehicles"
SPEC = ROOT / "out_stats_spec.json"
PARTS = ROOT / "remaster" / "data" / "parts.json"
OUT = ROOT / "out_slot_geometry.json"

NUM = re.compile(r"-?\d+(?:\.\d+)?")
SLOT_MARK = 'configureType("slot'
# item 槽名关键词 → parts.json 的 domain（None = 游戏无此类零件）
DOMAIN = {
    "STYL_F_BUMPER": "body.front_bumper", "STYL_R_BUMPER": "body.rear_bumper",
    "STYL_HOOD": "body.hood", "STYL_L_SIDESKIRT": "body.sideskirts",
    "STYL_R_SIDESKIRT": "body.sideskirts", "STYL_R_WING": "body.chassis_wing",
    "STYL_TRUNK": "body.trunk_wing", "STYL_LIGHTBAR": "body.ctf_lightbar",
    "STYL_INTERIOR": "styling.interior", "STYL_STEERING_WHEEL": "styling.steering_wheel",
    "STYL_RIMS": "styling.rims", "STYL_STICKER": "styling.sticker", "STYL_PAINT": "styling.paintjob",
    "RGER_SUSPENSION": "handling.running_gear", "RGER_TYRES": "handling.tyres",
    "EBAY_ENGINE": "power.engine", "EBAY_TRANSMISSION": "power.transmission",
    "EBAY_MUFFLER": "power.muffler", "EBAY_N20": "power.nitrous", "EBAY_NITROUS": "power.nitrous",
    "EBAY_WEIGHT_REDUCTION": "handling.weight_reduction",
    # 以下刻意留空：游戏里没有这些零件（死槽）
    "RGER_BRAKES": None, "EBAY_RADIATOR": None, "EBAY_INTERCOOLER": None,
    "STYL_F_GUARD_RAIL": None, "STYL_R_GUARD_RAIL": None, "STYL_S_GUARD_RAILS": None,
    "STYL_ROLLCAGE": None, "STYL_F_WING": None, "STYL_ROOF_WING": None,
    "STYL_R_SEATS": None, "STYL_SHIFT_KNOB": None, "STYL_ENTERTAINMENT": None, "STYL_GAUGES": None,
}


def parse_slot_lines(text: str):
    """→ [(id, pos, rot)]，逐行取数字：前三 = 位置、中三 = 朝向、最后一个 = id。"""
    out = []
    for line in text.splitlines():
        if SLOT_MARK not in line:
            continue
        ns = NUM.findall(line.split(SLOT_MARK, 1)[1])
        # 格式：pos(3) rot(3) id —— 第 7 个数才是 id；行尾可能还有 `\t; 注释`（注释里的数字不是 id）
        if len(ns) < 7:
            continue
        out.append((int(float(ns[6])), " ".join(ns[:3]), " ".join(ns[3:6])))
    return out


def scan_classes():
    """→ {类名: {'is_model':bool,'slots':[(id,pos,rot)],'use_mesh':bool}}"""
    res = {}
    for p in sorted(PSEUDO.rglob("*.java")):
        t = p.read_text(encoding="utf-8", errors="ignore")
        res[p.stem] = {
            "is_model": p.stem.startswith("Model_"),
            "slots": parse_slot_lines(t),
            "use_mesh": 'configureType("use_mesh' in t,
            "cfg_calls": len(re.findall(r'configureType\(', t)),
            "other_cfg": len(re.findall(r'configureType\(', t)) - t.count(SLOT_MARK),
        }
    return res


def load_part_counts():
    if not PARTS.exists():
        return {}
    pj = json.loads(PARTS.read_text(encoding="utf-8"))
    return {k: v for k, v in
            collections.Counter({d: n for v in pj["items"].values()
                                 for d, n in v["by_domain"].items()}).items()}


def domain_for(item_slot_names):
    for nm in item_slot_names:
        key = nm.replace("ITEMSLOT_", "")
        for k, dom in DOMAIN.items():
            if key.startswith(k) or key == k:
                return dom
    return None


def main(argv=None):
    ap = argparse.ArgumentParser(description="零件槽几何来源普查（docs/56）")
    ap.add_argument("--json", metavar="PATH", help="写 JSON（默认 out_slot_geometry.json）")
    ap.add_argument("--report", action="store_true", help="打印逐槽表")
    args = ap.parse_args(argv)

    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    by_index = {int(k): ((v[0] if v else "#%d" % int(k)) if isinstance(v, list) else v)
                for k, v in spec["item_slots"]["by_index"].items()}
    ref = collections.defaultdict(set)          # 物理槽 id → {item 槽下标}
    for r in spec["slot_table"]["rows"]:
        for m in r["slot_maps"]:
            ref[m["slot"]].add(r["item_slot_index"])

    classes = scan_classes()
    decl = collections.defaultdict(list)        # id → [(类名, pos, rot, is_model)]
    for stem, info in classes.items():
        for sid, pos, rot in info["slots"]:
            decl[sid].append((stem, pos, rot, info["is_model"]))
    dom_n = load_part_counts()

    slots = []
    for sid in sorted(set(ref) | set(decl)):
        names = [str(by_index.get(i, "?")) for i in sorted(ref.get(sid, ()))]
        d = decl.get(sid, [])
        car = [x for x in d if x[3]]
        part = [x for x in d if not x[3]]
        if d:
            verdict, why = "geometry", "有槽位姿声明（%d 个类：Model %d / 零件 %d）" % (len(d), len(car), len(part))
        else:
            dom = domain_for(names)
            n = dom_n.get(dom, 0) if dom else 0
            verdict = "logical" if n else "dead"
            why = ("零件的 configureType 数为 0（无 use_mesh/slot）⇒ 只改数值、不产生几何"
                   if n else "游戏无此类零件（parts.json 全域普查）")
        slots.append({
            "slot": sid,
            "referenced_by_table": bool(ref.get(sid)),
            "item_slots": names,
            "part_domain": domain_for(names),
            "part_count": (dom_n.get(domain_for(names), 0) if not d else None),
            "verdict": verdict, "why": why,
            "declared_by_car_model": sorted({x[0] for x in car}),
            "declared_by_part_class": sorted({x[0] for x in part}),
            "sample_pose": {"pos": d[0][1], "rot": d[0][2], "from": d[0][0]} if d else None,
        })

    geom = [s for s in slots if s["verdict"] == "geometry"]
    logi = [s for s in slots if s["verdict"] == "logical"]
    dead = [s for s in slots if s["verdict"] == "dead"]
    with_slot_and_mesh = sum(1 for c in classes.values() if c["slots"] and c["use_mesh"])
    with_slot_no_mesh = sum(1 for c in classes.values() if c["slots"] and not c["use_mesh"])
    doc = {
        "_meta": {"tool": "tools/slot_geometry.py", "doc": "docs/56_SLOT_GEOMETRY.md",
                  "format": 'configureType("slot\\t\\t<x y z>\\t\\t<rx ry rz>\\t\\t<id>")',
                  "note": "\\t 在 out_pseudo 里是转义两字符；前三数=位置、中三数=朝向、末数=物理槽 id"},
        "summary": {
            "classes_scanned": len(classes),
            "classes_declaring_slots": sum(1 for c in classes.values() if c["slots"]),
            "classes_declaring_slots_and_use_mesh": with_slot_and_mesh,
            "classes_declaring_slots_without_use_mesh": with_slot_no_mesh,
            "classes_with_slot_but_no_other_configureType":
                sum(1 for c in classes.values() if c["slots"] and c["other_cfg"] == 0),
            "classes_zero_configureType":
                sum(1 for c in classes.values() if c["cfg_calls"] == 0),
            "classes_zero_configureType_examples":
                [n for n, c in sorted(classes.items()) if c["cfg_calls"] == 0][:8],
            "distinct_ids_declared": len(decl),
            "slots_referenced_by_table": len(ref),
            "geometry": len(geom), "logical": len(logi), "dead": len(dead),
            "geometry_referenced": sum(1 for s in geom if s["referenced_by_table"]),
            "declared_but_not_referenced": sorted(s["slot"] for s in geom
                                                  if not s["referenced_by_table"]),
            "model_declared_ids": sorted({s["slot"] for s in geom if s["declared_by_car_model"]}),
            "part_only_ids": sorted({s["slot"] for s in geom
                                     if s["declared_by_part_class"] and not s["declared_by_car_model"]}),
        },
        "verdict_note": {
            "geometry": "有槽位姿 ⇒ 装配后按该 pos/rot 摆放网格",
            "logical": "无位姿 ⇒ 槽只用于 stats/装配记账，零件不产生几何",
            "dead": "无位姿且游戏无对应零件 ⇒ 表中未使用的定义",
        },
        "slots": slots,
    }
    path = pathlib.Path(args.json) if args.json else OUT
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    s = doc["summary"]
    print("槽几何普查 → %s" % path)
    print("  扫描类 %d｜含 slot 声明 %d（其中 %d 也声明 use_mesh、%d 不带网格）"
          % (s["classes_scanned"], s["classes_declaring_slots"],
             s["classes_declaring_slots_and_use_mesh"], s["classes_declaring_slots_without_use_mesh"]))
    print("  表引用物理槽 %d｜有几何 %d｜逻辑槽 %d｜死槽 %d｜含 slot 类共声明 %d 个 id"
          % (s["slots_referenced_by_table"], s["geometry"], s["logical"], s["dead"], s["distinct_ids_declared"]))
    if args.report:
        print("\n%-7s %-32s %-22s %s" % ("槽id", "item 槽", "判定", "说明"))
        for x in slots:
            if x["verdict"] != "geometry":
                print("%-7d %-32s %-8s %s" % (x["slot"], ",".join(x["item_slots"])[:31], x["verdict"], x["why"][:44]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
