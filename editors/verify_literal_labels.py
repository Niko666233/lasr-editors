"""独立复核 editors/data/literal_labels.json。

只依赖 lasr_core.tufa（字节码解析）和标准库：**不复用 gen_literal_labels 的标签抽取**，
伪码只用来数「类里有哪些方法名」（判断 JSON 的方法键是名字还是名字+描述符）。

检查项（任何一条不符都打印并计入错误，最后给出 exit code）：
  A. 每个「类 + 方法」的标签个数 == Tufa.literals(method) 个数（0 不符才算过）。
  B. 带「规则 C」标签（`X.<init>#参数N`）的条目：
     - 这些标签必须是该方法的**前导**标签，且编号连续 1..k；
     - 被调类短名必须 == 字节码里那条 invokespecial <init> 的 owner 短名；
     - k 必须 == 该 invokespecial 之前的字面量个数；
     - 第 1 个前导实参还要按「类名层级记号」独立复算一遍并与字节码字面量比对。
"""
import json
import re
import struct
import sys
from collections import Counter, OrderedDict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

from lasr_core import tufa                                  # noqa: E402

JSON_PATH = HERE / "data" / "literal_labels.json"
SNAP_ROOT = HERE / "data" / "classes"
PSEUDO_ROOT = ROOT / "out_pseudo" / "vehicles"

OP_INVOKE_SPECIAL = 0x11
STAGE_TOKENS = {"stock": 0, "I": 1, "II": 2, "III": 3, "IV": 4, "WB": 5,
                "01": 1, "02": 2, "03": 3, "04": 4, "05": 5}
PARAM_RE = re.compile(r"^[\w$]+\.<init>#参数(\d+)$")
HEAD_RE = re.compile(r"^//\s*(?P<fq>[\w.$]+)\.(?P<name>[^\s(]+)\((?P<desc>[^)]*)\)")


def snapshots():
    """data/classes 下所有车辆类快照（排除 java 全集 _java/）。"""
    for p in SNAP_ROOT.rglob("*.tufa"):
        if p.parts[len(SNAP_ROOT.parts)] == "_java":
            continue
        yield p


def load_snapshot(p):
    try:
        return tufa.Tufa(p.read_bytes())
    except Exception:                                     # noqa: BLE001
        return None


def pseudo_method_names(ppath, cls):
    """伪码头部注释里的方法名集合（只用来判断重载，不看正文）。"""
    names = Counter()
    try:
        text = ppath.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return names
    tag = "." + cls + "."
    for raw in text.splitlines():
        s = raw.strip()
        if not s.startswith("//"):
            continue
        c = s[2:].strip()
        i = c.find(tag)
        if i < 0:
            continue
        rest = c[i + len(tag):]
        j = rest.find("(")
        if j > 0:
            names[rest[:j]] += 1
    return names


def class_stage(cls):
    head, _sep, tok = cls.rpartition("_")
    return STAGE_TOKENS.get(tok) if head else None


def leading_special(t, m):
    """(前导字面量数, owner 全限定名, 描述符) —— 第一条 invokespecial <init>。"""
    if not m.prog:
        return None
    for o, op, _w, pay in m.prog:
        if op in tufa.EDITABLE_OPS:
            continue
        if op != OP_INVOKE_SPECIAL:
            continue
        r = t.pool.ref(pay) if (pay is not None and pay < t.pool.n) else None
        if not (r and r[3] == "ref" and r[1] == "<init>" and r[0]):
            continue
        n = sum(1 for o2, op2, _w2, _p2 in m.prog
                if o2 < o and op2 in tufa.EDITABLE_OPS)
        return n, r[0], (r[2] or "")


def build_arg_table():
    """(owner, desc, pos) -> {(car, body): {value: 次数}}，扫全部快照的 <init> 前导实参块。"""
    table = OrderedDict()
    for p in snapshots():
        t = load_snapshot(p)
        if t is None:
            continue
        grp = (p.parts[-3], p.parts[-2])
        for m in t.methods:
            if m.name != "<init>":
                continue
            info = leading_special(t, m)
            if not info or info[0] < 2:
                continue
            lits = t.literals(m)
            for pos in range(1, info[0]):
                cell = table.setdefault((info[1], info[2], pos), {})
                g = cell.setdefault(grp, {})
                v = lits[pos][3]
                g[v] = g.get(v, 0) + 1
    return table


def table_lookup(table, owner, desc, pos, group, min_n=3):
    """leave-one-group-out：预测某条时排除它自己所在的 car/body，其余必须众口一致。"""
    cell = table.get((owner, desc, pos))
    if not cell:
        return None
    vals = {}
    for g, cnt in cell.items():
        if g == group:
            continue
        for v, n in cnt.items():
            vals[v] = vals.get(v, 0) + n
    if len(vals) != 1:
        return None
    v, n = next(iter(vals.items()))
    return v if n >= min_n else None


