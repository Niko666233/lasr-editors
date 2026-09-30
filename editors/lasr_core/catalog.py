# -*- coding: utf-8 -*-
"""LASR 车辆/零件目录：从游戏原始字节码现场恢复「车 → 零件族 → 显示名 → 零件 id」的目录。

只依赖同目录的既有 codec：
  * ``flzd.py``  —— FLZD 容器解压（用 LASR.exe 自己的解压例程，unicorn 模拟）
  * ``tufa.py``  —— TUFA 类容器 / 常量池 / 方法字节码

提供三块 API（对应任务 1/2/3）：

任务 1  ``VehicleCatalog`` / ``scan_vehicles()``
    vehicles/<Car_Year>/<body>/classes.zip 里的每个 .class 拆成
    (零件族 family, 变体后缀 variant, 显示名 display_name, 类别 kind)。
    显示名 = 该类自己的 ``getName()Ljava.lang.String;`` 方法体里第 1 个字符串常量；
    拿不到就填 None（不猜、不回退到类名）。

任务 2  ``getipart_map()``
    从 ``Model_<Body>.getIPart(I)`` 的字节码现场恢复 {case 值: 零件类名}。
    编译后的形状是一个非常规整的开关链：

        ===== 比较链（每项 10 字节）=====
        05 <case 常量>        INT LITERAL
        1a <相对偏移>         条件跳转；目标 = 该 0x1a 指令**自身**的偏移 + payload
        ===== 处理体（每个 12 字节）=====
        27 <常量池索引>       NEW，pool.ref(payload) -> owner 即零件类名
        2a / 11 <ref>         DUP / INVOKESPECIAL <init>
        16                    RETURN
        ===== 落到「return null」=================
        17 <相对偏移>         无条件跳转（case 0 走这条，见下文）
        03 16                 压 null + RETURN

任务 3  ``ITEMSLOT`` / ``slot_table()`` / ``IPL_UPGRADE`` / ``stage_of_kind()``
    零件槽位名表（0..64）与 IPL_UPGRADE_* 常量。

零件 id 约定（任务书给定）： id = (1<<29) | (车索引 << 16) | case 值
  * 依据（本项目伪码可查）： ``IPart.PART_BITS=16``、``PART_SHFT=0``、
    ``ItemRoot.TYPE_BITS=3``、``IVehicle.VHC_BITS = 32-3-16 = 13``、``VHC_SHFT=PART_BITS``
    —— 即 case 占 bit0..15、车索引占 bit16..28、类型占 bit29..31；
    类型字段取值 ``TYPE_IPART = 1<<29`` 来自任务书约定，伪码里没有该常量（见报告「不确定」）。
  * ``build_id_index(catalog)`` / ``lookup_id(catalog, id)`` 就是给存档编辑器用的
    全量 id -> 类名 索引（含车目录/case）。

用法：
    import sys; sys.path.insert(0, 'editors')
    from lasr_core import catalog
    c = catalog.VehicleCatalog()          # 内部懒建 FlzdCodec，全流程复用
    c.load_all()                          # 任务 1
    c.load_vid_table(); c.match_car_index()
    v = c.vehicles[5]
    print(v.prefix, v.models, len(v.families()))
    print(c.getipart_map_for(v)[0])       # 任务 2
    print(catalog.lookup_id(c, catalog.part_id(0, 5)))
    print(catalog.slot_table()[0])        # 任务 3
"""

from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path

from . import vdata

_HERE = Path(__file__).resolve().parent
if str(_HERE.parent) not in sys.path:
    sys.path.insert(0, str(_HERE.parent))

try:  # 作为包被 import（editors.lasr_core.catalog）
    from . import tufa
except ImportError:  # 直接脚本运行
    from lasr_core import tufa

# flzd（要 unicorn 的那个）**故意不在这里 import**：打包成 exe 时 unicorn 会被排除
# （它在 frozen exe 里 0xC0000409，见 docs/60 §6），模块级 import 会让工具起不来。
# 只有真的需要解压时才在函数里 import。

# --------------------------------------------------------------------------
# 常量
# --------------------------------------------------------------------------

DEFAULT_GAME_ROOT = r"C:/Games/LASR"
EXE_NAME = "LASR.exe"
VEHICLES_SUBDIR = "vehicles"
CLASSES_ZIP = "classes.zip"

# TUFA VM 操作码（只列本模块用到的；全表见 docs/08_VM_OPCODES.md / tufa.NO_PAYLOAD）
OP_INT_LITERAL = 0x05     # 5 字节，payload = int 立即数
OP_STRING = 0x08          # 5 字节，payload = 常量池索引 -> utf8 字符串
OP_INVOKESPECIAL = 0x11   # 5 字节，payload = 常量池 ref
OP_GETSTATIC = 0x14       # 5 字节，payload = 常量池 ref（读静态字段）
OP_RETURN = 0x16          # 1 字节
OP_JMP = 0x17             # 5 字节，payload = 相对偏移（基址 = 自身偏移）
OP_JMP_EQ2 = 0x1A         # 5 字节，payload = 相对偏移（基址 = 自身偏移，实测）
OP_PUTSTATIC = 0x20       # 5 字节，payload = 常量池 ref（写静态字段）
OP_NEW = 0x27             # 5 字节，payload = 常量池索引 -> class ref

# 零件类名后缀 = 变体。全集来自对 10 台车 1,860 个类名的实测枚举：
#   stock / track / drift / rally / custom / custom2 / WB
#   stage_I..IV / stage_WB / style_I..IV / style_WB
VARIANT_RE = re.compile(
    r"_(stock|track|drift|rally|custom\d*|WB"
    r"|stage_(?:I|II|III|IV|V|WB)|style_(?:I|II|III|IV|V|WB))$"
)

#: 变体后缀 -> 该变体烘焙进类里的 ``kind``（见「任务 3 备注」）
VARIANT_KIND = {
    "stock": 0,
    "stage_I": 1, "stage_II": 2, "stage_III": 3, "stage_IV": 4, "stage_V": 5,
}

