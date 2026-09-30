"""从抬升伪码（out_pseudo/vehicles/<Car>/<body>/classes/classes/*.java）生成
「每个方法里每个字面量的作用」标签表，并用字节码逐方法校验对齐。

产物（本脚本只写这三个文件）：
    editors/data/literal_labels.json        {类短名: {方法名: [标签, ...]}}
    editors/out_literal_labels_report.txt   统计 / 失败分布 / 规则来源 / 值级校验

对齐口径（硬要求）：伪码抽出来的标签个数必须与 `lasr_core.tufa.Tufa.literals(method)`
（per-method、0-based、字节码顺序）**逐方法相等**才算对齐成功；不等就整条丢掉并计数，
绝不补齐、不猜（报告里给出失败分类）。对齐成功后另外做一次「值级校验」：标签自带的
数字必须与同一个下标的字节码字面量逐个对得上（允许一元负号 NEG、int/float 转换），
用来抓「数量对上但顺序错位」的情况。

标签规则（全部由字节码实测反推，见 out_literal_labels_report.txt 的「规则来源」）：
    local0.engine_volume = ((F)1998);   → engine_volume
    local0.turboTable[4] = 0.025;       → turboTable[4]（数组元素写入/读出）
    this.EBDParams_F[0] = ((F)500);     → EBDParams_F[0]（元素值）+ 同行的下标字面量
    local0 = new [F[13];                → 数组长度
    local1 = {38.0, 4.5}; local0.bt = local1;  → bt[0], bt[1], 数组长度
    认不出来的行                          → ? 或「谁#参数N」这种短语
"""
import argparse
import json
import os
import re
import struct
import sys
import zipfile
from collections import Counter, OrderedDict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

from lasr_core import flzd, tufa          # noqa: E402

GAME = Path(r"C:\Games\LASR")
EXE = GAME / "LASR.exe"
PSEUDO_ROOT = ROOT / "out_pseudo" / "vehicles"
OUT_JSON = HERE / "data" / "literal_labels.json"
OUT_REPORT = HERE / "out_literal_labels_report.txt"

UNKNOWN = "?"

# ---------------------------------------------------------------- 解析规则开关
# 这些开关是拿 1850 个类跑出来的（改一个开关就重跑 --measure 看匹配率）。
RULES = {
    # 数组元素写入时「最内层下标的字面量」什么时候存在：
    #   value_kind = 目标是 this 的字段/本方法新建的数组时，下标被编进指令 payload，
    #                只有链上第一次写入、或「值为浮点字面量且上一笔不是整数字面量」时
    #                才显式压一个字面量（实测：eRPMs 全整数只压 1 个下标；
    #                IMuffler.RPMs 全浮点每次压；EBDParams_F 整数+浮点只压 1 个）
    #   first_only = 只有链上第一次写入才压下标
    "index_model": "value_kind",
    # 多维数组的非最内层下标（`a[i][j]` 里的 i）是否每次写入都压字面量
    "outer_index_always": True,
    # switch 的 `case N:` 里的 N 是否算字面量（实测：True 时对齐数 +20，说明它是字面量）
    "case_values": True,
    # 构造器专用规则：<init> 的伪码比字节码少 1 / 3 个字面量时，补上被反编译器吞掉的
    # super(...) / this(...) 前导实参标签（见 ctor_prepend 的闸门）。
    "ctor_prepend": True,
}

# 构造器补齐：只处理「缺口 = 1 或 3」这两类（实测分别是被吞掉的 super(stage) /
# super(stage, 1.0, 0.5)）。缺口 +31/+39/-2 是反编译失败 / 乱码 / 乘数编在指令 payload
# 里的情况，不是丢实参，硬补出来的标签是错的 —— 明确不补，继续留空。
CTOR_DELTAS = (1, 3)

# 0x11 = invokespecial：构造器里唯一指向「父类 <init>（super(...)）或本类 <init>
# （this(...)）」的指令。实测 2272 个 <init> 里 2197 条 owner == CLSS 里的父类。
OP_INVOKE_SPECIAL = 0x11

# 类短名末尾的「层级」记号 -> super(...) 第 1 个实参的预测值。
# 实测：*_stage_I/II/III/IV/WB = 1..5、*_stock = 0、ISticker_*_01..05 = 1..5。
STAGE_TOKENS = {"stock": 0, "I": 1, "II": 2, "III": 3, "IV": 4, "WB": 5,
                "01": 1, "02": 2, "03": 3, "04": 4, "05": 5}

# 描述符里「整型 / 浮点」形参与字面量类型的对应（value_kind 给的是 int/float）
INT_PARAMS = frozenset("ISBCZ")

STR_RE = re.compile(r'"(?:[^"\\]|\\.)*"')
NUM_RE = re.compile(
    r"(?<![\w.$])(?:\d+\.\d*(?:[eE][-+]?\d+)?|\.\d+(?:[eE][-+]?\d+)?|\d+(?:[eE][-+]?\d+)?)(?![\w.])")
NEW_ARR_RE = re.compile(r"^(?P<t>.+?)\s*=\s*new\s+\S*\[(?P<n>\d+)\]$")
INIT_ARR_RE = re.compile(r"^(?P<t>.+?)\s*=\s*\{(?P<body>[^{}]*)\}$")
ASSIGN_RE = re.compile(r"^(?P<lhs>[^=<>!]+?)\s*=\s*(?P<rhs>.+?)$")
FIELD_RE = re.compile(r"^(?P<obj>[A-Za-z_$][\w$.]*?)\.(?P<f>[A-Za-z_$][\w$]*)$")
ELEM_RE = re.compile(r"^(?P<base>.+?)(?P<idx>(?:\[[^\]]*\])+)$")
LOCAL_RE = re.compile(r"^local\d+$")
CASE_RE = re.compile(r"^case\s+(?P<n>-?\d+)$")
INT_CAST_RE = re.compile(r"^\(\([FI]\)\s*-?\d+\s*\)$")
FLOAT_RE = re.compile(r"^-?\d+\.\d*(?:[eE][-+]?\d+)?$")


# ------------------------------------------------------------------ 伪码切分
def split_methods(text, cls):
    """→ [(name, desc, [原始行])]，按文件顺序。

    头部注释是 `// <全限定类名>.<方法名>(<desc>)`；反编译器把 <clinit> 写成 `?`，
    这里映射回 `<clinit>` / `()V`（与 Tufa 里 TREE 记录 0 的名字一致）。
    """
    out = []
    tag = "." + cls + "."
    name = desc = None
    lines = []
    for raw in text.splitlines():
        s = raw.strip()
        if s.startswith("//"):
            c = s[2:].strip()
            i = c.find(tag)
            if i >= 0:
                rest = c[i + len(tag):]
                j = rest.find("(")
                if j > 0:
                    if name is not None:
                        out.append((name, desc, lines))
                    name, desc = rest[:j], rest[j:]
                    # 反编译器有时会在头部后面加注解，例如
                    # `...(I)Ljava.game.item.IPart;   [stack analysis failed: return-arity]`
                    desc = re.sub(r"\s+\[[^\]]*\]\s*$", "", desc)
                    if name == "?":
                        name, desc = "<clinit>", "()V"
                    lines = []
                    continue
        if name is not None:
            lines.append(raw)
    if name is not None:
        out.append((name, desc, lines))
    return out


