"""字面量「作用」标注表（`data/literal_labels.json`）。

表由 `editors/gen_literal_labels.py` 从项目里的抬升伪码生成，并用字节码逐方法校验过
（标签个数必须等于该方法里 INT/FLOAT LITERAL 的个数）。它把每一行从
「方法名 + 序号」变成「作用」，例如：

    initBasics[0]  ->  engine_volume
    initRevCharacter[4] -> inertia
    initPowerCharacter[9] -> turboTable[4]

表不存在时全部返回 None，界面照常工作（只是没有「作用」列内容）。
"""
import json
import re
from pathlib import Path

# 数组类字面量的中文名（表里只留下反编译出的英文标识符，这里补人话）
_ARRAY_CN = {
    "eRPMs": "转速点",
    "eMuls": "扭矩倍率",
    "ePowers": "功率倍率",
    "eTorques": "扭矩倍率",
    "turboTable": "涡轮压力表",
    "boostTable": "增压表",
    "bt": "增压表",
}

# 伪码里的字段名 -> 中文（**只收含义无歧义的**；渲染成「中文 (原名)」，
# 这样即使我的译名不准，用户也能看到游戏自己的字段名）
_GLOSS = {
    "engine_volume": "排量", "idle": "怠速转速", "starter": "起动转速",
    "redline": "红线转速", "limiter": "断油转速", "limiter_reset": "断油恢复转速",
    "rev_limit": "限转", "max_rpm": "最高转速", "min_rpm": "最低转速",
    "inertia": "转动惯量", "mass": "质量", "weight": "重量",
    "drag": "风阻系数", "downforce": "下压力", "grip": "抓地力",
    "brake": "制动力", "brake_force": "制动力", "handbrake": "手刹力",
    "gear": "档位数", "ratio": "齿比", "final_drive": "主减速比",
    "torque": "扭矩", "power": "功率", "rpm": "转速",
    "steering": "转向", "suspension": "悬挂", "spring": "弹簧刚度",
    "damper": "阻尼", "travel": "悬挂行程", "camber": "外倾角", "toe": "前束",
    "fuel": "燃油", "fuel_capacity": "油箱容量", "nos": "氮气",
    "price": "价格", "cost": "价格", "damage": "损伤", "health": "耐久",
    "friction": "摩擦系数", "wheel_radius": "轮半径", "wheelbase": "轴距",
    "length": "车长", "width": "车宽", "height": "车高",
}

_ARR_RE = re.compile(r"^([A-Za-z_]\w*)\[(\d+)\](#下标)?$")
_LOCAL_RE = re.compile(r"^local\d+\[(\d+)\](#下标)?$")


def _pretty(v, method_name):
    """把「反编译残留」整成「人话」。

    生成器只能从伪码里抄标识符，于是数组字面量长这样：
        local0[0]#下标   —— 下标立即数（编译器生成的，改它没用）
        local0[3]        —— 第 3 项的值
        turboTable[0]#下标
    这里把数组名换成中文、把「#下标」标出来，字段名加中文注解。
    """
    if not v:
        return v
    m = re.match(r"^([A-Za-z_][\w$]*)\.<init>#参数(\d+)$", v)   # 构造器实参
    if m:
        return "%s 构造参数%s" % (m.group(1), m.group(2))
    m = re.match(r"^super#参数(\d+)$", v)
    if m:
        return "父类构造参数%s" % m.group(1)
    m = _LOCAL_RE.match(v)          # local0 这种匿名数组：用方法名当数组名
    if m:
        cn = _ARRAY_CN.get(method_name, method_name)
        return "%s 第%s项%s" % (cn, m.group(1),
                              "的下标（自动生成，别改）" if m.group(2) else "")
    m = _ARR_RE.match(v)
    if m:
        cn = _ARRAY_CN.get(m.group(1), m.group(1))
        return "%s 第%s项%s" % (cn, m.group(2),
                              "的下标（自动生成，别改）" if m.group(3) else "")
    if v == "数组长度":
        return "%s 的元素个数" % _ARRAY_CN.get(method_name, method_name)
    if v in ("?", "-"):
        return v
    g = _GLOSS.get(v.lower())
    return "%s (%s)" % (g, v) if g else v

_HERE = Path(__file__).resolve().parent
_CANDIDATES = (
    _HERE.parent / "data" / "literal_labels.json",
    _HERE / "literal_labels.json",
)
_cache = None


def available():
    return any(p.is_file() for p in _CANDIDATES)


def table():
    """{类短名 或 'Car/body/类短名': {方法名: [标签, ...]}}，失败时返回 {}。"""
    global _cache
    if _cache is not None:
        return _cache
    _cache = {}
    for p in _CANDIDATES:
        if p.is_file():
            try:
                _cache = json.loads(p.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                _cache = {}
            break
    return _cache


def label_for(class_short, method_name, index, car=None, body=None):
    """查一条标注；查不到返回 None。"""
    t = table()
    if not t:
        return None
    keys = []
    if car and body:
        keys.append("%s/%s/%s" % (car, body, class_short))
    keys.append(class_short)
    for k in keys:
        m = t.get(k)
        if not m:
            continue
        lst = m.get(method_name)
        if lst and 0 <= index < len(lst):
            v = lst[index]
            if v and v not in ("?", "-"):
                return _pretty(v, method_name)
            if v == "?":
                return None
    return None


def count():
    return sum(len(m) for m in table().values())


# ---------------------------------------------------------------------------
# 共享包（java/classes.zip）里那几个关键类的标注
# 生成器只覆盖了车包（vehicles/**），共享类没有伪码级标签，这里按**实测字面量
# 位置**手写 —— 位置都来自 2026-09-30 的逐字节核对（docs/61）。
# ---------------------------------------------------------------------------
_INITROUS_ONINSTALL = {
    0: "分派常量 档1", 1: "分派常量 档2", 2: "分派常量 档3",
    3: "分派常量 档4", 4: "分派常量 档5",
    5: "Stage I 喷射加成", 6: "Stage I 氮气容量",
    7: "Stage II 喷射加成", 8: "Stage II 氮气容量",
    9: "Stage III 喷射加成", 10: "Stage III 氮气容量",
    11: "Stage IV 喷射加成", 12: "Stage IV 氮气容量",
    13: "WB 喷射加成", 14: "WB 氮气容量",
    15: "默认分支 0", 16: "默认分支 0",
    17: "氮气消耗率 (consumption_nitro)",
}
_IENGINE_DEFAULT = {
    0: "（占位 int）", 1: "（占位 float）", 2: "（占位 float）", 3: "turboTable 长度 = 32",
    4: "turboLag（涡轮迟滞）", 5: "turboWGLimit（泄压阀转速）",
    6: "turboBOVLimit（放气阀）", 7: "turboPeakP（★增压总开关，>0.01 才增压）",
    8: "turboFlags",
}


def shared_label(class_short, method_name, index):
    """共享包关键类的「作用」（查不到返回 None）。"""
    if class_short == "INitrous" and method_name == "onInstall":
        return _INITROUS_ONINSTALL.get(index)
    if class_short == "IEngine" and method_name in ("<i>", "<clinit>"):
        return _IENGINE_DEFAULT.get(index)
    return None