#: 零件 id 里的类型位（任务书约定）
TYPE_IPART = 1 << 29
PART_BITS = 16
PART_SHFT = 0
VHC_SHFT = 16
VHC_BITS = 13

#: IPL_UPGRADE_*（out_pseudo/java/classes/game/item/IVehicle.java:107-114）
IPL_UPGRADE = {
    "IPL_UPGRADE_STOCK": 1,
    "IPL_UPGRADE_STAGE_I": 2,
    "IPL_UPGRADE_STAGE_II": 3,
    "IPL_UPGRADE_STAGE_III": 4,
    "IPL_UPGRADE_STAGE_IV": 5,
    "IPL_UPGRADE_STAGE_V": 6,
    "IPL_CUSTOM_PARTS": 7,
    "IPL_MAX": 8,
}

#: 零件槽位名表（out_pseudo/java/classes/game/item/IVehicle.java:34-98，全部 ITEMSLOT_*）
ITEMSLOT = {
    0:  ("STYL_F_BUMPER",         "前保险杠(外观)"),
    1:  ("STYL_HOOD",             "引擎盖(外观)"),
    2:  ("STYL_SIDESKIRTS",       "侧裙(外观)"),
    3:  ("STYL_TRUNK_HATCH",      "后备箱盖/尾门(外观)"),
    4:  ("STYL_R_BUMPER",         "后保险杠(外观)"),
    5:  ("STYL_HEADLIGHTS",       "前大灯(外观)"),
    6:  ("STYL_F_DOORS",          "前车门(外观)"),
    7:  ("STYL_R_DOORS",          "后车门(外观)"),
    8:  ("STYL_TAILLIGHTS",       "尾灯(外观)"),
    9:  ("STYL_R_WING",           "尾翼(外观)"),
    10: ("STYL_F_GUARD_RAIL",     "前防撞护栏(外观)"),
    11: ("STYL_S_GUARD_RAILS",    "侧护栏(外观)"),
    12: ("STYL_ROLLCAGE",         "防滚架(外观)"),
    13: ("STYL_R_GUARD_RAIL",     "后防撞护栏(外观)"),
    14: ("STYL_F_WING",           "前风翼/前定风翼(外观)?"),
    15: ("STYL_F_MIRRORS",        "外后视镜(外观)"),
    16: ("STYL_STICKER",          "车贴/贴纸(外观)〔= STYL_STICKER_HOOD，同值别名〕"),
    17: ("STYL_STICKER_DOOR",     "车门贴纸(外观)"),
    18: ("STYL_STICKER_F_QUARTER", "前侧翼板贴纸(外观)?"),
    19: ("STYL_STICKER_R_QUARTER", "后侧翼板贴纸(外观)?"),
    20: ("STYL_F_SEATS",          "前排座椅(内饰)"),
    21: ("STYL_R_SEATS",          "后排座椅(内饰)"),
    22: ("STYL_STEER_WHEEL",      "方向盘(内饰)"),
    23: ("STYL_SHIFT_KNOB",       "换挡杆头(内饰)"),
    24: ("STYL_HORN",             "喇叭(内饰)"),
    25: ("STYL_WINDOW_TINT",      "车窗贴膜(内饰)"),
    26: ("STYL_ENTERTAINMENT",    "音响/娱乐系统(内饰)"),
    27: ("STYL_INTERIOR_TRIM",    "内饰饰板(内饰)"),
    28: ("STYL_GAUGES",           "仪表组(内饰)"),
    29: ("STYL_PAINTJOB",         "车漆(外观)"),
    30: ("DRIV_TRANSMISSION",     "变速箱(驱动)"),
    31: ("DRIV_CLUTCH",           "离合器(驱动)"),
    32: ("DRIV_F_DIFF",           "前差速器(驱动)"),
    33: ("DRIV_C_DIFF",           "中央差速器(驱动)"),
    34: ("DRIV_R_DIFF",           "后差速器(驱动)"),
    35: ("RGER_TYRES",            "轮胎(行走/姿态)"),
    36: ("RGER_RIMS",             "轮毂(行走/姿态)"),
    37: ("STYL_STICKER_ROOF",     "车顶贴纸(外观)"),
    38: ("DRIV_R_RIMS",           "后轮毂(驱动)"),
    39: ("DRIV_R_TYRES",          "后轮胎(驱动)"),
    40: ("RGER_SUSPENSION",       "悬挂(行走/姿态)"),
    41: (None,                    "?〔0..64 里唯一没有 ITEMSLOT_* 常量的槽，原版未命名〕"),
    42: ("RGER_BRAKES",           "刹车(行走/姿态)"),
    43: ("DRIV_F_RIMS",           "前轮毂(驱动)"),
    44: ("DRIV_F_TYRES",          "前轮胎(驱动)"),
    45: ("EBAY_ENGINE",           "引擎(eBay 性能件)"),
    46: ("EBAY_FUEL_SYSTEM",      "燃油系统(eBay 性能件)"),
    47: ("EBAY_CYLINDER_HEAD",    "气缸盖(eBay 性能件)"),
    48: ("EBAY_LUBRICATION",      "润滑系统(eBay 性能件)"),
    49: ("EBAY_RADIATOR",         "散热器(eBay 性能件)"),
    50: ("EBAY_INTAKE",           "进气系统(eBay 性能件)"),
    51: ("EBAY_CHARGER",          "增压器/涡轮(eBay 性能件)"),
    52: ("EBAY_EXHAUST",          "排气(eBay 性能件)"),
    53: ("EBAY_MUFFLER",          "消声器(eBay 性能件)"),
    54: ("EBAY_INTERCOOLER",      "中冷器(eBay 性能件)"),
    55: ("EBAY_ECU",              "行车电脑 ECU(eBay 性能件)"),
    56: ("EBAY_TCS",              "牵引力控制 TCS(eBay 性能件)"),
    57: ("EBAY_ABS",              "防抱死 ABS(eBay 性能件)"),
    58: ("EBAY_ESP",              "车身稳定 ESP(eBay 性能件)"),
    59: ("EBAY_N20",              "氮气 N2O(eBay 性能件)"),
    60: ("DUMMIESTOFTHEDUMMIES",  "占位哑槽(内部)"),
    61: ("STYL_ROOF_WING",        "车顶扰流(外观)"),
    62: ("STYL_CHASSIS_R_WING",   "车体尾翼(外观)"),
    63: ("MISC_WEIGHT_REDUCTION", "减重(杂项)"),
    64: ("MISC_LIGHTBAR",         "警灯条(杂项)"),
}