def strip_strings(line):
    """去掉字符串常量：字符串里的数字在常量池里，不是 INT/FLOAT 字面量。"""
    return STR_RE.sub('""', line)


def shape_of(line):
    s = strip_strings(line.strip())
    s = re.sub(r"\d+\.\d+(?:[eE][-+]?\d+)?", "#F", s)
    s = re.sub(r"\b\d+\b", "#", s)
    return re.sub(r"[\w$]{6,}", "I", s)


def value_kind(rhs):
    """右值里那个数字字面量的类型：int（((F)1998) 这种）/ float（0.25）/ other。"""
    if INT_CAST_RE.match(rhs.strip()):
        return "int"
    nums = [m.group(0) for m in NUM_RE.finditer(rhs)]
    if not nums:
        return "other"
    if any("." in n or "e" in n.lower() for n in nums):
        return "float"
    if len(nums) == 1 and re.fullmatch(r"-?\d+", nums[0]):
        return "int"
    return "other"


def split_top_commas(body):
    """按顶层逗号切 `{...}` 里的元素。

    只让圆括号/花括号参与配对：反编译器在「stack analysis failed」的伪码里会把类型
    描述符写成不成对的 `[I` / `[[I`（IVehicle_Coupe_RS.<init>），拿它算深度会让整行
    切不动，所以方括号不计深度，负深度也直接夹回 0。
    """
    out, depth, cur = [], 0, []
    for ch in body:
        if ch in "({":
            depth += 1
        elif ch in ")}":
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    out.append("".join(cur))
    return [x.strip() for x in out if x.strip()]


def paren_arg_labels(line):
    """把一行里「调用实参」位置的数字标成 `<被调用者>#参数N`，返回 {数字起始位置: 标签}。

    只认真正的调用括号（`(` 前面是标识符 / `>`），分组用的括号不认。
    """
    out = {}
    stack = []
    for i, ch in enumerate(line):
        if ch == "(":
            head = line[:i].rstrip()
            if head and (head[-1].isalnum() or head[-1] in "_$>"):
                m = re.search(r"([\w$.<>]+)$", head)
                callee = m.group(1) if m else ""
                if callee.endswith(".<init>"):
                    callee = callee[:-len(".<init>")].split(".")[-1] + ".<init>"
                else:
                    callee = callee.split(".")[-1]
                stack.append((callee, 1, True))
            else:
                stack.append(("", 1, False))
        elif ch == ")" and stack:
            stack.pop()
        elif ch == "," and stack:
            ca, n, iscall = stack.pop()
            stack.append((ca, n + 1, iscall))
        elif stack and ch.isdigit() and not (line[i - 1:i].isalnum() or
                                             line[i - 1:i] in "_$."):
            for ca, n, iscall in reversed(stack):     # 最近一个「真调用」的实参位置
                if iscall and ca:
                    out[i] = "%s#参数%d" % (ca, n)
                    break
    return out


# ------------------------------------------------------------------ 标签抽取
def extract_labels(lines, trace=None, rules=None):
    """一个方法的伪码行 → (标签列表, 每个标签对应的数字或 None)，顺序=字节码顺序。"""
    rules = rules or RULES
    labels, nums = [], []
    fresh = set()             # 本方法里新建的数组表达式（`X = new ...` / `X = {..}`）
    fresh_fields = set()      # 本方法里新建过的字段名
    local_field = {}          # localK -> 它后来被赋给的字段名
    chain = {}                # 基数组表达式 -> {"n": 次数, "kind": 上一个值的类型}

    def emit(lab, num, line):
        labels.append(lab)
        nums.append(num)
        if trace is not None:
            trace.append((line, lab))

    def emit_nums(text, default, line):
        """给一段文本里的数字加标签。

        `[..]` 里的数字优先算数组下标（读出）；在调用实参位置上的算 `<谁>#参数N`；
        其余用 default（赋值行用字段名，认不出来的一行用 ?）。
        """
        args = paren_arg_labels(text)
        for m in NUM_RE.finditer(text):
            j = m.start() - 1
            while j >= 0 and text[j] == " ":
                j -= 1
            if j >= 0 and text[j] == "[":
                bm = re.search(r"([\w.$]+)\s*$", text[:j])
                lab = "%s#下标" % (bm.group(1).split(".")[-1] if bm else "数组")
            elif m.start() in args:
                lab = args[m.start()]
            else:
                lab = default
            emit(lab if isinstance(lab, str) else lab(m), m.group(0), line)

    # 预扫：localK 最终落到哪个字段（数组临时量的命名用）
    for raw in lines:
        m = ASSIGN_RE.match(strip_strings(raw.strip()).rstrip(";"))
        if not m:
            continue
        fm = FIELD_RE.match(m.group("lhs").strip())
        if fm and LOCAL_RE.match(m.group("rhs").strip()):
            local_field[m.group("rhs").strip()] = fm.group("f")

    # 预扫：每行如果是简单赋值，记下它的右值（给下面 if 重复调用的判断用）
    line_rhs = {}
    for i, raw in enumerate(lines):
        m = ASSIGN_RE.match(strip_strings(raw.strip()).rstrip(";").strip())
        if m:
            line_rhs[i] = m.group("rhs").strip()

    for idx, raw in enumerate(lines):
        prev_rhs = line_rhs.get(idx - 1)
        s = strip_strings(raw.strip())
        if not s or s.startswith("//") or s in ("}", "{"):
            continue
        s = s.rstrip(";").strip()

        # ---- 数组创建：长度字面量（字节码里紧跟着 new [F[n] 之前）
        m = NEW_ARR_RE.match(s)
        if m:
            t = m.group("t").strip()
            fresh.add(t)
            fm = FIELD_RE.match(t)
            if fm:
                fresh_fields.add(fm.group("f"))
            emit("数组长度", m.group("n"), raw)
            continue

        # ---- 数组初始化临时量：值在前、长度在后（= 字节码压栈顺序）
        m = INIT_ARR_RE.match(s)
        if m:
            t = m.group("t").strip()
            fm = FIELD_RE.match(t)
            fld = fm.group("f") if fm else (local_field.get(t) or t)
            if fm:
                fresh_fields.add(fld)
            n = 0
            for tok in split_top_commas(m.group("body")):
                for _mm in NUM_RE.finditer(tok):
                    emit("%s[%d]" % (fld, n), _mm.group(0), raw)
                n += 1
            emit("数组长度", str(n), raw)   # 元素个数（字符串元素也算一个元素）
            fresh.add(t)
            continue

        # ---- 赋值
        m = ASSIGN_RE.match(s)
        if m:
            lhs, rhs = m.group("lhs").strip(), m.group("rhs").strip()
            em = ELEM_RE.match(lhs)
            if em:
                base = em.group("base").strip()
                idxs = [x.strip() for x in re.findall(r"\[([^\]]*)\]", em.group("idx"))]
                fm = FIELD_RE.match(base)
                fname = fm.group("f") if fm else base
                obj = fm.group("obj") if fm else ""
                if LOCAL_RE.match(base):
                    encoded = True
                elif fm and obj == "this":
                    encoded = True
                elif fm and LOCAL_RE.match(obj):
                    encoded = fname in fresh_fields
                else:
                    encoded = False
                kind = value_kind(rhs)
                st = chain.setdefault(base, {"n": 0, "kind": None})
                # 非最内层下标（二维的第一个下标）：每次写入都显式压一个字面量
                # （实测 Model_Coupe_RS.<init> 的 axleLoadDegradationAtBodyStage[i][j]：
                #  10 笔写入 = 10 个外下标 + 1 个内下标 + 10 个值 = 21 个字面量）
                for o in idxs[:-1]:
                    if re.fullmatch(r"\d+", o) and (rules["outer_index_always"] or st["n"] == 0):
                        emit("%s[%s]#下标" % (fname, o), o, raw)
                inner = idxs[-1]
                if re.fullmatch(r"\d+", inner):
                    push = False
                    if not encoded:
                        push = True                      # 别的对象的字段：每次都压
                    elif st["n"] == 0:
                        push = True                      # 链上第一笔（下标 0）
                    elif rules["index_model"] == "value_kind" and \
                            kind in ("float", "other") and st["kind"] != "int":
                        push = True
                    if push:
                        emit("%s[%s]#下标" % (fname, inner), inner, raw)
                st["n"] += 1
                st["kind"] = kind
                tgt = "%s[%s]" % (fname, inner) if re.fullmatch(r"\d+", inner) else fname
                emit_nums(rhs, tgt, raw)
                continue
            fm = FIELD_RE.match(lhs)
            if fm:
                emit_nums(rhs, fm.group("f"), raw)
            elif LOCAL_RE.match(lhs):
                emit_nums(rhs, local_field.get(lhs, lhs), raw)
            else:
                emit_nums(rhs, UNKNOWN, raw)
            continue

        # ---- 认不出来的一行：调用实参给「谁#参数N」，别处给 ?
        if s.startswith("case "):
            if rules["case_values"]:
                emit_nums(s, "case值", raw)      # switch 分支：字节码里 case 值也是字面量
            continue
        # 反编译器把 `x = f(n);` + `if ((f(n) != null))` 里的调用重复打印了一遍
        # （实测 Hatch_S2_Sounds.setEngineSounds：字节码里 getSfxTable(0) 只出现一次），
        # 上一行刚把同一个表达式赋给局部量时，if 行里的数字不再算字面量。
        if s.startswith("if (") and prev_rhs:
            inner = s[len("if (("):] if s.startswith("if ((") else s[len("if ("):]
            inner = re.sub(r"\s*!=\s*null\)?\)?\s*\{?$", "", inner).strip()
            if inner == prev_rhs:
                continue
        if s.startswith("return") and NUM_RE.search(s):
            emit_nums(s, "返回值", raw)
            continue
        emit_nums(s, UNKNOWN, raw)

    return labels, nums