def close_enough(a, b):
    tol = 1e-6 * max(1.0, abs(float(b)))
    return abs(float(a) - float(b)) <= tol or abs(float(a) + float(b)) <= tol


def main():
    data = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    sup_table = build_arg_table()
    print("跨车体常量表键数            : %d %s"
          % (len(sup_table), list(sup_table)[:3]))
    n_entries = 0
    n_labels = 0
    n_ctor_labels = 0
    k_hist = Counter()
    pred_used = Counter()
    n_ctor_entries = 0
    errors = []
    ambiguous = []
    missing_class = []
    # 类 -> 候选快照（只扫一次；排除 java 全集 _java/）
    index = {}
    for p in SNAP_ROOT.rglob("*.tufa"):
        if p.parts[len(SNAP_ROOT.parts)] == "_java":
            continue
        index.setdefault(p.stem, []).append(p)

    for ckey, meths in data.items():
        if "/" in ckey:
            car, body, cls = ckey.split("/")
            spac = SNAP_ROOT / car / body / (cls + ".tufa")
            if not spac.is_file():
                missing_class.append(ckey)
                continue
            cands = [spac]
        else:
            cls = ckey
            cands = index.get(cls, [])
            if not cands:
                missing_class.append(ckey)
                continue
            car, body = cands[0].parts[-3], cands[0].parts[-2]
        ppath = PSEUDO_ROOT / car / body / "classes" / "classes" / (cls + ".java")
        names = pseudo_method_names(ppath, cls)
        for spac in cands:
            try:
                t = tufa.Tufa(spac.read_bytes())
            except Exception as exc:                        # noqa: BLE001
                errors.append("解析失败 %s: %r" % (spac, exc))
                continue
            by_key = {}
            for m in t.methods:
                if not t.literals(m):
                    continue
                key = m.name if names.get(m.name, 0) <= 1 else "%s%s" % (m.name, m.desc)
                by_key.setdefault(key, []).append(m)
            for mkey, labs in meths.items():
                n_entries += 1
                n_labels += len(labs)
                cand = by_key.get(mkey)
                if not cand:
                    errors.append("JSON 里有但字节码里没找到: %s %s" % (ckey, mkey))
                    continue
                if len(cand) > 1:
                    ambiguous.append((ckey, mkey, len(cand)))
                    continue
                m = cand[0]
                lits = t.literals(m)
                if len(labs) != len(lits):
                    errors.append("个数不符: %s %s JSON=%d 字节码=%d"
                                  % (ckey, mkey, len(labs), len(lits)))
                    continue
                # ---- 规则 C 标签的独立复核（只针对 <init>，且必须是「编号 1..k 的同名前导段」）
                if m.name != "<init>":
                    continue
                k = 0
                for lab in labs:
                    mm = PARAM_RE.match(lab)
                    if not mm or mm.group(1) != str(k + 1):
                        break
                    if k and lab.split(".<init>")[0] != labs[0].split(".<init>")[0]:
                        break
                    k += 1
                if not k:
                    continue
                info = leading_special(t, m)
                if info is None or info[0] != k:
                    continue           # 前缀是普通伪码实参标签，不是规则 C 补的
                owner_short = info[1].split(".")[-1]
                if owner_short != labs[0].split(".<init>")[0]:
                    errors.append("被调类短名不符: %s %s 标签=%s owner=%s"
                                  % (ckey, mkey, labs[0], owner_short))
                    continue
                n_ctor_entries += 1
                n_ctor_labels += k
                k_hist[k] += 1
                st = class_stage(cls)
                v0 = lits[0][3]
                if st is None or not close_enough(st, v0):
                    errors.append("类名层级记号(%s)与第 1 个前导字面量(%s)不符: %s %s"
                                  % (st, v0, ckey, mkey))
                for i in range(1, k):
                    pred = table_lookup(sup_table, info[1], info[2], i, (car, body))
                    pred_used[(info[1], info[2], i, pred)] += 1
                    if pred is None or not close_enough(pred, lits[i][3]):
                        errors.append("第 %d 个前导实参预测(%s) != 字节码(%s): %s %s"
                                      % (i + 1, pred, lits[i][3], ckey, mkey))
    print("JSON 条目（类+方法）      : %d" % n_entries)
    print("标签总数                  : %d" % n_labels)
    print("规则 C 条目（前导标签数 k 直方图）: %d %s"
          % (n_ctor_entries, dict(sorted(k_hist.items()))))
    for k, v in pred_used.most_common(6):
        print("    跨车体预测 %-34s pos=%d -> %-5s 命中 %d 条" % (k[0], k[2], k[3], v))
    print("找不到字节码的类          : %d %s" % (len(missing_class), missing_class[:5]))
    print("方法键有歧义的条目        : %d %s" % (len(ambiguous), ambiguous[:5]))
    print("不符条目                  : %d" % len(errors))
    for e in errors[:40]:
        print("   !", e)
    return 1 if (errors or missing_class or ambiguous) else 0


if __name__ == "__main__":
    sys.exit(main())