def slot_table():
    """{槽号: {'en': 常量名, 'cn': 中文名}}（0..64）"""
    return {n: {"en": en, "cn": cn} for n, (en, cn) in ITEMSLOT.items()}


def stage_of_kind(kind):
    """零件 ``kind``(0=stock,1..5=stage_I..V) -> IPL_UPGRADE_* 数值。

    依据（伪码）：java.game.item.IEngine.getPriority() 里
    ``switch (this.kind) { case 1: return IPL_UPGRADE_STAGE_I; ... }``
    （out_pseudo/java/classes/game/item/IEngine.java:100-115）。
    """
    if kind == 0:
        return IPL_UPGRADE["IPL_UPGRADE_STOCK"]
    name = {1: "IPL_UPGRADE_STAGE_I", 2: "IPL_UPGRADE_STAGE_II",
            3: "IPL_UPGRADE_STAGE_III", 4: "IPL_UPGRADE_STAGE_IV",
            5: "IPL_UPGRADE_STAGE_V"}.get(kind)
    return IPL_UPGRADE.get(name) if name else None


def part_id(vehicle_index, case_value):
    """(1<<29) | (车索引<<16) | case 值"""
    return TYPE_IPART | ((vehicle_index & 0x1FFF) << VHC_SHFT) | (case_value & 0xFFFF)


def id_parts(item_id):
    """零件 id -> (类型, 车索引, case 值)"""
    return ((item_id >> 29) & 0x7, (item_id >> VHC_SHFT) & 0x1FFF, item_id & 0xFFFF)


# --------------------------------------------------------------------------
# 数据模型
# --------------------------------------------------------------------------

class Part(object):
    """zip 里的一个 .class 条目。"""

    __slots__ = ("name", "family", "variant", "kind", "display_name",
                 "display_source", "entry")

    def __init__(self, name, family, variant, kind, display_name, display_source, entry):
        self.name = name              # 简单类名，例如 Coupe_RS_IEngine_stock
        self.family = family          # 零件族，例如 IEngine（车体级类为 None）
        self.variant = variant        # 变体后缀，例如 stage_I；无则 None
        self.kind = kind              # part / geometry / paintjob / sticker / model / vehicle / sounds
        self.display_name = display_name      # getName() 里的字符串常量，拿不到 = None
        self.display_source = display_source  # getName / no-getName / getName-not-string
        self.entry = entry            # zip 内条目名

    def __repr__(self):
        return "<Part %s family=%s variant=%s kind=%s name=%r>" % (
            self.name, self.family, self.variant, self.kind, self.display_name)


class Vehicle(object):
    """一台车的一个车体（vehicles/<Car_Year>/<body>/classes.zip）。"""

    def __init__(self, car, body, zip_path):
        self.car = car            # 目录名，例如 Phoenix_RS_1997
        self.body = body          # 目录名，例如 coupe
        self.zip_path = str(zip_path)
        self.prefix = None        # 车体类名前缀，例如 Coupe_RS（由 Model_*/IVehicle_* 推出）
        self.models = []          # ['Model_Coupe_RS', 'Model_Coupe_RS_WB']
        self.ivhicles = []        # ['IVehicle_Coupe_RS', ...]
        self.parts = []           # [Part]
        self.n_entries = 0

    # -- 分类视图 ---------------------------------------------------------
    def by_kind(self, kind):
        return [p for p in self.parts if p.kind == kind]

    def families(self):
        """{零件族: [Part]}（只含 kind == 'part'）"""
        out = {}
        for p in self.parts:
            if p.kind == "part":
                out.setdefault(p.family, []).append(p)
        return out

    def __repr__(self):
        return "<Vehicle %s/%s prefix=%s parts=%d>" % (
            self.car, self.body, self.prefix, len(self.parts))


# --------------------------------------------------------------------------
# 字节码层：显示名 / getIPart
# --------------------------------------------------------------------------

def static_string_field(t, field):
    """找 ``<field> = "字面量"`` 的值：程序顺序里紧邻在 PUTFIELD_STATIC 之前压栈的字符串。"""
    for m in t.methods:
        if not m.linear:
            continue
        last = None
        for _o, op, _w, pay in m.prog:
            if op == OP_STRING:
                last = t.pool.utf8(pay)
            elif op == OP_PUTSTATIC and pay is not None:
                r = t.pool.ref(pay)
                if r and r[1] == field and last is not None:
                    return last
    return None


def class_display_name(t):
    """该类自己的 getName() 返回值 -> (name, source)。

    * ``return "字面量";``  -> 直接取 0x08 的字符串（绝大多数外观/内饰件）
    * ``return <静态字段>;`` -> 追到该静态字段被赋的字面量（Model_* 的
      ``getName()`` 就是 ``return ModelName``，ModelName = "'97 Phoenix RS"）
    两种都拿不到就 (None, 原因)，不猜、不回退到类名。
    """
    hits = [m for m in t.methods
            if m.name == "getName" and (m.desc or "").startswith("()Ljava.lang.String")]
    if not hits:
        return None, "no-getName"
    m = hits[0]
    if not m.linear:
        return None, "getName-not-linear"
    for _o, op, _w, pay in m.prog:
        if op == OP_STRING:
            s = t.pool.utf8(pay)
            if s is not None:
                return s, "getName"
            return None, "getName-bad-poolidx"
    for _o, op, _w, pay in m.prog:
        if op == OP_GETSTATIC and pay is not None:
            r = t.pool.ref(pay)
            if r and r[1]:
                s = static_string_field(t, r[1])
                if s is not None:
                    return s, "getName->" + r[1]
            break
    return None, "getName-not-string"