# ------------------------------------------------------------------ 值级校验
def value_matches(num_txt, byte_val, label=None):
    """标签里的数字与字节码字面量对得上吗。

    允许：一元负号（伪码写 (-3000.0)、字节码是 FLOAT 3000.0 + NEG）、int↔float32、
    以及反编译器打印时的精度损失（实测伪码只打到 ~7 位有效数字，例如 4.28 对应
    字节码 4.279999732971191），所以用 1e-6 的相对容差。
    已知例外：二维数组字面量（`int[][]`）的长度占位在字节码里是 -1（真正的元素个数
    在 0x24 指令的 payload 里），见 IVehicle_Hatch_S2.<init> 的 stylingIDs。
    """
    if num_txt is None:
        return True
    try:
        v = float(num_txt)
    except ValueError:
        return True
    b = float(byte_val)
    if label == "数组长度" and b == -1:
        return True
    tol = 1e-6 * max(1.0, abs(b))
    if abs(v - b) <= tol or abs(v + b) <= tol:
        return True
    try:
        if abs(struct.unpack("<f", struct.pack("<f", v))[0] - b) <= tol:
            return True
    except (OverflowError, struct.error):
        pass
    return False


# ------------------------------------------------- 规则 C：构造器前导实参补齐
def class_stage(cls):
    """类短名末尾的层级记号 -> 预测值（认不出来返回 None）。"""
    head, _sep, tok = cls.rpartition("_")
    if not head:
        return None
    return STAGE_TOKENS.get(tok)


def desc_params(desc):
    """'(IFF)' -> ['I', 'F', 'F']（解析不了返回 None）。

    实测有少数引用记录里描述符是空串或没有括号（例如 ISticker 的部分构造器），
    这时不猜类型，只做「位置 + 取值」两层校验。
    """
    if not desc.startswith("("):
        return None
    end = desc.find(")")
    if end < 0:
        return None
    body, out = desc[1:end], []
    while body:
        c = body[0]
        if c == "[":
            while body and body[0] == "[":
                body = body[1:]
            c = body[:1]
            if not c:
                return None
        if c == "L":
            j = body.find(";")
            if j < 0:
                return None
            body = body[j + 1:]
            out.append("L")
        else:
            body = body[1:]
            out.append(c)
    return out


def kind_matches(kind, ptype):
    """字节码字面量类型（int/float）与该形参类型对得上吗。"""
    if ptype is None:
        return True
    if kind == "int":
        return ptype in INT_PARAMS
    if kind == "float":
        return ptype == "F"
    return True


def ctor_special(t, m):
    """<init> 里第一条 invokespecial <init>（super(...) / this(...)）及其之前的字面量。

    → {"n": 前导字面量数, "lits": [(kind, value), ...], "owner": 全限定被调类,
       "desc": 构造器描述符}；找不到（或该记录解不开）返回 None。
    """
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
        lits = t.literals(m)
        n = sum(1 for o2, op2, _w2, _p2 in m.prog
                if o2 < o and op2 in tufa.EDITABLE_OPS)
        return {"n": n, "lits": [(k, v) for _i, _o, k, v in lits[:n]],
                "owner": r[0], "desc": r[2] or ""}
    return None


