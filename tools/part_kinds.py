#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 TUFA 指令流取回**零件 `kind`（阶）常量** —— docs/50 §9 #8 的落地。

问题：`out_pseudo/` 是重建产物，重建器把「`<init>` 里传给超类 `<init>(I)` 的立即数」
丢了（docs/00「常量提升」），于是 `parts.json` 里的阶只能**按类名后缀猜**
（`stage_index()`：`_stage_III` → 3）。

真值在 TUFA 指令流里，形态就一条：

    LOCAL_LOAD 0
    INT LITERAL k          ← 就是 kind
    INVOKESPECIAL <base>.<init> (I)

`getStage()` 直接 `return kind`；`getName()` / `getPriority()` / `loadItemTextures()`
都按 kind `1..5` 分派（1..4 = Stage I—IV，**5 = Unique**，0 = 原厂 stock）。

用法：
  python tools/part_kinds.py --json out_part_kinds.json        # 全量
  python tools/part_kinds.py --dump <class.class>              # 看单个类的证据
  python tools/part_kinds.py --report                          # 分布 + 与名字推断对账
"""
import argparse
import json
import re
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
from lasr_vm import chunks                                    # noqa: E402
from lasr_cfg import disasm, name_of                          # noqa: E402
from lasr_named import load_methods_meta, ref_text, class_name   # noqa: E402
from resolve_pool import Pool                                 # noqa: E402
from opcode_table import tree_records                          # noqa: E402

OP_INT = 0x05          # INT LITERAL
OP_LOCAL_LOAD = 0x0b
OP_LOCAL_STORE = 0x0d
OP_INVOKESPECIAL = 0x11

ROMAN = ["I", "II", "III", "IV", "V"]


def stage_by_name(class_name_str):
    """现有 `parts.json` 的做法：按类名后缀猜阶（拿来做对账基线）。"""
    n = class_name_str.rsplit(".", 1)[-1]
    if n.endswith("_stock"):
        return 0
    if n.endswith("_WB") or "_WB_" in n:
        return 5
    for i, r in enumerate(ROMAN, 1):
        if n.endswith("_stage_" + r):
            return i
    m = re.search(r"_(\d+)$", n)
    return int(m.group(1)) if m else None


def read_tufa(path):
    ck = chunks(Path(path).read_bytes())
    pool = Pool(ck["CONS"][0])
    recs = [r for r in tree_records(ck["TREE"][0]) if r and r[-1] == 0x16]
    meta = load_methods_meta(ck)
    sup = pool.ref(struct.unpack_from("<I", ck["CLSS"][0], 12)[0])
    return ck, pool, recs, meta, (sup[0] if sup else None)


def ctor_calls(rec, pool):
    """取一个方法里「传给某 `<init>` 的立即数」：[(值, 目标类, 描述符, 指令偏移)]。"""
    out = []
    loc = {}
    last = None
    for ins in disasm(rec):
        if ins.op == OP_INT:
            last = ins.pay
        elif ins.op == OP_LOCAL_LOAD:
            if ins.pay in loc:
                last = loc[ins.pay]
        elif ins.op == OP_LOCAL_STORE:
            loc[ins.pay] = last
        elif ins.op == OP_INVOKESPECIAL:
            r = pool.ref(ins.pay)
            if r and r[1] == "<init>":
                out.append((last, r[0], r[2], ins.off))
    return out


IDX = None


def index():
    """类名 → .class 路径（沿构造器链自证时要回读基类文件）。"""
    global IDX
    if IDX is None:
        IDX = {}
        for f in list(ROOT.glob("extracted/java/**/*.class")) + \
                list(ROOT.glob("extracted/vehicles/**/*.class")):
            try:
                nm = Pool(chunks(f.read_bytes())["CONS"][0]).utf8(0)
            except Exception:
                continue
            if nm:
                IDX[nm] = f
    return IDX


def _params(desc):
    """描述符的参数段文本（不含返回类型）。"""
    if not desc or not desc.startswith("(") or ")" not in desc:
        return ""
    return desc[1:desc.index(")")]


def resolve_kind(rec, pool, seen=None, depth=0):
    """沿 `<init>` 调用链求 kind。

    只认「**真的作为实参传进某个 `java.game.item.*` 的 `(I…)` 构造器**」的 int 字面量；
    子类不传时沿不带 int 实参的基类构造器递归（`_stock` 类就靠这条走到基类的 `INT LITERAL 0`）。
    装饰类（`IF_Doors` → `ISet.<init>()`、`IPaintjob` → `IPart.<init>()`）链上没有 int ⇒ 无阶。
    返回 (kind, 证据链, 是否经基类) 或 None。
    """
    if depth > 4:
        return None
    seen = seen if seen is not None else set()
    calls = [c for c in ctor_calls(rec, pool)
             if (c[1] or "").startswith("java.game.item.")
             and c[1] != "java.game.item.IVehicle"]        # 车体变体不是零件
    for v, target, desc, off in calls:
        if desc and desc.startswith("(I") and isinstance(v, int) and 0 <= v <= 5:
            return (v, "INT LITERAL %s → %s.<init>%s @%d" % (v, target, desc, off), False)
    for _v, target, desc, off in calls:
        if not desc or "I" in _params(desc):
            continue                                       # 参数里没有 int 才值得递归
        key = (target, desc)
        if key in seen:
            continue
        seen.add(key)
        f = index().get(target)
        if not f:
            continue
        try:
            _ck, p2, recs2, meta2, _s = read_tufa(f)
        except Exception:
            continue
        for k2, r2 in enumerate(recs2):
            m2 = meta2.get(k2)
            if m2 and p2.utf8(m2[1]) == "<init>" and p2.utf8(m2[2]) == desc:
                got = resolve_kind(r2, p2, seen, depth + 1)
                if got:
                    return (got[0], got[1] + " ⇒ 经基类 %s.<init>%s" % (target, desc), True)
    return None


def kind_of(path, reasons=None):
    """返回 (dict | None, 未命中原因 | None, 类名 | None)。"""
    ctx = {"cls": None}

    def why(tag):
        if reasons is not None:
            reasons[tag] += 1
        return (None, tag, ctx["cls"])

    try:
        ck, pool, recs, meta, sup = read_tufa(path)
    except Exception as e:
        return why("TUFA 解析失败: %s" % type(e).__name__)
    cls = pool.utf8(0)
    ctx["cls"] = cls
    if not cls:
        return why("无类名")
    for k, rec in enumerate(recs):
        m = meta.get(k)
        if not m:
            continue
        if pool.utf8(m[1]) != "<init>":
            continue
        item_calls = [c for c in ctor_calls(rec, pool)
                      if (c[1] or "").startswith("java.game.item.")
                      and c[1] != "java.game.item.IVehicle"]
        if not item_calls:
            return why("非零件类（构造器不调 java.game.item.*；内层网格/外观类）")
        got = resolve_kind(rec, pool)
        if got:
            kind, evidence, via_base = got
            target = evidence.split("→ ")[1].split(".<init>")[0] if "→ " in evidence else None
            return ({"file": str(Path(path).name), "class": cls, "extends": sup,
                     "kind": kind, "implicit": via_base,
                     "base_ctor": evidence.split("→ ")[1].split(" @")[0] if "→ " in evidence else None,
                     "kind_source": evidence, "target": target}, None, cls)
        return why("无阶（分阶不适用：装饰/非分阶零件，如 IF_Doors→ISet、IPaintjob→IPart）")
    return why("类里没有 <init> 方法（继承自父类）")


def scan(limit=None, pattern=None):
    files = sorted(ROOT.glob("extracted/vehicles/**/*.class"))   # 零件类都在这里
    if pattern:
        files = [f for f in files if pattern in str(f)]
    out, unresolved = [], {}
    reasons = Counter()
    for i, f in enumerate(files):
        if limit and i >= limit:
            break
        r, reason, cls = kind_of(f, reasons)
        if r:
            r["stage_by_name"] = stage_by_name(r["class"])
            out.append(r)
        else:
            unresolved[cls or f.name] = reason
    return out, unresolved, reasons, len(files)


def main(argv=None):
    ap = argparse.ArgumentParser(description="从 TUFA 指令流取回零件 kind（阶）常量")
    ap.add_argument("--json", default=None)
    ap.add_argument("--dump", default=None, help="单个 .class：打印 <init> 反汇编")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--grep", default=None, help="只扫路径含该串的类")
    a = ap.parse_args(argv)

    if a.dump:
        p = Path(a.dump)
        p = p if p.is_absolute() else ROOT / p
        ck, pool, recs, meta, sup = read_tufa(p)
        print("class %s\nextends %s" % (pool.utf8(0), sup))
        for k, rec in enumerate(recs):
            m = meta.get(k)
            if not m or pool.utf8(m[1]) != "<init>":
                continue
            print("--- <init>%s (%d bytes) ---" % (pool.utf8(m[2]), len(rec)))
            for ins in disasm(rec):
                print("  %4d  %02x %-20s %s" % (ins.off, ins.op, name_of(ins.op),
                                                ref_text(pool, ins.pay) if ins.op == OP_INVOKESPECIAL
                                                else (ins.pay if ins.pay is not None else "")))
            print("  -> ctor_calls:", ctor_calls(rec, pool))
        return 0

    res, unresolved, reasons, nfiles = scan(limit=(a.limit or None), pattern=a.grep)
    expl = sum(1 for r in res if not r.get("implicit"))
    impl = len(res) - expl
    print("扫描 %d 个类 → 命中 kind %d 个（显式 %d / 沿基类链自证 %d）；未命中 %d"
          % (nfiles, len(res), expl, impl, len(unresolved)))
    if a.report or not a.json:
        by_base = defaultdict(Counter)
        agree = Counter()
        for r in res:
            base = (r["extends"] or "?").rsplit(".", 1)[-1]
            by_base[base][r["kind"]] += 1
            if r["stage_by_name"] == r["kind"]:
                agree["一致"] += 1
            elif r["stage_by_name"] is None:
                agree["名字里没阶（新增信息）"] += 1
            else:
                agree["冲突"] += 1
        for base, c in sorted(by_base.items(), key=lambda kv: -sum(kv[1].values())):
            print("  %-22s %s" % (base, dict(sorted(c.items()))))
        print("  与 name 推断对账:", dict(agree))
        if agree["冲突"]:
            print("  冲突样例:")
            for r in [x for x in res if x["stage_by_name"] is not None
                      and x["stage_by_name"] != x["kind"]][:10]:
                print("    %-60s kind=%s name=%s" % (r["class"].rsplit(".", 1)[-1],
                                                     r["kind"], r["stage_by_name"]))
        print("  未命中原因:")
        for tag, n in reasons.most_common():
            print("    %-56s %d" % (tag, n))
    if a.json:
        Path(a.json).write_text(json.dumps(
            {"classes": res, "unresolved": unresolved,
             "_meta": {"tool": "tools/part_kinds.py",
                       "how": "TUFA 构造器链取回 kind 常量（伪码重建吞掉的那个）",
                       "kind_semantics": "0=原厂/stock, 1..4=Stage I..IV, 5=Unique(WB)",
                       "scanned": nfiles, "resolved": len(res)}},
            ensure_ascii=False, indent=1), encoding="utf-8")
        print("-> %s" % a.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