def getipart_map(t):
    """``Model_<Body>.getIPart(I)`` -> {case 值: 零件类名 or None}。

    None 表示该 case 落到「压 null + RETURN」（原版伪码里渲染成 ``case 0: break;``）。
    现场从字节码恢复，不读任何伪码文件。
    """
    out = {}
    meth = None
    for m in t.methods:
        if m.name == "getIPart":
            meth = m
            break
    if meth is None:
        return out
    if not meth.linear:
        return out
    prog = meth.prog
    by_off = {o: (op, pay) for o, op, _w, pay in prog}
    for i, (o, op, _w, pay) in enumerate(prog):
        if op != OP_INT_LITERAL or i + 1 >= len(prog):
            continue
        o2, op2, _w2, pay2 = prog[i + 1]
        if op2 == OP_JMP_EQ2:
            tgt = o2 + pay2                     # 基址 = 跳转指令自身偏移
            ent = by_off.get(tgt)
            if ent is None:
                continue
            if ent[0] == OP_NEW:
                r = t.pool.ref(ent[1])
                out[pay if pay < 0x80000000 else pay - (1 << 32)] = r[0] if r else None
            elif ent[0] == OP_JMP:
                # 跳向共享的「压 null + RETURN」尾巴 —— case 0 走这条
                out[pay if pay < 0x80000000 else pay - (1 << 32)] = None
        elif op2 == OP_NEW:                     # 未压缩形式（防御性分支）
            r = t.pool.ref(pay2)
            out[pay if pay < 0x80000000 else pay - (1 << 32)] = r[0] if r else None
    return out


def class_ctor_kind(t):
    """具体零件类的 ``<init>()`` 传给父类 ``<init>(I)`` 的 kind 值（拿不到 None）。

    例：Coupe_RS_IEngine_stage_I.<init> = ``push 1; invokespecial IEngine.<init>(I)``。
    """
    for m in t.methods:
        if m.name != "<init>":
            continue
        if not m.linear:
            continue
        last_int = None
        for _o, op, _w, pay in m.prog:
            if op == OP_INT_LITERAL:
                last_int = pay if pay < 0x80000000 else pay - (1 << 32)
            elif op == OP_INVOKESPECIAL and pay is not None:
                r = t.pool.ref(pay)
                if r and r[1] == "<init>" and r[2] == "(I)":
                    return last_int
        return None
    return None


def _looks_like_geometry(method_names):
    return any(n in method_names for n in ("getMesh", "getRenderType", "getBoneAssigns"))


# --------------------------------------------------------------------------
# 目录扫描
# --------------------------------------------------------------------------

def _classify(vehicle, name, t):
    """给一个类定 (family, variant, kind)。"""
    if name.startswith("IVehicle_"):
        return None, None, "vehicle"
    if name.startswith("Model_"):
        return None, None, "model"
    if name.startswith("IPaintjob_"):
        return name, None, "paintjob"
    if name.startswith("ISticker_"):
        return name, None, "sticker"
    # 去掉车体前缀
    body = name
    if vehicle.prefix and name.startswith(vehicle.prefix + "_"):
        body = name[len(vehicle.prefix) + 1:]
    m = VARIANT_RE.search(body)
    if m:
        return body[:m.start()], m.group(1), "part"
    if body == "Sounds":
        return body, None, "sounds"
    names = [mm.name for mm in t.methods]
    if _looks_like_geometry(names) and "getPrestige" not in names:
        return body, None, "geometry"
    return body, None, "part"


def scan_vehicles(game_root=DEFAULT_GAME_ROOT):
    """[ (car, body, zip_path) ]，按目录名排序。"""
    root = Path(game_root) / VEHICLES_SUBDIR
    out = []
    if not root.is_dir():
        raise FileNotFoundError("找不到 %s" % root)
    for car in sorted(p for p in root.iterdir() if p.is_dir()):
        for body in sorted(p for p in car.iterdir() if p.is_dir()):
            z = body / CLASSES_ZIP
            if z.is_file():
                out.append((car.name, body.name, z))
    return out