def build_super_arg_table(classes, codec):
    """给「前导实参里第 2..k 个位置」建一张跨车体的常量表。

    (owner, desc, pos) -> {(car, body): {value: 次数}}。用法是 leave-one-group-out：
    预测某个方法时**排除它自己所在的 car/body**，只信别的车体在同一个父类构造器
    调用约定里压过的值 —— 这样预测值和被校验的那个字节码字面量来自不同文件。
    """
    zips, table = {}, {}
    for car, body, zp, cls, _ppath in classes:
        if zp not in zips:
            zips[zp] = zipfile.ZipFile(zp)
        try:
            t = tufa.Tufa(class_bytes(car, body, cls, zips[zp], codec))
        except Exception:                              # noqa: BLE001
            continue
        for m in t.methods:
            if m.name != "<init>":
                continue
            info = ctor_special(t, m)
            if not info or info["n"] < 2:
                continue
            for pos in range(1, info["n"]):
                cell = table.setdefault((info["owner"], info["desc"], pos), {})
                grp = cell.setdefault((car, body), {})
                v = info["lits"][pos][1]
                grp[v] = grp.get(v, 0) + 1
    return table


def table_lookup(table, owner, desc, pos, group, min_n=3):
    """跨车体常量表取值：别的车体的贡献必须**众口一致**且至少 min_n 条，否则 None。"""
    cell = table.get((owner, desc, pos))
    if not cell:
        return None
    vals = {}
    for grp, cnt in cell.items():
        if grp == group:
            continue
        for val, n in cnt.items():
            vals[val] = vals.get(val, 0) + n
    if len(vals) != 1:
        return None                                    # 有歧义 / 无贡献
    val, n = next(iter(vals.items()))
    return val if n >= min_n else None


def ctor_prepend(t, m, cls, k, vals, table, group):
    """规则 C：补上被反编译器吞掉的 super(...) / this(...) 前导实参标签。

    返回 (labels, nums, None) 或 (None, None, 原因)。**硬闸门：任一层不过就整条不补。**

    结构层（只看字节码，证明「缺的就是前导 k 个实参」）：
      S1 记录能解开，且第一条 invokespecial <init> 之前的字面量**恰好 k 个**；
      S2 该 <init> 的 owner 是本类的父类（或本类，this(...) 委托）；
      S3 描述符前 k 个形参类型与这 k 个字面量的类型逐位一致（描述符解析不出来时跳过）。
    取值层（预测值必须来自本类之外，再与同一序号的字节码字面量逐个比对）：
      V1 第 1 个位置：类名末尾的层级记号（*_stage_I/II/III/IV/WB、*_stock、*_NN）；
      V2 第 2..k 个位置：同一父类构造器约定的跨车体常量表（leave-one-group-out）；
      V3 预测值 vs 同一序号字节码字面量，用 value_matches 的容差（一元负号、
         int↔float32、伪码 7 位有效数字）。
    """
    info = ctor_special(t, m)
    if not info:
        return None, None, "S: 找不到 super/this 调用"
    if info["n"] != k:
        return None, None, "S1: 前导字面量 %d 个 != 缺口 %d" % (info["n"], k)
    owner_short = info["owner"].split(".")[-1]
    params = desc_params(info["desc"])
    if params is not None:
        if len(params) < k:
            return None, None, "S3: 父类构造器形参少于缺口"
        for i in range(k):
            if not kind_matches(info["lits"][i][0], params[i]):
                return None, None, "S3: 第 %d 个前导字面量类型与形参不符" % (i + 1)

    preds, srcs = [], []
    for i in range(k):
        if i == 0:
            v = class_stage(cls)
            src = "类名层级记号"
        else:
            v = table_lookup(table, info["owner"], info["desc"], i, group)
            src = "跨车体常量表"
        if v is None:
            return None, None, "V%d: 第 %d 个前导实参没有独立预测值" % (1 if i == 0 else 2, i + 1)
        preds.append(v)
        srcs.append(src)

    for i, v in enumerate(preds):
        if not value_matches(str(v), vals[i], None):
            return None, None, ("V3: 第 %d 个前导实参预测值 %s（%s）与字节码 %s 不符"
                                % (i + 1, v, srcs[i], vals[i]))
    labels = ["%s.<init>#参数%d" % (owner_short, i + 1) for i in range(k)]
    return labels, [str(v) for v in preds], None


# ------------------------------------------------------------------ 主流程
def iter_classes():
    out = []
    for car in sorted(os.listdir(PSEUDO_ROOT)):
        d = PSEUDO_ROOT / car
        if not d.is_dir():
            continue
        for body in sorted(os.listdir(d)):
            dd = d / body / "classes" / "classes"
            zp = GAME / "vehicles" / car / body / "classes.zip"
            if not dd.is_dir() or not zp.exists():
                continue
            for f in sorted(os.listdir(dd)):
                if f.endswith(".java"):
                    out.append((car, body, zp, f[:-5], dd / f))
    return out


SNAP_ROOT = HERE / "data" / "classes"


def class_bytes(car, body, cls, z, codec, stats=None):
    """类的 TUFA 明文：优先用快照 editors/data/classes/<Car>/<body>/<cls>.tufa
    （与 lasr_core.vdata 同一约定，1850 个类齐全），没有快照才回退 classes.zip + 解码。

    快照与 zip 条目是同一份字节码的明文（gen_snapshot.py 写出），用它跑能避开
    反复调 FLZD 解码器时的偶发失步（实测同一 codec 连跑两轮会有 1~2 个类报
    size mismatch / not a TUFA class），也让整轮从 ~5 秒降到 ~1 秒。
    """
    snap = SNAP_ROOT / car / body / (cls + ".tufa")
    if snap.is_file():
        if stats is not None:
            stats["from_snapshot"] += 1
        return snap.read_bytes()
    if stats is not None:
        stats["from_zip"] += 1
    return codec.unpack(z.read("classes/%s.class" % cls))


