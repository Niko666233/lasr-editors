#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""性能 stat 链 + 槽位表提取器 —— 关掉 docs/50 §6.8(#2) 与 §9 #7。

数据来源（全部可复现，纯离线）：
  * `STATS_*` / `ITEMSLOT_*` 常量 —— `out_init.json`（`tools/lift_expr.py` 从 **TUFA 指令流**抬升，
    字段类型全匹配零冲突 ⇒ 不受「伪码重建吞常量」影响）。
  * UI 取值公式 —— `out_pseudo/java/classes/game/frontend/ProgrBarCommon.java:142-208`（人工逐行核对后写死）。
  * 槽位表 —— **以 `Vehicle.class` 的 `fillSLUT` 字节码为准**重建（TREE 记录 #11）；
    `out_pseudo/.../Vehicle.java` 的伪码版本只作交叉校验（伪码少 3 个 `SlotMap`，重建丢失）。
  * info block —— 原生 `java.game.parts.Chassis.getInfoBlock() [F @0x486f20`；长度由 `push 0x13` 定为 19。

`fillSLUT` 字节码里的固定形态（分组规则即由此得出）：
    new SlotMap; push <字面量…>; INVOKESPECIAL SlotMap.<init>(…)      ← 连续若干次
    push <元素个数>; …; LOCAL_STORE <组号>                            ← 一组收尾
    … 65 组后依次 `Vehicle.slotLookupTable.addElement(local0 … local64)`

用法：
  python tools/stat_slots.py --json out_stats_spec.json
  python tools/stat_slots.py --report