class VehicleCatalog(object):
    """一次编解码器，扫全部车。"""

    def __init__(self, game_root=DEFAULT_GAME_ROOT, exe_path=None, verbose=False):
        self.game_root = str(game_root)
        self.exe_path = exe_path or "%s/%s" % (self.game_root.rstrip("/"), EXE_NAME)
        self.verbose = verbose
        self._codec = None
        self.vehicles = []
        self.vid = {}
        self.car_index = {}

    # -- 懒加载 codec（unicorn 初始化较贵，全流程只建一次）-----------------
    @property
    def codec(self):
        if self._codec is None:
            from . import flzd          # 懒加载（要 unicorn；快照命中时根本不会走到这）
            self._codec = flzd.FlzdCodec(self.exe_path)
        return self._codec

    def load_class(self, tufa_bytes):
        return tufa.Tufa(tufa_bytes)

    def read_class(self, zf, entry):
        """zip 条目 -> TUFA 对象。

        优先走随工具发布的明文快照（**不需要 unicorn** —— 打包 exe 里
        `uc.emu_start` 会 0xC0000409，见 docs/60 §6）；快照缺失或不一致才真解压。
        """
        path = getattr(zf, "filename", None)
        if path:
            data = vdata.read_zip_entry(path, entry, codec=self._codec)
        else:
            from . import flzd
            raw = zf.read(entry)
            data = self.codec.unpack(raw) if flzd.is_flzd(raw) else raw
        return tufa.Tufa(data)

    # -- 任务 3 附带：真字节码里的 VID 表 --------------------------------
    def load_vid_table(self, java_zip=None):
        """从 java/classes.zip 的 IVehicle.<clinit> 恢复 VID_* -> 索引。

        <clinit> 的形状：``05 <int>`` 然后 ``20 <常量池 ref: IVehicle.VID_*>``。
        """
        path = java_zip or "%s/java/%s" % (self.game_root.rstrip("/"), CLASSES_ZIP)
        with zipfile.ZipFile(path) as zf:
            entry = None
            for n in zf.namelist():
                if n.endswith("/IVehicle.class") or n == "IVehicle.class":
                    entry = n
                    break
            if entry is None:
                raise FileNotFoundError("java/classes.zip 里没有 IVehicle.class")
            t = self.read_class(zf, entry)
        vid = {}
        for m in t.methods:
            if not m.linear:
                continue
            last = None
            for _o, op, _w, pay in m.prog:
                if op == OP_INT_LITERAL:
                    last = pay if pay < 0x80000000 else pay - (1 << 32)
                elif op == OP_PUTSTATIC and pay is not None:
                    r = t.pool.ref(pay)
                    if r and r[0] and r[0].endswith("IVehicle") and (r[1] or "").startswith("VID_"):
                        vid[r[1]] = last
        self.vid = vid
        return vid

    def match_car_index(self):
        """车目录名 -> 车索引（VID_*）。

        打分 = 年份命中 + 名字 token 重叠；必须唯一最优，否则留空并在报告里标出。
        """
        out = {}
        ambiguous = {}
        years = {n: re.findall(r"\d{2,4}", n) for n in self.vid}
        for car, body, _z in scan_vehicles(self.game_root):
            ctoks = set(t for t in car.split("_") if t)
            cyear = re.findall(r"\d{4}", car)
            cy2 = set(y[-2:] for y in cyear)
            scores = []
            for vname, idx in self.vid.items():
                base = vname[4:]
                vtoks_l = [t for t in base.split("_") if t]
                vtoks = set(vtoks_l)
                s = len(ctoks & vtoks)
                if cy2 and any(y in years[vname] for y in cy2):
                    s += 3
                # WB 宽体变体不是普通车目录名，出现就轻扣分
                if "WB" in vname:
                    s -= 1
                # 第二排序键用 token 数（基型名字最短），再按字母序 —— 解决
                # VID_06_Fujin_MX 与 VID_06_Fujin_MX_Matt_Peacock 同分的情况
                scores.append((s, -len(vtoks_l), vname, idx))
            scores.sort(key=lambda x: (-x[0], -x[1], x[2]))
            if scores and (len(scores) == 1 or scores[0][:2] > scores[1][:2]):
                out[car] = scores[0][3]
            else:
                ambiguous[car] = [(s[0], s[1], s[2], s[3]) for s in scores[:3]]
        self.car_index = out
        self.car_index_ambiguous = ambiguous
        return out

    # -- 任务 1：扫一台车 ------------------------------------------------
    def load_vehicle(self, car, body, zip_path):
        v = Vehicle(car, body, zip_path)
        with zipfile.ZipFile(zip_path) as zf:
            entries = [n for n in zf.namelist() if n.lower().endswith(".class")]
            v.n_entries = len(entries)
            simple = {}
            for e in entries:
                simple[Path(e).stem] = e
            # 车体前缀：只用 Model_* 推（Model 类是车体定义本身）。IVehicle_* 里还有
            # 警车/车手特供变体（如 IVehicle_Sedan_MX_N1），拿它们推会得出过长的前缀，
            # 把 Sedan_MX_IEngine_stock 这类零件错误地当成另一个族（踩过，实测 10 台车）。
            cands = set()
            model_names = [nm for nm in simple if nm.startswith("Model_")]
            for nm in model_names:
                v.models.append(nm)
                cands.add(nm[len("Model_"):])
            for nm in simple:
                if nm.startswith("IVehicle_"):
                    v.ivhicles.append(nm)
            if not cands:  # 兜底：没有 Model_* 时才用 IVehicle_*
                for nm in v.ivhicles:
                    cands.add(nm[len("IVehicle_"):])
            v.models.sort()
            v.ivhicles.sort()
            stripped = set(c[:-3] if c.endswith("_WB") else c for c in cands)
            v.prefix = sorted(stripped, key=len)[0] if stripped else None
            v.prefix_candidates = sorted(stripped)
            for nm in sorted(simple):
                t = self.read_class(zf, simple[nm])
                family, variant, kind = _classify(v, nm, t)
                disp, src = class_display_name(t)
                v.parts.append(Part(nm, family, variant, kind, disp, src, simple[nm]))
                if self.verbose:
                    print("    %-42s %-18s %-10s %-9s %r"
                          % (nm, family, variant, kind, disp))
        return v

    def load_all(self):
        self.vehicles = [self.load_vehicle(c, b, z)
                         for (c, b, z) in scan_vehicles(self.game_root)]
        return self.vehicles

    # -- 任务 2 ----------------------------------------------------------
    def getipart_map_for(self, vehicle):
        """车体主类 Model_<Body>.class（不带 _WB）-> {case: 类名}"""
        target = None
        for nm in vehicle.models:
            if not nm.endswith("_WB"):
                target = nm
                break
        if target is None:
            return {}, None
        with zipfile.ZipFile(vehicle.zip_path) as zf:
            for n in zf.namelist():
                if Path(n).stem == target:
                    return getipart_map(self.read_class(zf, n)), target
        return {}, target


def build_id_index(catalog, refresh=False):
    """给存档编辑器用的全量索引：{零件 id: (车目录, case 值, 类名 or None)}。

    零件 id = (1<<29) | (车索引<<16) | case，车索引来自 IVehicle 的 VID_*（真字节码）。
    类名 None 表示原版该 case 落到「return null」分支（每台车的 case 0）。
    结果缓存在 catalog 上，重复调用不重扫。
    """
    if not refresh and getattr(catalog, "_id_index", None) is not None:
        return catalog._id_index
    out = {}
    for v in catalog.vehicles:
        idx = catalog.car_index.get(v.car)
        if idx is None:
            continue
        rec, _model = catalog.getipart_map_for(v)
        for case, cls in rec.items():
            out[part_id(idx, case)] = (v.car, case, cls)
    catalog._id_index = out
    return out


def lookup_id(catalog, item_id):
    """零件 id -> (类型, 车索引, case, 车目录, 类名)；查不到返回 None。"""
    typ, vidx, case = id_parts(item_id)
    hit = build_id_index(catalog).get(item_id)
    if hit is None:
        return None
    return (typ, vidx, case, hit[0], hit[2])


# --------------------------------------------------------------------------
# 自检 / 报告
# --------------------------------------------------------------------------

_PSEUDO_ROOT = _HERE.parent.parent / "out_pseudo" / "vehicles"