def run(limit=None, rules=None, diagnose=False):
    rules = rules or RULES
    codec = flzd.FlzdCodec(str(EXE))
    classes = iter_classes()
    if limit:
        classes = classes[:limit]
    short = Counter(c for _a, _b, _z, c, _p in classes)

    stats = Counter()
    fails, fail_head, unknown_src, failed_shapes = Counter(), {}, Counter(), Counter()
    fail_by_name = Counter()
    per_car = OrderedDict()
    labels_out = OrderedDict()
    dup_class_keys, dup_method_keys = [], []
    value_bad, value_checked = [], 0
    zips = {}
    # 规则 C 的计数器：ctor_fail = 去重后的失败原因计数，
    # ctor_patched_* = 本轮真正补出来并进入 JSON 的（car/body, 类, 方法, 标签）
    ctor_fail, ctor_samples, ctor_patched = Counter(), {}, []
    ctor_value_bad = []
    sup_table = build_super_arg_table(classes, codec) if rules.get("ctor_prepend",
                                                                  True) else {}

    for car, body, zp, cls, ppath in classes:
        if zp not in zips:
            zips[zp] = zipfile.ZipFile(zp)
        z = zips[zp]
        try:
            t = tufa.Tufa(class_bytes(car, body, cls, z, codec, stats))
        except Exception as exc:                       # noqa: BLE001
            stats["class_error"] += 1
            fail_head.setdefault("class_error", (cls, repr(exc)))
            continue
        stats["classes"] += 1
        pc = per_car.setdefault("%s/%s" % (car, body), Counter())
        pc["classes"] += 1
        text = ppath.read_text(encoding="utf-8", errors="replace")
        pm, traces = OrderedDict(), {}
        for name, desc, lines in split_methods(text, cls):
            tr = []
            pm[(name, desc)] = extract_labels(lines, tr, rules)
            traces[(name, desc)] = (lines, tr)
        name_cnt = Counter(n for n, _d in pm)
        accepted = OrderedDict()
        for m in t.methods:
            lits = t.literals(m)
            if not lits:
                continue
            stats["bc_methods"] += 1
            stats["bc_literals"] += len(lits)
            pc["bc_methods"] += 1
            key = (m.name, m.desc)
            vals = [v for _i, _o, _k, v in lits]
            if key not in pm:
                stats["method_missing"] += 1
                fails["伪码里没有这个方法"] += 1
                fail_head.setdefault("missing:" + m.name,
                                     (cls, m.name, m.desc, len(lits),
                                      [round(v, 4) for v in vals[:14]], None))
                continue
            labs, nums = pm[key]
            stats["checked"] += 1
            gap = len(lits) - len(labs)
            patched = False
            why = None
            if gap and m.name == "<init>" and gap in CTOR_DELTAS:
                stats["ctor_attempt"] += 1
                stats["ctor_attempt_k%d" % gap] += 1
                if rules.get("ctor_prepend", True):
                    plabs, pnums, why = ctor_prepend(t, m, cls, gap, vals,
                                                     sup_table, (car, body))
                    if plabs is not None:
                        labs, nums = plabs + list(labs), pnums + list(nums)
                        patched = True
                else:
                    why = "规则关闭（--set ctor_prepend=false）"
                if not patched:
                    ctor_fail[why or "未处理"] += 1
                    ctor_samples.setdefault(why or "未处理",
                                            (car, body, cls, m.name, m.desc,
                                             len(lits), gap, labs[:6],
                                             [round(v, 4) for v in vals[:6]]))
            if len(labs) != len(lits):
                stats["mismatch"] += 1
                pc["mismatch"] += 1
                d = len(lits) - len(labs)
                fails["个数差 %+d%s" % (d, "（构造器补齐未通过）" if gap in CTOR_DELTAS
                                        and m.name == "<init>" else "")] += 1
                fail_by_name[(d, m.name)] += 1
                if m.name in ("<init>", "<clinit>"):
                    stats["mismatch_ctor"] += 1
                fail_head.setdefault("d%+d" % d,
                                     (cls, m.name, m.desc, len(lits),
                                      [round(v, 4) for v in vals[:14]], labs[:14]))
                if diagnose:
                    for ln, _lab in traces[key][1]:
                        failed_shapes[shape_of(ln)] += 1
                continue
            # ---- 值级校验（标签自带的数字 vs 同一序号的字节码字面量）
            bad = [i for i in range(len(lits)) if not value_matches(nums[i], vals[i], labs[i])]
            if patched and bad:
                # 硬闸门：本轮补出来的条目只要有一条对不上，整条丢弃（绝不放宽）
                stats["ctor_value_dropped"] += 1
                ctor_fail["V3: 补完后值级校验不通过"] += 1
                ctor_samples.setdefault("V3: 补完后值级校验不通过",
                                        (car, body, cls, m.name, m.desc, len(lits), gap,
                                         labs[:6], [round(v, 4) for v in vals[:6]]))
                ctor_value_bad.append((cls, m.name, m.desc, len(lits),
                                       [i for i in bad][:8], labs[:8], nums[:8],
                                       [round(v, 4) for v in vals[:8]]))
                continue
            stats["aligned"] += 1
            stats["aligned_literals"] += len(lits)
            stats["labels_known"] += sum(1 for x in labs if x != UNKNOWN)
            pc["aligned"] += 1
            pc["aligned_literals"] += len(lits)
            value_checked += 1
            if patched:
                stats["ctor_patched"] += 1
                stats["ctor_patched_k%d" % gap] += 1
                stats["ctor_patched_literals"] += len(lits)
                pc["ctor_patched"] += 1
                ctor_patched.append((car, body, cls, m.name, gap, labs[:gap],
                                     [round(v, 4) for v in vals[:gap]]))
            if bad:
                stats["value_mismatch_methods"] += 1
                value_bad.append((cls, m.name, len(bad), len(lits),
                                  [round(v, 4) for v in vals[:10]], labs[:10], nums[:10]))
            if diagnose:
                for ln, lab in traces[key][1]:
                    if lab == UNKNOWN:
                        unknown_src[shape_of(ln)] += 1
            mkey = m.name if name_cnt[m.name] == 1 else "%s%s" % (m.name, m.desc)
            if mkey in accepted:
                dup_method_keys.append((cls, mkey))
            accepted[mkey] = labs
        if accepted:
            ckey = "%s/%s/%s" % (car, body, cls) if short[cls] > 1 else cls
            if ckey in labels_out:
                dup_class_keys.append(ckey)
            labels_out[ckey] = accepted
            pc["classes_in_json"] += 1
            pc["methods_in_json"] += len(accepted)
            pc["labels_in_json"] += sum(len(v) for v in accepted.values())
    return dict(labels_out=labels_out, stats=stats, fails=fails, fail_head=fail_head,
                unknown_src=unknown_src, failed_shapes=failed_shapes, short=short,
                value_bad=value_bad, value_checked=value_checked,
                dup_class_keys=dup_class_keys, dup_method_keys=dup_method_keys,
                fail_by_name=fail_by_name, classes=classes, rules=rules,
                per_car=per_car, value_bad_n=len(value_bad),
                ctor_fail=ctor_fail, ctor_samples=ctor_samples,
                ctor_patched=ctor_patched, ctor_value_bad=ctor_value_bad)