"""
import argparse
import json
import math
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

from lasr_vm import chunks                                   # noqa: E402
from lasr_cfg import disasm                                  # noqa: E402
from lasr_named import load_methods_meta                     # noqa: E402
from resolve_pool import Pool                                # noqa: E402
from opcode_table import tree_records                        # noqa: E402

OP_INT = 0x05
OP_LOCAL_LOAD = 0x0b
OP_LOCAL_STORE = 0x0d
OP_INVOKESPECIAL = 0x11

VEHICLE_CLASS = "extracted/java/classes/game/Vehicle.class"
N_SLOTS = 65                  # = slotLookupTable.size() = Vehicle.baseslotcount

# ProgrBarCommon.refreshSliders 的 stat 取值映射（逐行核对）。
#   case 0（预览态）写 newStates、case 1（基准态）写 baseStates，两处公式完全相同。
UI_SOURCE = {
    "STATS_DURABILITY": {"from": "vehicle.statStates[0]",
                         "note": "switch 里没有它 ⇒ 走 default 分支，直接取 statStates 同下标"},
    "STATS_WEIGHT": {"block_index": 0, "negate": True, "src": "ProgrBarCommon.java:152,182"},
    "STATS_POWER": {"block_index": 2, "src": "ProgrBarCommon.java:164,194"},
    "STATS_TOP_SPEED": {"block_index": 4, "scale": 3.6, "unit_in": "m/s", "unit_out": "km/h",
                        "mph_factor": 0.62, "src": "ProgrBarCommon.java:155,185"},
    "STATS_ACCELERATION": {"block_index": 12, "negate": True, "src": "ProgrBarCommon.java:149,179"},
    "STATS_BRAKING": {"block_index": 16, "negate": True, "src": "ProgrBarCommon.java:146,176"},
    "STATS_CORNERING": {"block_index": 17, "src": "ProgrBarCommon.java:161,191"},
    "STATS_STABILITY": {"block_index": 18, "scale": 180.0 / math.pi, "unit_in": "rad/s",
                        "unit_out": "deg/s", "src": "ProgrBarCommon.java:158,188"},
}

# info block 里已能给出语义的槽（其余槽未逐条追原生函数体）
BLOCK_KNOWN = {
    0: "重量（性能条取负显示 ⇒ 越重条越短）",
    2: "功率",
    4: "极速（m/s；显示时 ×3.6）",
    12: "直线加速量（取负显示 ⇒ 疑为 0-100 km/h 时间）",
    16: "制动量（取负显示 ⇒ 疑为制动距离）",
    17: "过弯横向能力（g）",
    18: "稳定性（rad/s 偏航角速度上限；显示时 rad/s → °/s）",
}

SLOTMAP_PSEUDO = re.compile(r"new java\.game\.item\.SlotMap\.<init>\(([^)]*)\)")
GROUP_PSEUDO = re.compile(r"^local(\d+) = \{(.*)\};")
ADD_PSEUDO = re.compile(r"^java\.game\.Vehicle\.slotLookupTable\.addElement\(local(\d+)\);")


# ---------------------------------------------------------------- 常量（字节码）

def bytecode_consts():
    """从 out_init.json 取 STATS_* 与 ITEMSLOT_*（该文件数值来自字节码抬升）。"""
    d = json.loads((ROOT / "out_init.json").read_text(encoding="utf-8"))
    out = {"stats": {}, "item_slots": {}, "source": {}}
    for key, bucket, prefix, label in (
            ("java/classes/game/Vehicle.class#0", "stats", "STATS_", "Vehicle.<clinit>"),
            ("java/classes/game/item/IVehicle.class#0", "item_slots", "ITEMSLOT_", "IVehicle.<clinit>")):
        for s in d.get(key, {}).get("stmts", []):
            tgt = s.get("target") or ""
            m = re.match(r"java\.game\.(?:Vehicle|item\.IVehicle)\.(%s\w+)" % prefix, tgt)
            if not m:
                continue
            try:
                out[bucket][m.group(1)] = int(float(s["expr"]))
                out["source"].setdefault(label, []).append("%s = %s" % (m.group(1), s["expr"]))
            except Exception:
                continue
    return out


# ---------------------------------------------------------------- 槽位表（字节码）

def _ref(pool, pay):
    try:
        return pool.ref(pay)
    except Exception:
        return None


def slot_table_from_bytecode():
    """按分组规则从 `fillSLUT` 的指令流重建槽位表。"""
    ck = chunks((ROOT / VEHICLE_CLASS).read_bytes())
    pool = Pool(ck["CONS"][0])
    meta = load_methods_meta(ck)
    recs = [r for r in tree_records(ck["TREE"][0]) if r and r[-1] == 0x16]

    rec = None
    for k, r in enumerate(recs):
        m = meta.get(k)
        if m and pool.utf8(m[1]) == "fillSLUT":
            rec = r
    assert rec is not None, "找不到 fillSLUT"
    ins = list(disasm(rec))

    # 1) 所有 SlotMap 构造 + 其整型实参（紧邻的 OP_INT 序列）
    ctors = []          # [(指令下标, 实参列表)]
    for i, x in enumerate(ins):
        if x.pay is None or x.op < 0x10:
            continue
        r = _ref(pool, x.pay)
        if not (r and r[0] == "java.game.item.SlotMap" and r[1] == "<init>"):
            continue
        n = r[2].count("I")
        args, j = [], i - 1
        while j >= 0 and ins[j].op == OP_INT and len(args) < n:
            args.insert(0, ins[j].pay)
            j -= 1
        assert len(args) == n, "第 %d 个 SlotMap 实参不足（%s）" % (len(ctors), r[2])
        ctors.append((i, args))

    # 3) addElement 顺序（local0 … local64）—— 同时给出「哪些 local 才是组变量」
    order = []
    for i, x in enumerate(ins):
        if x.pay is None or x.op < 0x10:
            continue
        r = _ref(pool, x.pay)
        if not (r and r[1] == "addElement"):
            continue
        j = i - 1
        while j >= 0 and ins[j].op != OP_LOCAL_LOAD:
            j -= 1
        assert j >= 0, "addElement 前找不到 LOCAL_LOAD"
        order.append(ins[j].pay)
    assert len(order) == N_SLOTS, "addElement 次数 %d != %d" % (len(order), N_SLOTS)
    group_locals = set(order)

    # 2) 切组：每个「组变量」的 LOCAL_STORE 收走「上一组之后新建的全部 SlotMap」。
    #    收尾序列是 `push <元素数>; 0x22; 0x24; LOCAL_STORE <组号>`（计数 push 在倒数第三条），
    #    空组同样出现（push 0），所以不能按「有没有 SlotMap」筛。
    groups, bounds = {}, []
    for i, x in enumerate(ins):
        if x.op != OP_LOCAL_STORE or x.pay not in group_locals:
            continue
        lo = bounds[-1][0] + 1 if bounds else 0
        sel = [c for c in ctors if lo <= c[0] < i]
        cnt = None
        for j in range(i - 1, max(-1, i - 6), -1):
            if ins[j].op == OP_INT:
                cnt = ins[j].pay
                break
        assert cnt == len(sel), "组 %d 计数 push=%s 与实际 %d 个 SlotMap 不符" % (x.pay, cnt, len(sel))
        groups[x.pay] = [a for _, a in sel]
        bounds.append((i, x.pay))
    assert len(bounds) == N_SLOTS, "切出 %d 组 != %d" % (len(bounds), N_SLOTS)
    assert set(groups) == group_locals, "组变量集合不吻合：%s" % (group_locals ^ set(groups))

    rows = []
    for pos, li in enumerate(order):
        raw = groups.get(li, [])
        rows.append({
            "item_slot_index": pos,
            "slot_maps": [{"slot": a[-1], "partIndex": a[1] if len(a) == 3 else 0,
                           "linkVirtualSlot": a[0] if len(a) == 3 else -1} for a in raw],
        })
    return rows, len(ctors)


def parse_slot_table_pseudo():
    """伪码版（只作交叉校验）：返回 (行列表, SlotMap 总数)。"""
    txt = (ROOT / "out_pseudo/java/classes/game/Vehicle.java").read_text(encoding="utf-8")
    groups, order = {}, []
    for line in txt.splitlines():
        line = line.strip()
        m = GROUP_PSEUDO.match(line)
        if m:
            groups[int(m.group(1))] = SLOTMAP_PSEUDO.findall(m.group(2))
            continue
        m = ADD_PSEUDO.match(line)
        if m:
            order.append(int(m.group(1)))
    rows, total = [], 0
    for pos, li in enumerate(order):
        raw = groups.get(li, [])
        total += len(raw)
        rows.append({"item_slot_index": pos, "raw": raw})
    return rows, total


def slider_ranges():
    """从 ProgrBarCommon.setupSliderRanges 取 8 个 stat 的滑块量程（= 原版对各 stat 量程的声明）。"""
    txt = (ROOT / "out_pseudo/java/classes/game/frontend/ProgrBarCommon.java").read_text(encoding="utf-8")
    out = {}
    for kind, rx in (("min", re.compile(r"sliderMin\[java\.game\.Vehicle\.(STATS_\w+)\] = \(?(-?[\d.]+)\)?;")),
                     ("max", re.compile(r"sliderMax\[java\.game\.Vehicle\.(STATS_\w+)\] = \(?(-?[\d.]+)\)?;"))):
        for name, v in rx.findall(txt):
            out.setdefault(name, {})[kind] = float(v)
    return out


ATTACH_RX = re.compile(r"^this\.attach = local(\d+);")
ARR_RX = re.compile(r"^local(\d+) = \{(.*)\};$")


def part_attach():
    """各零件基类（java/game/item/I*.java）声明的 `attach`（= 占用哪些 ITEMSLOT）。

    形如 `local2 = {java.game.item.IVehicle.ITEMSLOT_EBAY_ENGINE}; this.attach = local2;`；
    也有表达式形式（ISticker: `ITEMSLOT_STYL_STICKER + this.placement_`），原样保留。
    """
    base = ROOT / "out_pseudo/java/classes/game/item"
    out = {}
    for p in sorted(base.glob("I*.java")):
        lines = [ln.strip() for ln in p.read_text(encoding="utf-8").splitlines()]
        arrs, hits = {}, []
        for ln in lines:
            m = ARR_RX.match(ln)
            if m:
                arrs[m.group(1)] = m.group(2)
                continue
            m = ATTACH_RX.match(ln)
            if m:
                body = arrs.get(m.group(1))
                if body is None:
                    hits.append({"local": m.group(1), "raw": None,
                                 "note": "来自形参/前一条语句，未在本方法内直接给出数组字面量"})
                    continue
                toks = [t.strip() for t in body.split(",") if t.strip()]
                names, exprs = [], []
                for t in toks:
                    mm = re.fullmatch(r"java\.game\.item\.IVehicle\.(ITEMSLOT_\w+)", t)
                    if mm:
                        names.append(mm.group(1))
                    else:
                        exprs.append(t)
                hits.append({"local": m.group(1), "item_slots": names, "expressions": exprs,
                             "raw": body})
        if hits:
            out[p.stem] = hits
    return out


# ── info block 逐槽（原生 getInfoBlock @0x486f20 + 填充器 0x4544a0）──
INFO_GETTER, INFO_HI = 0x486F20, 0x487150
INFO_FILLER, INFO_FILLER_HI = 0x4544A0, 0x4556B8

# 槽号 → (名字, 单位, 置信度, 证据)。偏移不手抄：由 tools/native_frame_trace.py 从字节码现算。
INFO_SLOT_SEMANTICS = {
    0: ("weight", "kg", "verified",
        "0x454614：1.0 / [动力总成+0x14]（倒数质量）；UI `WEIGHT ← -infoBlock[0]`；"
        "★ **原版日志字符串坐实**：`Vehicle.updatevariables` 调试块 `\">>> Total mass:\\t\\t\" + block[0] + \" kg\"`"),
    1: ("internal_mass_scaled", "?", "unknown",
        "0x454781：([栈+0x8c] × 2e-4)，后被 min/max 反复更新（0x454cb8/0x454f6b/0x4552a0）；"
        "输入是 `0x4bb760` 取的 vec3 分量（同族的两个 vec3 之差见槽 5/6），✗ 物理量未定"),
    2: ("power", "hp?", "verified",
        "0x454c1e：[动力总成+0x1b0] × [底盘+0x2298]；UI `POWER ← infoBlock[2]`"),
    3: ("torque_like", "?", "inferred",
        "0x454c54：[动力总成+0x1ac] × [底盘+0x2298]（与功率同尺度 ⇒ 推断扭矩类）"),
    4: ("top_speed", "m/s", "verified",
        "0x454bf1 哨兵 −1 → 0x454edc 起 `comiss` 取最大（引擎曲线族最大值）；"
        "UI `TOP_SPEED ← infoBlock[4] × 3.6`（km/h）"),
    5: ("front_axle_share", "0..1", "verified",
        "0x45463b：d_a/(d_a+d_b)，两个 `0x4bb760` 取的 vec3 之差作几何量；"
        "★ 原版等价实现：`Vehicle.updatevariables` 的 `(CM.z - w0.z)/(w2.z - w0.z)`（再用 mass 乘成 kg）"),
    6: ("rear_axle_share", "0..1", "verified", "0x454644：1 − 槽 5"),
    7: ("internal_geometry_a", "?", "unknown", "0x4547c0：归一化量 × 4e-4，后被 min/max 更新"),
    8: ("internal_geometry_b", "?", "unknown", "0x4547d6：同族，× 4e-4"),
    9: ("axle_load_ratio", "?", "verified",
        "0x454b0b：([轮0+0xb8] + [轮1+0xb8]) = **前轴和**、([轮3+0xb8] + [轮2+0xb8]) = **后轴和**"
        "（0x15e0 = 0x1528+0xb8、0x4030 = 3×0x1528+0xb8、0x2b08 = 2×0x1528+0xb8 ⇒ 配对算术自证）；0x454b49 再按比例分配"),
    10: ("front_axle_wheel_coef", "1/kg?", "verified",
        "调用方 0x4870a1：[轮数组+0x58] × (1/质量) —— 轮 0 = **前轴代表轮**（同款取法见 `getWheelPos(0)`）"),
    11: ("rear_axle_wheel_coef", "1/kg?", "verified",
        "调用方 0x4870c5：[轮数组+0x2aa8] = 轮 2 的 +0x58（0x2aa8 = 2×0x1528+0x58）× 1/质量 —— 轮 2 = **后轴代表轮**"),
    12: ("accel_time_0_100", "s", "verified",
        "0x4551f4/0x45520e/0x455215：累积量 + 门限 [0x6ed6b8]=27.7778 m/s —— **恰为 100 km/h**；"
        "UI `ACCELERATION ← -infoBlock[12]`（量程 2–20 s）⇒ 0-100 km/h 用时"),
    13: ("powertrain_raw_a", "?", "unknown",
        "0x454c35：[引擎+0xfd4]+0x1c4 原值（4 字节整拷贝、无缩放）—— 与槽 2/3 同源（安装的发动机数据块），✗ 具体字段未定"),
    14: ("powertrain_raw_b", "?", "unknown",
        "0x454c6b：[引擎+0xfd4]+0x1c0 原值（无缩放）—— 同族，✗ 具体字段未定"),
    15: ("accel_like", "m/s²?", "inferred",
        "0x455485：Δ × 1/质量；仅在 ([+0x2c]+[+0x30]) > 100 时计算，否则置 0"),
    16: ("braking_decel", "m/s²", "verified",
        "0x45548a：Δ × 1/质量；UI `BRAKING ← -infoBlock[16]`（量程 10–100 m ⇒ 制动距离）"),
    17: ("cornering", "g?", "verified",
        "0x455607 `fstp [esi+0x68]`（x87）：(a+b)/(2·f+c) 比值；UI `CORNERING ← infoBlock[17]`（0.5–5 g）"),
    18: ("stability", "rad/s", "verified",
        "0x455689 `fstp [esi+0x6c]`（x87）：四轮 (+0x4c/+0x58/+0x64/+0x68) 平均（× [0x6ecd94]=0.25）后过 `fptan`；"
        "UI `STABILITY ← infoBlock[18] / π × 180`（°/s）"),
}

# 本轮顺带解出的浮点常量真值（.rdata，VA → 值, 语义）
INFO_CONSTANTS = {
    0x6EC138: (97.22222137451172, "350/3.6 = 350 km/h 的 m/s 值（极速上界；与 UI 量程 0–350 km/h 自洽）"),
    0x6ED6B8: (27.77777862548828, "100/3.6 = 100 km/h 门限（槽 12）"),
    0x6EBD94: (100.0, "100.0 门限（槽 15/16 的百公里门）"),
    0x6EC6A0: (9.549296379089355, "60/2π = RPM ↔ rad/s 换算"),
    0x6ECD94: (0.25, "四轮平均系数（槽 18）"),
    0x6EC27C: (1.5707963705062866, "π/2"), 0x6ED444: (0.6366197466850281, "2/π"),
    0x6E766C: (1.0, "1.0"), 0x6E7668: (-1.0, "−1.0（极速搜索哨兵）"),
    0x6ED67C: (0.00019999999494757503, "2e-4"), 0x6ED678: (0.00039999998989515007, "4e-4"),
}


def info_block_layout():
    """info block 19 槽 → 填充器结构偏移（字节码现算）+ 逐槽语义标注。"""
    from native_frame_trace import trace
    _ins, _base, events = trace(INFO_GETTER, INFO_HI, 0x6438F0)
    raw, computed = [], []
    for kind, data, va in events:
        if kind != "slot":
            continue
        if isinstance(data, tuple) and data and data[0] == "计算":
            computed.append({"slot": len(raw), "va": hex(va), "expr": data[3]})
            raw.append(None)
        else:
            raw.append(None if data is None else data[0])
    ints = [o for o in raw if isinstance(o, int)]
    lo = min(ints)
    hi = max(ints)
    rows = []
    for i, o in enumerate(raw):
        name, unit, conf, ev = INFO_SLOT_SEMANTICS.get(i, ("?", "", "unknown", ""))
        rows.append({
            "slot": i,
            "struct_offset": ("+0x%02x" % (o - lo)) if isinstance(o, int) else None,
            "byte": (o - lo) if isinstance(o, int) else None,
            "name": name, "unit": unit, "confidence": conf, "evidence": ev})
    return {
        "producer": "native java.game.parts.Chassis.getInfoBlock() [F @0x486f20",
        "length": len(rows),
        "length_evidence": "反汇编里 `push 0x13` 后 call 0x649170 分配 19 元素 float[]",
        "write_pattern": "`call 0x6438f0(数组, 槽号, 值)`，槽号 0..18 顺序写入",
        "layout_method": "tools/native_frame_trace.py 跟踪「未清理 push 字节数 D」，把每槽的来源换算成"
                         "填充器结构偏移（槽 0 的来源 = 结构 +0x00，权重与 UI 一致）",
        "filler": hex(INFO_FILLER) + "（stdcall 2 参 / `ret 8`）",
        "struct_prefix": "info block = 填充器写出结构的前 %d 个 float（0x00–0x%02x）；结构本身 ≥ 0x220 字节"
                         % (hi // 4 + 1, hi),
        "slots": rows,
        "computed_in_caller": computed,
        "constants": {hex(k): {"value": v, "note": n} for k, (v, n) in INFO_CONSTANTS.items()},
        "unknown_slots": [r["slot"] for r in rows if r["confidence"] == "unknown"],
        "wheel_order": "FL,FR,RL,RR —— 三证：① Java `VPV_TYRE_FL/FR/RL/RR_INFL = 16..19` 的顺序；"
                       "② 填充器里轴和配对 `[轮数组+0xb8] + [轮数组+0x15e0]`（0x15e0 = 0x1528+0xb8 ⇒ 轮0+轮1 = 前轴）、"
                       "`[轮数组+0x4030] + [轮数组+0x2b08]`（轮3+轮2 = 后轴）⇒ 0/1 = 前轴、2/3 = 后轴；"
                       "③ 原版 `getWheelPos(0)/(2)` 被用来算轴距（前/后轴代表轮）",
        "consumers": {
            "ui": "纯 UI 消费者只有 `game/frontend/ProgrBarCommon.refreshSliders`（取槽 0/2/4/12/16/17/18 + default 槽 0 当 DURABILITY）",
            "debug_log": "`game/Vehicle.updatevariables` 里的 `if (true)` 死调试块：打印 `Total mass (kg)` / `Wheelbase (m)` / "
                         "`Axle load (front|rear) kg (%)` —— ★ **实机对照钩子**：游戏日志里这三行可直接验证 info block 与轴荷公式",
            "note": "其余 11 槽（1/3/5..11/13/14/15）无任何 Java 消费者 ⇒ 内部中间量，未命名不影响重制",
        },
        "corrections": ["docs/44 §2.4 把 `0x4BB760` 记为「标志查询」——实测它是 thiscall 的 "
                        "**3 float vec3 取值器**（`push &vec3` 后被调用，槽 5/6 的几何量即由它取得）"],
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="性能 stat 链 + 槽位表提取")
    ap.add_argument("--json", default=None)
    ap.add_argument("--report", action="store_true")
    a = ap.parse_args(argv)

    c = bytecode_consts()
    stats, itemslots = c["stats"], c["item_slots"]
    rows, n_maps = slot_table_from_bytecode()
    prows, ptotal = parse_slot_table_pseudo()
    sliders = slider_ranges()
    attach = part_attach()
    ib = info_block_layout()

    # 伪码 vs 字节码：逐组比元素个数（伪码少的正是「重建丢失」的证据）
    delta = [{"item_slot_index": br["item_slot_index"], "bytecode": len(br["slot_maps"]),
              "pseudo": len(pr["raw"])}
             for br, pr in zip(rows, prows) if len(br["slot_maps"]) != len(pr["raw"])]

    by_index = {}
    for k, v in itemslots.items():
        by_index.setdefault(v, []).append(k)

    out = {
        "_meta": {
            "tool": "tools/stat_slots.py",
            "sources": ["out_init.json（字节码抬升的 STATS_/ITEMSLOT_ 常量）",
                        "Vehicle.class fillSLUT 字节码（槽位表权威来源）",
                        "out_pseudo/java/classes/game/Vehicle.java（伪码交叉校验）",
                        "out_pseudo/java/classes/game/frontend/ProgrBarCommon.java:142-208（取值公式）",
                        "原生 java.game.parts.Chassis.getInfoBlock @0x486f20（info block）"],
            "slot_table_bytecode_vs_pseudo": {"bytecode_slot_maps": n_maps, "pseudo_slot_maps": ptotal,
                                              "differing_groups": delta},
            "stats_theoric_max_note":
                "`STATS_THEORIC_MAX = 1` 是**字节码真值**（非重建假象）：`out_init.json` 抬升值与 "
                "`Vehicle.<clinit>` 原始字面量流 `…5,0,1,1,2,3,4,5,6,7,8` 按字段序一一对应，两路一致。"
                "后果：`IPart.<i>()` 里 `statChanges = new [F[STATS_THEORIC_MAX]` 长度也是 1 ⇒ "
                "Java 层加/卸零件只改 `statStates[0]`（DURABILITY）；其余 7 项是 info block 的派生显示值。",
        },
        "stats": {
            "constants": stats,
            "display": UI_SOURCE,
            "slider_ranges": sliders,
            "theoric_max": stats.get("STATS_THEORIC_MAX"),
            "max": stats.get("STATS_MAX"),
            "applied_in_java_layer": [0],
        },
        "info_block": dict(ib, ui_used={str(k): v for k, v in BLOCK_KNOWN.items()}),
        "item_slots": {
            "values": itemslots,
            "count": len(itemslots),
            "by_index": {str(i): by_index.get(i, []) for i in range(N_SLOTS)},
        },
        "part_attach": {
            "note": "各零件基类 `java.game.item.I*` 的 `attach` 数组 = 该零件族占用哪些 ITEMSLOT；"
                    "与 slot_table 配合才能定位物理槽（表：ITEMSLOT → 物理槽；attach：零件 → ITEMSLOT）。",
            "classes": attach,
        },
        "slot_table": {
            "index_semantics": "下标 = ITEMSLOT_* 值（0..64）；每项 = 该 item slot 占用的物理槽 SlotMap 列表",
            "slot_map_fields": {"slot": "物理槽 id（由车辆 Model 类的 `slot\\t…\\t<id>` 定义）",
                                "partIndex": "同一 item 的第几个物理件",
                                "linkVirtualSlot": "该物理槽同时算作哪个虚拟槽（-1 = 无）"},
            "groups": len(rows),
            "slot_maps": n_maps,
            "rows": rows,
        },
    }

    if a.report or not a.json:
        print("STATS_* (%d):" % len(stats))
        for k, v in sorted(stats.items(), key=lambda kv: kv[1]):
            print("   %-24s %s" % (k, v))
        print("\nITEMSLOT_*: %d 个（槽位表按 0..64 索引）" % len(itemslots))
        print("\nUI 取值映射:")
        for k, v in UI_SOURCE.items():
            print("   %-20s ← %s" % (k, v.get("from") or
                                     "info_block[%s]%s%s" % (v["block_index"],
                                                             " × %.4g" % v["scale"] if v.get("scale") else "",
                                                             "（取负）" if v.get("negate") else "")))
        print("\ninfo block 逐槽（原生 0x486f20；偏移 = 填充器 %s 的结构偏移）:" % ib["filler"].split("（")[0])
        for r in ib["slots"]:
            print("   [%2d] %-22s %-8s %-9s %s" % (r["slot"], r["name"], r["unit"] or "?",
                                                   r["confidence"], r["struct_offset"] or "（调用方现算）"))
        print("\n槽位表(字节码): %d 组 / %d 个 SlotMap；伪码版 %d 个（少 %d）"
              % (len(rows), n_maps, ptotal, n_maps - ptotal))
        for r in rows:
            if not r["slot_maps"]:
                continue
            i = r["item_slot_index"]
            nm = ",".join(by_index.get(i, [])) or "?"
            print("   [%2d] %-30s %s" % (i, nm, [m["slot"] for m in r["slot_maps"]]))
        print("   空组 %d 个：%s" % (sum(1 for r in rows if not r["slot_maps"]),
                                     [r["item_slot_index"] for r in rows if not r["slot_maps"]]))
        if delta:
            print("   与伪码不一致的组: %s" % delta)
    if a.json:
        Path(a.json).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        print("-> %s" % a.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