def pseudo_getipart(car, body, model_class):
    """从 out_pseudo 的 Model_<Body>.java 里抽 {case: 类名 or None}，仅用于交叉验证。"""
    p = _PSEUDO_ROOT / car / body / "classes" / "classes" / (model_class + ".java")
    if not p.is_file():
        return None, str(p)
    lines = p.read_text(encoding="latin-1").splitlines()
    start = None
    for i, ln in enumerate(lines):
        if "getIPart(I)Ljava.game.item.IPart;" in ln:
            start = i + 1
            break
    if start is None:
        return None, "无 getIPart 方法头"
    end = len(lines)
    for j in range(start, len(lines)):
        s = lines[j].strip()
        if s.startswith("// ") or s == "//":
            end = j
            break
    out = {}
    cur = None
    case_re = re.compile(r"^\s*case\s+(-?\d+)\s*:")
    new_re = re.compile(r"return new ([A-Za-z0-9_.$]+)\.<init>\(\);")
    for ln in lines[start:end]:
        m = case_re.match(ln)
        if m:
            cur = int(m.group(1))
            out.setdefault(cur, None)
            continue
        m = new_re.search(ln)
        if m and cur is not None:
            out[cur] = m.group(1)
    return out, None


def main(argv=None, report_path=None):
    out = []

    def emit(s=""):
        out.append(s)
        print(s)

    emit("=" * 78)
    emit("LASR 车辆/零件目录自检报告 (editors/lasr_core/catalog.py)")
    emit("=" * 78)

    cat = VehicleCatalog(verbose=False)
    emit("FLZD 编解码器（跑 LASR.exe 自己的例程，unicorn）初始化成功，"
         "level 表 = %s" % (cat.codec.table,))
    emit("")

    trips = scan_vehicles(cat.game_root)
    emit("发现 %d 个 classes.zip（任务 1 全量）：" % len(trips))
    for car, body, z in trips:
        emit("  %-24s %-6s %s (%d bytes)"
             % (car, body, z.as_posix(), z.stat().st_size))
    emit("")

    # ---------------- 任务 1 ----------------
    emit("-" * 78)
    emit("任务 1：零件目录（每台车的零件数 / 显示名命中率）")
    emit("-" * 78)
    header = ("%-24s %6s %6s %6s %8s %8s %6s"
              % ("车", "条目", "零件", "零件族", "有显示名", "命中率", "几何"))
    emit(header)
    emit("-" * len(header))
    total_parts = 0
    total_disp = 0
    for car, body, z in trips:
        v = cat.load_vehicle(car, body, z)
        cat.vehicles.append(v)
        plist = v.by_kind("part")
        fams = v.families()
        disp = [p for p in plist if p.display_name is not None]
        total_parts += len(plist)
        total_disp += len(disp)
        emit("%-24s %6d %6d %6d %8d %7.1f%% %6d"
             % (car, v.n_entries, len(plist), len(fams), len(disp),
                100.0 * len(disp) / max(1, len(plist)), len(v.by_kind("geometry"))))
    emit("-" * len(header))
    emit("%-24s %6s %6d %6s %8d %7.1f%%"
         % ("合计/平均", "", total_parts, "", total_disp,
            100.0 * total_disp / max(1, total_parts)))
    emit("  * 「零件」= kind=='part' 的条目；车体级类（Model_*/IVehicle_*）、车漆"
         "（IPaintjob_*）、贴纸（ISticker_*）、")
    emit("    几何/资源类与 *_Sounds 单列在下一张表，不计入零件数/命中率。")
    emit("")

    # 报告里所有「样例」统一用这一台车，避免行文里的车名与样例不符
    ref = None
    for v in cat.vehicles:
        if v.car == "Phoenix_RS_1997":
            ref = v
    if ref is None:
        ref = cat.vehicles[0]

    # VID 表 / 车索引（真字节码），后面任务 2、任务 3 的样例与值域自检都要用
    cat.load_vid_table()
    cat.match_car_index()

    # 每台车：类分布 + 车体级类识别
    emit("每台车的条目类别分布（车体级类已单列，不计入零件）：")
    emit("%-24s %6s %8s %8s %8s %8s %8s %8s"
         % ("车", "零件", "几何", "车漆", "贴纸", "Model", "IVehicle", "其它"))
    for v in cat.vehicles:
        kinds = {}
        for p in v.parts:
            kinds[p.kind] = kinds.get(p.kind, 0) + 1
        emit("%-24s %6d %8d %8d %8d %8d %8d %8d"
             % (v.car, kinds.get("part", 0), kinds.get("geometry", 0),
                kinds.get("paintjob", 0), kinds.get("sticker", 0),
                kinds.get("model", 0), kinds.get("vehicle", 0),
                kinds.get("sounds", 0)))
    emit("")
    emit("车体前缀 + 车体级类（识别结果）：")
    for v in cat.vehicles:
        emit("  %-24s prefix=%-14s models=%s ivhicles=%s"
             % (v.car, v.prefix, v.models, v.ivhicles))
    emit("")

    # 零件族清单（并集）
    fam_all = {}
    for v in cat.vehicles:
        for f in v.families():
            fam_all.setdefault(f, set()).add(v.car)
    emit("全部零件族（%d 个，列出出现该族的车数）：" % len(fam_all))
    for f in sorted(fam_all):
        emit("  %-20s %2d 台车" % (f, len(fam_all[f])))
    emit("")

    # 显示名来源分布（全部条目）+ 车名
    src_all = {}
    for v in cat.vehicles:
        for p in v.parts:
            src_all[p.display_source] = src_all.get(p.display_source, 0) + 1
    emit("显示名来源分布（全部 %d 个条目）：" % sum(src_all.values()))
    for k in sorted(src_all):
        emit("  %-24s %d" % (k, src_all[k]))
    emit("  * no-getName = 该类自己没覆盖 getName()，显示名由父类运行时给出，"
         "例如 java/game/item/IEngine.java:140 按 kind 返回 \"$21|Engine - Stage I\"；")
    emit("    IPart.java:35 则转发给 this.part[0].getName()。这属于父类逻辑，"
         "本模块按任务书要求填 None。")
    emit("")
    emit("车名（Model_* 自己的 getName() -> ModelName 静态字段）：")
    for v in cat.vehicles:
        mname = {p.name: p.display_name for p in v.parts if p.kind == "model"}
        emit("  %-24s %s" % (v.car, mname))
    emit("")
    emit("显示名样例（%s/%s，前 12 个有名字的零件）：" % (ref.car, ref.body))
    v0 = ref
    shown = 0
    for p in v0.parts:
        if p.display_name is not None and shown < 12:
            emit("  %-34s %-14s %-9s -> %r"
                 % (p.name, p.family, p.variant, p.display_name))
            shown += 1
    emit("")

    # ---------------- 任务 2 ----------------
    emit("-" * 78)
    emit("任务 2：零件 id -> 类名（Model_<Body>.getIPart 现场恢复 vs 伪码逐条比对）")
    emit("-" * 78)
    grand_ok = grand_tot = 0
    mismatch_all = []
    for v in cat.vehicles:
        rec, model_class = cat.getipart_map_for(v)
        ps, err = pseudo_getipart(v.car, v.body, model_class or "")
        if ps is None:
            emit("%-24s %-26s 伪码不可用：%s" % (v.car, model_class, err))
            continue
        both = set(rec) | set(ps)
        ok = sum(1 for k in both if rec.get(k) == ps.get(k))
        bad = sorted(k for k in both if rec.get(k) != ps.get(k))
        grand_ok += ok
        grand_tot += len(both)
        emit("%-24s %-26s 字节码 %3d 条 / 伪码 %3d 条 / 比对 %3d 条 / 匹配 %3d / 不匹配 %d"
             % (v.car, model_class, len(rec), len(ps), len(both), ok, len(bad)))
        if bad:
            for k in bad[:6]:
                emit("      ✗ case %-6d 字节码=%s 伪码=%s"
                     % (k, rec.get(k), ps.get(k)))
                mismatch_all.append((v.car, k, rec.get(k), ps.get(k)))
    emit("-" * 78)
    emit("合计：匹配 %d / 比对 %d 条（%.2f%%），不匹配 %d 条"
         % (grand_ok, grand_tot, 100.0 * grand_ok / max(1, grand_tot), len(mismatch_all)))
    emit("")

    # 追加：宽体（_WB）车体类的 Model_<Body>_WB 也走一遍同样流程
    emit("追加：宽体 Model_<Body>_WB 的 getIPart 同样比对（保存编辑器里 WB 是 VID 10..19）：")
    wb_ok = wb_tot = 0
    for v in cat.vehicles:
        wb = [nm for nm in v.models if nm.endswith("_WB")]
        if not wb:
            continue
        wb = wb[0]
        with zipfile.ZipFile(v.zip_path) as zf:
            for n in zf.namelist():
                if Path(n).stem == wb:
                    rec = getipart_map(cat.read_class(zf, n))
        ps, err = pseudo_getipart(v.car, v.body, wb)
        if ps is None:
            emit("  %-24s %-26s 伪码不可用：%s" % (v.car, wb, err))
            continue
        both = set(rec) | set(ps)
        ok = sum(1 for k in both if rec.get(k) == ps.get(k))
        wb_ok += ok
        wb_tot += len(both)
        emit("  %-24s %-26s 字节码 %3d / 伪码 %3d / 比对 %3d / 匹配 %3d / 不匹配 %d"
             % (v.car, wb, len(rec), len(ps), len(both), ok,
                len([k for k in both if rec.get(k) != ps.get(k)])))
    emit("  合计：匹配 %d / 比对 %d 条（%.2f%%）"
         % (wb_ok, wb_tot, 100.0 * wb_ok / max(1, wb_tot)))
    emit("")

    # 值域自检：case 必须能塞进 PART_BITS=16，车索引必须能塞进 VHC_BITS=13
    bad_case = []
    for v in cat.vehicles:
        rec, _m = cat.getipart_map_for(v)
        for k in rec:
            if not (0 <= k < (1 << PART_BITS)):
                bad_case.append((v.car, k))
    emit("值域自检：全部 case 值 %s（PART_BITS=16）"
         % ("都落在 0..65535 内 ✔" if not bad_case else "越界 %s" % bad_case))
    if cat.car_index:
        bad_idx = [(c, i) for c, i in cat.car_index.items() if not (0 <= i < (1 << VHC_BITS))]
        emit("          全部车索引 %s（VHC_BITS=13 -> 0..8191）"
             % ("都落在范围内 ✔" if not bad_idx else "越界 %s" % bad_idx))
    emit("")

    # 存档编辑器用的全量索引 + 往返自检
    idmap = build_id_index(cat)
    rt_ok = 0
    for pid in idmap:
        r = lookup_id(cat, pid)
        if r is not None and r[4] == idmap[pid][2]:
            rt_ok += 1
    emit("零件 id 全量索引：%d 条（10 台车主车体）。id -> 类名 往返自检 %d/%d 通过。"
         % (len(idmap), rt_ok, len(idmap)))
    emit("示例：id=%d -> %s；id=%d -> %s"
         % (part_id(0, 5), idmap.get(part_id(0, 5)),
            part_id(9, 7), idmap.get(part_id(9, 7))))
    emit("      lookup_id(%d) = %s" % (part_id(0, 5), lookup_id(cat, part_id(0, 5))))
    emit("")

    # 样例：参考车的前 10 条映射 + id
    v0 = ref
    rec0, model0 = cat.getipart_map_for(v0)
    idx0 = cat.car_index.get(v0.car)
    emit("样例：%s / %s（车索引 VID=%s）前 10 条 case 映射，含零件 id："
         % (v0.car, model0, idx0))
    for k in sorted(rec0)[:10]:
        pid = part_id(idx0, k) if idx0 is not None else None
        emit("  case %-6d -> %-64s id=%s" % (k, rec0[k], pid))
    emit("")

    # ---------------- 任务 3 ----------------
    emit("-" * 78)
    emit("任务 3：零件槽位名表（0..64）与 stage 映射")
    emit("-" * 78)
    st = slot_table()
    emit("槽数：%d，覆盖 %s" % (len(st), "0..64 连续" if sorted(st) == list(range(65))
                                else "有缺口：%s" % [i for i in range(65) if i not in st]))
    for i in range(65):
        e = st.get(i)
        if e is None:
            emit("  %2d  %-22s %s" % (i, "-", "?〔无 ITEMSLOT_* 常量〕"))
        else:
            emit("  %2d  %-22s %s" % (i, e["en"], e["cn"]))
    emit("")
    emit("IPL_UPGRADE_*：%s" % IPL_UPGRADE)
    emit("kind -> IPL：{0:'IPL_UPGRADE_STOCK'(1), 1..5:'IPL_UPGRADE_STAGE_I..V'(2..6)}")
    emit("")
    emit("stage 与零件 id 的关系（字节码实证，%s，前缀 %s）：" % (v0.car, v0.prefix))
    for variant in ("stock", "stage_I", "stage_II", "stage_III", "stage_IV"):
        nm = "%s_IEngine_%s" % (v0.prefix, variant)
        try:
            with zipfile.ZipFile(v0.zip_path) as zf:
                t = cat.read_class(zf, "classes/%s.class" % nm)
            k = class_ctor_kind(t)
            emit("  %-34s <init>() 传给 IEngine.<init>(I) 的 kind = %-4s -> IPL = %s"
                 % (nm, k, stage_of_kind(k) if k is not None else None))
        except KeyError:
            emit("  %-34s （该车无此类）" % nm)
    emit("")

    # ---------------- VID / 车索引 ----------------
    emit("-" * 78)
    emit("附：车索引（IVehicle.<clinit> 真字节码恢复的 VID_* 表）")
    emit("-" * 78)
    if cat.vid:
        for k in sorted(cat.vid, key=lambda x: (cat.vid[x], x)):
            emit("  VID=%-3d %s" % (cat.vid[k], k))
        emit("")
        emit("车目录 -> 车索引（按年份 + 名称 token 唯一最优匹配）：")
        for car in sorted(cat.car_index):
            emit("  %-24s VID = %d" % (car, cat.car_index[car]))
        amb = getattr(cat, "car_index_ambiguous", {})
        if amb:
            emit("  !! 歧义未定：%s" % amb)
    else:
        emit("  ✗ VID 表未取到")
    emit("")

    # ---------------- 结论 ----------------
    emit("=" * 78)
    emit("结论")
    emit("=" * 78)
    emit("1) 任务 1：10 台车共 %d 个普通零件类，其中 %d 个（%.1f%%）能从类自身的"
         % (total_parts, total_disp, 100.0 * total_disp / max(1, total_parts)))
    emit("   getName()Ljava.lang.String; 里直接取到显示名；另有 %d 个 Model_* 通过"
         % src_all.get("getName->ModelName", 0))
    emit("   getName() -> ModelName 拿到车名。取不到的（%d 个）原版类里没有 getName()，"
         % src_all.get("no-getName", 0))
    emit("   显示名由父类运行时给出（IEngine 按 kind 拼 \"$21|Engine - Stage I\" 之类），"
         "按任务书要求填 None。")
    emit("2) 任务 2：getIPart 的 {case: 零件类名} 全部从 TUFA 字节码现场恢复，逐条比对伪码：")
    emit("   10 台车主车体 %d/%d 匹配，10 台车宽体(_WB) %d/%d 匹配。"
         % (grand_ok, grand_tot, wb_ok, wb_tot))
    emit("   恢复规则：比较链里每个 ``05 <case>`` 后跟 ``1a <相对偏移>``，跳转目标 = 该 1a 指令")
    emit("   自身偏移 + payload；目标处若是 ``27 <常量池索引>`` 就是 NEW，pool.ref 给出类名；")
    emit("   若目标是 ``17 <相对偏移>`` 则是共享的「压 null + RETURN」尾巴（case 0 走这条）。")
    emit("3) 任务 3：槽位表 0..64 全部落在伪码头部（41 号槽在原版就没有 ITEMSLOT_* 常量名）；")
    emit("   stage 不编码在零件 id 的 case 值里：每个具体零件类把自己那档 kind 烘焙进自己的")
    emit("   <init>()（stock=0，stage_I..IV=1..4），IEngine.getStage() 直接返回它、")
    emit("   getPriority() 再映射到 IPL_UPGRADE_STAGE_I..V(2..6)，stock -> IPL_UPGRADE_STOCK(1)。")
    emit("")
    emit("不确定 / 需要额外确认（✗）")
    emit("  ✗ TYPE_IPART = 1<<29 是任务书给的约定，伪码里没有这条常量可直接印证；")
    emit("    能印证的只有位宽：IPart.PART_BITS=16 / ItemRoot.TYPE_BITS=3 /")
    emit("    IVehicle.VHC_BITS=32-3-16=13 / VHC_SHFT=PART_BITS=16（伪码头部常量）。")
    emit("  ✗ ITEMSLOT 41 号槽：0..64 里唯一没有常量名，语义未知（标 '?'）。")
    emit("  ✗ 少数中文译名标了 '?'（STYL_F_WING / STYL_STICKER_*_QUARTER），")
    emit("    英文常量名可靠，中文是按字面语义译的猜测。")
    emit("  ✗ Rim_ST（每台车一个）没按变体后缀拆：语料里只有 Rim_F_ST / Rim_R_ST /")
    emit("    Rim_U_ST 与之并列，'_ST' 从不作为独立后缀出现，故整段当族名，可能真意是 Rim+ST。")
    emit("  ✗ kind(0/1..5) 与 id 的关系是「间接」的：id 的 case 值不携带 stage，")
    emit("    要走 类名 -> <init>() 烘焙的 kind -> IPL_UPGRADE_* 这条链。")
    emit("")

    txt = "\n".join(out) + "\n"
    if report_path:
        Path(report_path).write_text(txt, encoding="utf-8")
    return out


if __name__ == "__main__":
    _rp = _HERE.parent / "out_catalog_report.txt"
    main(report_path=_rp)
    print("\n报告已写入 %s" % _rp)