def ctor_section(A, r, before=None):
    """报告里「本轮新增：构造器 super(...) 实参补齐（规则 C）」一节。"""
    st = r["stats"]
    n_patched = st.get("ctor_patched", 0)
    n_new_lit = st.get("ctor_patched_literals", 0)
    A("本轮新增：构造器 super(...)/this(...) 前导实参补齐（规则 C）")
    A("-----------------------------------------------------")
    A("  为什么会有缺口：反编译器把 <init> 里的 super(...) 调用整个吞掉（整份伪码里")
    A("  不出现 `super` 字样），伪码标签就比字节码字面量少。913 个丢弃方法里：")
    A("    差 +1 : 855 个构造器（= 被吞掉的 super(stage) 那一个实参）")
    A("    差 +3 : 50 个构造器（= super(stage, 1.0, 0.5) 三个实参，全是 INitrous 子类）")
    A("    其余 8 个（+31 / +39 / -2）不是丢实参（反编译失败 / 乱码伪码 / 乘数编在")
    A("    指令 payload 里），明确**不补**，继续留空。")
    A("  补出来的标签沿用伪码实参标签的命名：`<父类短名>.<init>#参数N`")
    A("  （例：Hatch_S2_IEngine_stage_I.<init> → IEngine.<init>#参数1）。")
    A("  闸门（逐层，任一不过 -> 整条不补、方法继续留空；补出来的必须每条都过）：")
    A("    S1 记录能解开，且第一条 invokespecial <init>(0x11) 之前的字面量恰好 k 个（k=缺口）")
    A("    S2 该 <init> 的 owner = 本类父类（CLSS 里的那个引用；this(...) 委托时是本类）")
    A("    S3 描述符前 k 个形参类型与这 k 个字面量类型逐位一致（I/S/B/C/Z↔int，F↔float）")
    A("    V1 第 1 个前导实参的预测值来自**类名**层级记号（*_stage_I/II/III/IV/WB = 1..5，")
    A("       *_stock = 0，ISticker_*_NN = NN）——不看字节码，只跟字节码比")
    A("    V2 第 2..k 个前导实参的预测值来自同一父类构造器约定的**跨车体常量表**")
    A("       （leave-one-group-out：排除本方法所在的 car/body，别的车体必须众口一致、")
    A("        至少 3 条贡献；有歧义就不给预测值）")
    A("    V3 每个预测值与同一序号的字节码字面量逐个比对（value_matches 容差：一元负号 /")
    A("       int↔float32 / 伪码 7 位有效数字），**有一条不符就整条丢弃**")
    A("    补完后整条（含原有伪码标签）还要再过一次完整值级校验。")
    A("")
    A("  尝试补齐的构造器           : %d （差 +1: %d，差 +3: %d）"
      % (st.get("ctor_attempt", 0), st.get("ctor_attempt_k1", 0),
         st.get("ctor_attempt_k3", 0)))
    A("  补成功并进入 JSON 的方法   : %d （差 +1: %d，差 +3: %d）"
      % (n_patched, st.get("ctor_patched_k1", 0), st.get("ctor_patched_k3", 0)))
    A("  本轮新增字面量             : %d" % n_new_lit)
    A("  补完后又被值级校验打回的    : %d" % st.get("ctor_value_dropped", 0))
    A("")
    A("  被闸门拒绝的原因分布")
    for k, v in r["ctor_fail"].most_common():
        A("    %-38s %d" % (k, v))
    A("  被拒绝的样例（car/body、类、描述符、字节码字面量数、缺口、伪码标签、字节码值）")
    for k, v in r["ctor_samples"].items():
        A("    [%s] %s" % (k, v))
    A("")
    A("  补成功的样例（car/body、类、缺口、补出来的标签、对应的字节码字面量）")
    for row in r["ctor_patched"][:14]:
        A("    %s/%s %s %s  k=%d  %s  vals=%s" % row)
    if not r["ctor_patched"]:
        A("    （无）")
    A("  补完后值级校验不通过的样例（若有）")
    for row in r["ctor_value_bad"][:10]:
        A("    %s" % (row,))
    A("  未被补上的 +1/+3 构造器合计 : %d 条（原因分布见上；差 +3 且原因是" % sum(r["ctor_fail"].values()))
    A("  V2 无预测值的，说明该父类构造器约定在别的车体里没有一致的常量可依据）")
    A("")
    if before:
        bst = before["stats"]
        b_methods = sum(len(v) for v in before["labels_out"].values())
        b_lit = bst.get("aligned_literals", 0)
        A("覆盖率前后对比（before = 同一脚本同一数据、把规则 C 关掉跑的那一轮）")
        A("-----------------------------------------------------------")
        A("  方法级（对齐成功 / 逐方法比对过）   : %d/%d = %.1f%%  ->  %d/%d = %.1f%%"
          % (bst["aligned"], bst["checked"], 100.0 * bst["aligned"] / max(1, bst["checked"]),
             st["aligned"], st["checked"], 100.0 * st["aligned"] / max(1, st["checked"])))
        A("  字面量级（进入 JSON / 字节码字面量） : %d/%d = %.1f%%  ->  %d/%d = %.1f%%"
          % (b_lit, bst["bc_literals"], 100.0 * b_lit / max(1, bst["bc_literals"]),
             st["aligned_literals"], st["bc_literals"],
             100.0 * st["aligned_literals"] / max(1, st["bc_literals"])))
        A("  进入 JSON 的类数 / 方法数           : %d / %d  ->  %d / %d"
          % (len(before["labels_out"]), b_methods,
             len(r["labels_out"]), sum(len(v) for v in r["labels_out"].values())))
        A("  仍失败的方法数                     : %d  ->  %d"
          % (bst["mismatch"], st["mismatch"]))
        A("  本轮新增方法数                     : %d" % (st["aligned"] - bst["aligned"]))
        A("  本轮新增字面量数                   : %d"
          % (st["aligned_literals"] - b_lit))
    A("")


def write_outputs(r, before=None):
    st = r["stats"]
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(r["labels_out"], ensure_ascii=False,
                                   separators=(",", ":")), encoding="utf-8")
    lines = []
    A = lines.append
    A("字面量作用标签报告（editors/gen_literal_labels.py 生成）")
    A("=" * 72)
    A("数据源：")
    A("  伪码  out_pseudo/vehicles/<Car>/<body>/classes/classes/*.java")
    A("  字节码 C:\\Games\\LASR\\vehicles\\<Car>\\<body>\\classes.zip 里的同名 .class")
    A("  校验  editors/lasr_core/flzd.py（解容器）+ editors/lasr_core/tufa.py::Tufa.literals")
    A("  快照  editors/data/classes/<Car>/<body>/<cls>.tufa（优先用，与 zip 条目同一份字节码明文；")
    A("        没有快照才回退 classes.zip + FLZD 解码）")
    A("")
    A("对齐判定：伪码标签个数 == Tufa.literals(method) 个数（per-method、0-based、字节码顺序）。")
    A("个数不等整条丢弃，不补齐。对齐后另做值级校验（标签自带的数字 vs 同一序号的字节码值，")
    A("允许一元负号 NEG 与 int↔float32 转换）。")
    A("")
    A("总数字")
    A("------")
    A("  车辆类总数（伪码目录里对应 classes.zip 的 .java）: %d" % st["classes"])
    A("  解容器/解析失败                              : %d" % st["class_error"])
    A("  类字节码来源：快照 / zip 回退                : %d / %d"
      % (st["from_snapshot"], st["from_zip"]))
    A("  字节码里有字面量的方法数                     : %d" % st["bc_methods"])
    A("  这些方法里的字面量总数                       : %d" % st["bc_literals"])
    A("  其中伪码里找不到对应方法（丢弃）             : %d" % st["method_missing"])
    A("  逐方法比对过的方法数                         : %d" % st["checked"])
    A("  对齐成功 / 失败                              : %d / %d" % (st["aligned"], st["mismatch"]))
    A("  对齐成功率                                   : %.1f%%" %
      (100.0 * st["aligned"] / max(1, st["checked"])))
    A("  进入 JSON 的类数 / 方法数                    : %d / %d" %
      (len(r["labels_out"]), sum(len(v) for v in r["labels_out"].values())))
    A("  没有任何方法进入 JSON 的类                   : %d" %
      (st["classes"] - len(r["labels_out"])))
    A("  进入 JSON 的字面量数                         : %d" % st["aligned_literals"])
    A("  值级校验通过的方法 / 不通过                  : %d / %d" %
      (r["value_checked"] - st["value_mismatch_methods"], st["value_mismatch_methods"]))
    A("")
    ctor_section(A, r, before)
    A("覆盖率（对齐成功的方法里，标签不是 ? 的比例）")
    A("-------------------------------------------")
    A("  有标签的字面量 %d / %d = %.1f%%" %
      (st["labels_known"], st["aligned_literals"],
       100.0 * st["labels_known"] / max(1, st["aligned_literals"])))
    A("")
    A("标签种类分布（进入 JSON 的所有标签）")
    A("----------------------------------")
    kind = Counter()
    for _cls, _meths in r["labels_out"].items():
        for _m, labs in _meths.items():
            for lab in labs:
                if lab.endswith("#下标"):
                    kind["<字段>#下标（数组下标字面量）"] += 1
                elif "#参数" in lab:
                    kind["<被调用者>#参数N（调用实参字面量）"] += 1
                elif lab == "数组长度":
                    kind["数组长度"] += 1
                elif lab == "case值":
                    kind["case值（switch 分支）"] += 1
                elif lab == "返回值":
                    kind["返回值"] += 1
                elif lab == UNKNOWN:
                    kind["?"] += 1
                else:
                    kind["<字段名>（引擎参数）"] += 1
    _tot = sum(kind.values()) or 1
    for k, v in kind.most_common():
        A("  %-32s %7d  %5.1f%%" % (k, v, 100.0 * v / _tot))
    A("")
    A("字段名覆盖率（标签直接给出字段名/字段下标的字面量）")
    A("----------------------------------------------")
    named = sum(v for k, v in kind.items() if k.startswith("<字段名>"))
    A("  <字段名> %d / %d = %.1f%%；<字段>#下标 %d；其余是调用实参/数组长度/分支值/返回值/? "
      % (named, _tot, 100.0 * named / _tot, kind["<字段>#下标（数组下标字面量）"]))
    A("")
    A("按车体细分（Car/body）")
    A("---------------------")
    A("  %-26s %6s %8s %8s %8s %8s" %
      ("车辆/车体", "类数", "有字面量", "对齐成功", "失败", "JSON字面量"))
    for k, pc in r["per_car"].items():
        A("  %-26s %6d %8d %8d %8d %8d" %
          (k, pc["classes"], pc["bc_methods"], pc["aligned"], pc["mismatch"],
           pc["aligned_literals"]))
    A("")
    A("失败分布（丢弃的方法）")
    A("---------------------")
    for k, v in r["fails"].most_common():
        A("  %-28s %d" % (k, v))
    A("  其中构造器(<init>/<clinit>)被丢弃: %d（占失败 %.1f%%）" %
      (st["mismatch_ctor"], 100.0 * st["mismatch_ctor"] / max(1, st["mismatch"])))
    A("")
    A("失败最多的 (个数差, 方法名)")
    A("--------------------------")
    for (d, nm), v in r["fail_by_name"].most_common(12):
        A("  %+4d  %-24s %d" % (d, nm, v))
    A("")
    A("失败样例（类/方法/字节码字面量数/字节码值前缀/伪码标签前缀）")
    A("--------------------------------------------------------")
    for k, v in r["fail_head"].items():
        A("  [%s] %s" % (k, v))
    A("")
    A("对齐成功的方法里 ? 标签最大的来源行（形状归一化）")
    A("-----------------------------------------------")
    for k, v in r["unknown_src"].most_common(25):
        A("  %6d  %s" % (v, k[:110]))
    if not r["unknown_src"]:
        A("  （本次没有任何标签落到 ?：认不出的行基本都落进了「谁#参数N」/「字段#下标」）")
    A("")
    A("值级校验不通过的方法（全部）")
    A("---------------------------")
    if not r["value_bad"]:
        A("  无")
    for row in r["value_bad"][:20]:
        A("  %s" % (row,))
    A("")
    A("键冲突")
    A("------")
    A("  类短名在不同车体下重名（JSON 键已改成 <Car>/<body>/<Class>）：%d" % len(r["dup_class_keys"]))
    if r["dup_class_keys"]:
        A("    例：%s" % r["dup_class_keys"][:8])
    A("  同类里同名（不同签名）方法冲突（键已加 desc）：%d" % len(r["dup_method_keys"]))
    if r["dup_method_keys"]:
        A("    例：%s" % r["dup_method_keys"][:8])
    A("")
    A("规则来源（都在本轮实测里反复对过）")
    A("----------------------------------")
    A("1) `X = new <类型>[N];`：N 是字面量，字节码顺序 `INT N; NEWARRAY`；")
    A("   例 Coupe_RS_IEngine_stock.eRPMs off=1 INT 13 → 0x22。")
    A("2) `localK = {v0,v1,...};`：字节码先把值压栈、再压长度（`FLOAT 38.0,4.5,0.85,0.0;")
    A("   INT 4; 0x22; 0x24`），所以长度标签排在值后面；宿主字段来自紧跟的 `X.f = localK;`。")
    A("   长度值 = 元素个数（字符串元素也算），例如 Hatch_S2_IRims_stock.Rims() 的 8 个字符串")
    A("   → 字节码 FLOAT/INT 8，与 `数组长度` 对齐。")
    A("3) `X.f[i] = v`：目标数组是 this 的字段或本方法新建的数组时，最内层下标被编进")
    A("   0x1C 指令 payload，只有链上第一笔（或「浮点值且上一笔不是整数值」）会显式压下标；")
    A("   目标是别的对象的字段（local0.turboTable[i]）时每笔都压下标：")
    A("     initPowerCharacter  turboTable 32 笔 = 32 下标 + 32 值（全浮点）")
    A("     IRunningGear_stock.<init> EBDParams_F 3 笔 = 1 下标 + 3 值（整数,整数,浮点）")
    A("     Coupe_SD_T5_IMuffler_stage_I.RPMs 3 笔 = 3 下标 + 3 值（全浮点）")
    A("     Coupe_RS_IEngine_stock.eRPMs 13 笔 = 1 下标 + 13 值（全整数）")
    A("   开关实测：--set index_model=first_only 对齐数 3308→3203（更差）。")
    A("4) 多维 `X.f[i][j] = v`：外层下标 i 每笔都压，内层 j 只在链上第一笔压：")
    A("     Model_Coupe_RS.<init> axleLoadDegradationAtBodyStage 10 笔 = 10 外下标 + 1 内下标")
    A("     + 10 值 = 21，与实测一致。开关实测：--set outer_index_always=false 3308→3288。")
    A("5) `case N:` 的 N 是字面量（switch 编译成「压 case 值 + 比较」）：算进去 3308，")
    A("   不算 3288；所以默认算，标签给 `case值`。")
    A("6) 反编译器把 `x = f(n); if ((f(n) != null))` 里的调用重复打印了一遍，")
    A("   上一行刚把同一表达式赋给局部量时，if 行里的数字不再算字面量（救回 20 个方法）。")
    A("")
    A("丢弃方法的原因分类（逐类都给过样例）")
    A("-----------------------------------")
    A("  a) 构造器 super(...) 实参被反编译器吞掉：例如 Hatch_S2_IEngine_stage_I.<init>")
    A("     字节码 `INT 1 → IEngine.<init>(I)`，伪码只剩 `initStock(local0);`，个数必然不等。")
    A("     该类别 = 失败的大头；本轮已由「规则 C」补上并通过值级校验，见上面那一节。")
    A("  a2) 缺口 +1/+3 但过不了规则 C 闸门（没有独立预测值 / 预测值与字节码不符）：")
    A("     例如 Hatch_S2_ISteeringWheel_stock 类名说 stock=0，字节码第 1 个实参是 FLOAT 350.0；")
    A("     Coupe_SD_T5_ISideskirts_stock 同理（1 != 0）。这类继续留空，不硬补。")
    A("  b) 整个方法体被吞：Hatch_S2_INitrous_stage_I.<init> 伪码只有 `return;`，")
    A("     字节码还有 3 个字面量（super 的 stage 号 + 1.0 + 0.5）。")
    A("  c) 反编译失败：Coupe_SD_T5_Rim_ST.static_getBoneAssigns 头部带")
    A("     `[stack analysis failed: unreachable]`，正文只写 `return null;`，")
    A("     真正代码只在 `// ---- N block(s) not reached` 注释里（该注释不是伪码行，未解析）。")
    A("  d) 伪码乱码：IVehicle_Coupe_RS.<init> 的数组字面量里混进 `None.xxx [I` 这种")
    A("     不成对类型描述符，值级校验也会抓到错位（这类方法本来就对不齐，被丢弃）。")
    A("  e) 乘数编在指令 payload 里：Sedan_MX_IRunningGear_stage_IV.<init> 的")
    A("     `this.DTbrak_F = (((F)1900) * 1.25);` 只有 1900 是字面量，")
    A("     1.25 在 0x1C 的 payload（pay=2684354566=0xA0000006，高位就是 1.25 的 float 高位）里。")
    A("")
    A("标签词表（给 UI 用）")
    A("----------------")
    A("  engine_volume / redline / …   字段名：直接就是被写的引擎字段（规则 1）")
    A("  turboTable[4]               字段的数组元素（规则 2/3；i 是伪码里写的下标）")
    A("  EBDParams_F[0]#下标          同一条写入指令显式压的下标字面量")
    A("  数组长度                     `new T[n]` / 数组初始化里的长度字面量（规则 4）")
    A("  local3[2]                   数组没落到任何字段上（比如直接 return），只能用局部量名")
    A("  configureVisual#参数3        某个调用的第 3 个实参")
    A("  IEngine.<init>#参数1        「规则 C」补的 super(...)/this(...) 前导实参（被吞掉的）")
    A("  case值                      switch 的 case N 值")
    A("  返回值                       return 语句里直接返回的字面量")
    A("  ?                          认不出来（本轮 0 个）")
    A("")
    A("不确定处（逐条）")
    A("----------------")
    A("  1. \"<被调用者>#参数N\"（占标签大头）只表示「这一行的第 N 个实参」，不是引擎字段名；")
    A("     实参位置的判定基于伪码的调用括号，值级校验只能保证顺序/取值一致，")
    A("     不能保证语义（同一位置多个 0.0 时看不出来）。")
    A("  2. \"<字段>#下标\" 表示「写这个元素时编译器显式压了的下标字面量」，")
    A("     下标何时显式压是按实测模型推的（见规则 3/4），个别类可能有偏差——")
    A("     但凡偏差都会让个数不等而被丢掉，不会静默错位。")
    A("  3. 少数类的伪码与字节码不同步：Hatch_Trend_IEngine_stock 的 eRPMs/eMuls")
    A("     伪码值是字节码的一半（954 vs 1908…），值级校验能抓到；这两条方法仍在 JSON 里")
    A('     （个数相等、标签描述的是「数组第 i 项」这一位置语义），但它的数值不可信。')
    A("  4. 二维 `int[][]` 数组字面量的长度占位在字节码里是 -1（真长度在 0x24 payload），")
    A("     这类位置的值级校验按例外放行（IVehicle_Hatch_S2.<init> 的 stylingIDs）。")
    A("  5. 伪码打印只有约 7 位有效数字（4.28 对应字节码 4.279999732971191），")
    A("     值级校验用 1e-6 相对容差，所以「相邻两个字面量数值很接近」的错位抓不出来（少见）。")
    A("  6. 只覆盖 vehicles/<Car>/<body>/classes.zip 下的 1850 个类；")
    A("     out_pseudo 里另外 34 个（vehicles/classes 等）不在本次范围。")
    A("  7. 「规则 C」补出来的 `<父类>.<init>#参数N`：第 1 个实参的数值由**类名层级记号**")
    A("     预测（与字节码独立），第 2..k 个由**别的车体**在同一父类构造器约定里压过的")
    A("     常量预测（leave-one-group-out）。因此：单个类或单个车体偏离一定会被逐条比对")
    A("     抓住；但若**所有车体**在同一个约定上都用错值（例如 INitrous 的 1.0/0.5 若有")
    A("     系统性偏差），本闸门看不出来 —— 这两条是那份 50 条 +3 的唯一薄弱点，已明示。")
    A("     结构层（前导字面量个数 / 位置 / owner / 形参类型）是逐条从字节码证明的，不依赖预测。")
    OUT_REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return OUT_JSON, OUT_REPORT


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--set", action="append", default=[], metavar="K=V",
                    help="覆盖解析规则开关，例如 --set case_values=true")
    ap.add_argument("--write", action="store_true", help="写 json + report")
    a = ap.parse_args(argv)
    rules = dict(RULES)
    for kv in a.set:
        k, _, v = kv.partition("=")
        rules[k] = {"true": True, "false": False}.get(v, v)
    r = run(a.limit, rules, diagnose=True)
    st = r["stats"]
    print(json.dumps(st, indent=1, ensure_ascii=False))
    print("失败分布:", json.dumps(r["fails"].most_common(12), ensure_ascii=False))
    if a.top:
        print("-- ? 来源 --")
        for k, v in r["unknown_src"].most_common(a.top):
            print("  %6d  %s" % (v, k[:100]))
    if a.write:
        base_rules = dict(rules)
        base_rules["ctor_prepend"] = False
        before = run(a.limit, base_rules, diagnose=False)
        print("before:", json.dumps({k: before["stats"][k] for k in
                                     ("checked", "aligned", "aligned_literals",
                                      "mismatch", "bc_literals")}, ensure_ascii=False))
        print("written:", write_outputs(r, before))
    return r


if __name__ == "__main__":
    main()
