"""LASR 生涯存档（`save/career/NNN.sav`）读写核心。

本模块由伪码逐字复原，布局来源：
  * 外层容器 SDAT —— 由 `java.io.File.write/readString` 的调用序列 + 实际字节验证；
  * `java.game.Gamelogic.save/load`（L1358 / L1413）—— 主字段顺序；
  * `java.game.Player.save/load`（L662 / L711）—— 昵称 / 车辆 / 零件 / prestigeValues；
  * `java.game.RaceChronicle`（L1483 `saveChronicles`）—— 编年史 18 字段；
  * `java.game.item.ItemRoot` / `IPart` / `IVehicle` —— 物品 id 位域定义。

容器布局::

    "SDAT" | u32 0x00030100 | u32 fileSize | payload | 12 字节尾

其中 `fileSize` = **整个文件的字节数**（12 + len(payload) + 12），
后 12 字节尾在本作里固定为 8 个 0 字节 + u32(8)，但本模块**原样保留**不做推断。

payload 字段顺序（严格按 save() 的 write 顺序）::

    u32  SAVEFILEID_MAIN      = 0x97654301  (= -1754971391 的有符号表示)
    u32  SAVEFILEVERSION_MAIN = 16
    str  lastSaveTime          ; u32 长度 + 字节（长度含结尾 NUL）
    str  nickName              ; 同上
    u32  lastVehicle           ; 注意：这里存的是 **VID 索引**（0..22），不是完整物品 id
    u32  carCount              ; 只计非空车辆
      carCount × { u32 vehicleId
                   u32 partCount
                   partCount × { u32 partId, u32 status } }
    u32  prestigeValues[15]    ; 写盘顺序为 index 14 → 0（读回时按出现顺序存放）
    u32  pubIndex              ; 1-based（load 时 setCurrentPub(v-1)）
    u32  driverType            ; 0..7（IDriver.MAX=8 / Driver.drivers 有 8 项）
    u32  tuningPageIndex
    u32  carsOpen
    u32  tuningOpen
    u32  winSum
    u32  raceSum
    u32  retries
    u32  offeredRaces
    f32  aiLevelMul
    u32  chronicleCount
      chronicleCount × 18 字段（bestLapTime 为 f32，其余 u32）
    u32  bastardRaceFinished
    u32  trialsCompleted
    u32  trialProgress
    u32  trials[30]
    u32  prestige

物品 id 位域（来自 `ItemRoot.TYPE_*` / `IPart.PART_*` / `IVehicle.VHC_*`）::

     31        29 28                        16 15          0
    +-----------+------------------------------+-------------+
    | type(3)   | vehicle index (13)           | case(16)    |
    +-----------+------------------------------+-------------+
      type:  车辆/零件 = IVehicle.VHC_PRID = 1
    车辆 id = (1 << 29) | (vehicle_index << 16)
    零件 id = (1 << 29) | (vehicle_index << 16) | case_value
"""
from __future__ import annotations

import math
import struct
import sys
from pathlib import Path

# --------------------------------------------------------------------------- #
# 常量
# --------------------------------------------------------------------------- #

MAGIC = b"SDAT"
SDAT_VERSION = 0x00030100
HEADER_LEN = 12                      # "SDAT" + u32 版本 + u32 fileSize
TRAILER_LEN = 12                     # 固定 12 字节尾
DEFAULT_TRAILER = b"\x00" * 8 + struct.pack("<I", 8)
SAVEFILEID_MAIN = 0x97654301
SAVEFILEVERSION_MAIN = 16
PRESTIGE_VECTOR_SIZE = 15
TRIAL_COUNT = 30
DRIVER_COUNT = 8                     # IDriver.MAX / len(Driver.drivers)

# RaceChronicle.save 的 18 个字段（写盘顺序）
CHRONICLE_FIELDS = (
    "splineLeft", "crashes", "won", "rescue", "repair", "bestLapTime",
    "pushes", "trackID", "TOD", "laps", "mycar", "mystage", "opcar",
    "opstage", "pinks", "prestige", "opstatus", "oprank",
)
CHRONICLE_FLOAT_FIELDS = frozenset({"bestLapTime"})

# --------------------------------------------------------------------------- #
# 车辆索引表（抄自 out_pseudo/java/classes/game/item/IVehicle.java 的 VID_* 常量）
# --------------------------------------------------------------------------- #

VID_CAREER_MAX = 10                  # 前 10 台为职业可用车（含 0..9）
VID_MAX = 23                         # 0..22 共 23 台（含 10 台 _WB 宽体 + 3 台特殊车）

VID_NAMES = {
    0: "VID_97_Phoenix_RS",
    1: "VID_83_Phoenix_Trend",
    2: "VID_05_Invictus_Corus_S2",
    3: "VID_06_Fujin_MX",
    4: "VID_94_Invictus_Quaddro_SD_T5",
    5: "VID_97_Raptor_ZX",
    6: "VID_06_Hornet_Wega",
    7: "VID_04_Takura_Cyclone_R",
    8: "VID_02_Takura_Tornado_R",
    9: "VID_03_NSR_Dragon_S",
    10: "VID_97_Phoenix_RS_WB",
    11: "VID_83_Phoenix_Trend_WB",
    12: "VID_05_Invictus_Corus_S2_WB",
    13: "VID_06_Fujin_MX_WB",
    14: "VID_94_Invictus_Quaddro_SD_T5_WB",
    15: "VID_97_Raptor_ZX_WB",
    16: "VID_06_Hornet_Wega_WB",
    17: "VID_04_Takura_Cyclone_R_WB",
    18: "VID_02_Takura_Tornado_R_WB",
    19: "VID_03_NSR_Dragon_S_WB",
    20: "VID_06_Fujin_MX_Matt_Peacock",
    21: "VID_06_Hornet_Wega_Stan_Karew",
    22: "VID_97_Raptor_ZX_Ted_Cutter",
}

# --------------------------------------------------------------------------- #
# 物品 id 位域
# --------------------------------------------------------------------------- #

TYPE_BITS = 3
TYPE_SHFT = 32 - TYPE_BITS           # 29
TYPE_MASK = ((1 << TYPE_BITS) - 1) << TYPE_SHFT          # 0xE0000000
PART_BITS = 16
PART_SHFT = 0
PART_MASK = ((1 << PART_BITS) - 1) << PART_SHFT          # 0x0000FFFF
VHC_SHFT = PART_BITS                 # 16
VHC_BITS = 32 - TYPE_BITS - PART_BITS                    # 13
VHC_MASK = ((1 << VHC_BITS) - 1) << VHC_SHFT             # 0x1FFF0000
PRID_VEHICLE = 1                     # IVehicle.VHC_PRID


class SaveError(Exception):
    """存档结构不符合预期时抛出。"""


# --------------------------------------------------------------------------- #
# 车辆 / 零件 id 工具函数
# --------------------------------------------------------------------------- #

def make_vehicle_id(vehicle_index: int) -> int:
    """由 VID 索引拼出车辆物品 id：`(1<<29) | (index<<16)`。"""
    _check_index(vehicle_index)
    return (PRID_VEHICLE << TYPE_SHFT) | (vehicle_index << VHC_SHFT)


def make_part_id(vehicle_index: int, case_value: int) -> int:
    """由 (车辆索引, 零件 case 值) 拼出零件物品 id。

    等价于 Java 里的 `vehicle.getId() | (caseValue << IPart.PART_SHFT)`。
    """
    _check_index(vehicle_index)
    if not 0 <= case_value <= PART_MASK:
        raise ValueError("case_value 超出 16 位范围: %r" % (case_value,))
    return (PRID_VEHICLE << TYPE_SHFT) | (vehicle_index << VHC_SHFT) | (case_value & PART_MASK)


def split_id(item_id: int):
    """拆解任意物品 id -> (type, vehicle_index, case_value)。

    对车辆物品 id 来说 case_value 恒为 0；type 为顶部 3 位（车辆/零件 = 1）。
    """
    item_id &= 0xFFFFFFFF
    return ((item_id & TYPE_MASK) >> TYPE_SHFT,
            (item_id & VHC_MASK) >> VHC_SHFT,
            (item_id & PART_MASK) >> PART_SHFT)


def vehicle_index_of(item_id: int) -> int:
    """取物品 id 里的车辆索引（等价 IVehicle.extractIndex）。"""
    return (item_id & VHC_MASK) >> VHC_SHFT


def item_type_of(item_id: int) -> int:
    """取物品 id 的 type 位（等价 ItemRoot 的 primary id）。"""
    return (item_id & TYPE_MASK) >> TYPE_SHFT


def is_vehicle_id(item_id: int) -> bool:
    """判断是否为车辆物品 id（type==1 且 case 位为 0）。"""
    return item_type_of(item_id) == PRID_VEHICLE and (item_id & PART_MASK) == 0


def is_part_id(item_id: int) -> bool:
    """判断是否为零件物品 id（type==1 且 case 位非 0）。"""
    return item_type_of(item_id) == PRID_VEHICLE and (item_id & PART_MASK) != 0


def vehicle_name(vehicle_index: int) -> str:
    """VID 索引 -> 车名常量；未知返回 `VID_<idx>_<unknown>`。"""
    return VID_NAMES.get(vehicle_index, "VID_%d_<unknown>" % vehicle_index)


def _check_index(vehicle_index: int) -> None:
    if not 0 <= vehicle_index < VID_MAX:
        raise ValueError("车辆索引超出 0..%d: %r" % (VID_MAX - 1, vehicle_index))


# --------------------------------------------------------------------------- #
# 底层 读 / 写
# --------------------------------------------------------------------------- #

class Reader:
    """小端字节流游标。"""

    def __init__(self, data: bytes, pos: int = 0):
        self.d = data
        self.p = pos

    def take(self, n: int) -> bytes:
        if self.p + n > len(self.d):
            raise SaveError("读取越界：需要 %d 字节，仅剩 %d" % (n, len(self.d) - self.p))
        out = self.d[self.p:self.p + n]
        self.p += n
        return out

    def u32(self) -> int:
        return struct.unpack("<I", self.take(4))[0]

    def i32(self) -> int:
        return struct.unpack("<i", self.take(4))[0]

    def f32(self) -> float:
        return struct.unpack("<f", self.take(4))[0]

    def string(self):
        """读一个带 u32 长度的字符串；返回 (文本, 原始字节) 以便逐字节回写。"""
        n = self.u32()
        if n == 0:
            return "", b""
        raw = self.take(n)
        text = raw.split(b"\x00", 1)[0].decode("latin-1")
        return text, raw


class Writer:
    """小端字节流累加器。"""

    def __init__(self):
        self.out = bytearray()

    def u32(self, v: int) -> None:
        self.out += struct.pack("<I", v & 0xFFFFFFFF)

    def i32(self, v: int) -> None:
        self.out += struct.pack("<i", v)

    def f32(self, v: float) -> None:
        self.out += struct.pack("<f", v)

    def string(self, text: str, raw: bytes | None = None) -> None:
        """写字符串。若 `raw` 与当前文本编码一致则原样写回（保证零改动字节级复现）。"""
        enc = _encode_string(text)
        payload = raw if (raw is not None and enc == raw) else enc
        self.u32(len(payload))
        self.out += payload


def _encode_string(text: str) -> bytes:
    """按游戏的 writeString 约定编码：文本 + NUL；空串写成长度 0。"""
    if text == "":
        return b""
    return text.encode("latin-1") + b"\x00"


# --------------------------------------------------------------------------- #
# 容器 拆 / 装
# --------------------------------------------------------------------------- #

def unwrap(blob: bytes):
    """拆开 SDAT 容器 -> (版本, 声明大小, payload, 12 字节尾)。"""
    if len(blob) < HEADER_LEN + TRAILER_LEN:
        raise SaveError("文件过短，不足 SDAT 头 + 尾：%d 字节" % len(blob))
    if blob[:4] != MAGIC:
        raise SaveError("不是 LASR SDAT 文件（magic=%r）" % blob[:4])
    ver, size = struct.unpack_from("<II", blob, 4)
    if ver != SDAT_VERSION:
        raise SaveError("未知 SDAT 版本 0x%08x（期望 0x%08x）" % (ver, SDAT_VERSION))
    trailer = blob[len(blob) - TRAILER_LEN:]
    payload = blob[HEADER_LEN:len(blob) - TRAILER_LEN]
    return ver, size, payload, trailer


def wrap(payload: bytes, trailer: bytes) -> bytes:
    """把 payload + 尾装回 SDAT 容器，并重算 fileSize 字段。"""
    if len(trailer) != TRAILER_LEN:
        raise SaveError("尾长度必须为 %d，实际 %d" % (TRAILER_LEN, len(trailer)))
    total = HEADER_LEN + len(payload) + TRAILER_LEN
    return MAGIC + struct.pack("<II", SDAT_VERSION, total) + payload + trailer


# --------------------------------------------------------------------------- #
# 解析 / 生成
# --------------------------------------------------------------------------- #

def loads(blob: bytes) -> dict:
    """把整个 SDAT 字节串解析成字典（含 `_` 前缀的内部字段）。"""
    ver, size, payload, trailer = unwrap(blob)
    r = Reader(payload)

    fid = r.u32()
    if fid != SAVEFILEID_MAIN:
        raise SaveError("SAVEFILEID 不符：0x%08x（期望 0x%08x）" % (fid, SAVEFILEID_MAIN))
    fver = r.u32()
    if fver != SAVEFILEVERSION_MAIN:
        raise SaveError("SAVEFILEVERSION 不符：%d（期望 %d）" % (fver, SAVEFILEVERSION_MAIN))

    s = {
        "sdat_version": ver,
        "declared_file_size": size,
        "_trailer": trailer,
        "_raw_strings": {},
    }

    t, raw = r.string()
    s["lastSaveTime"] = t
    s["_raw_strings"]["lastSaveTime"] = raw
    t, raw = r.string()
    s["nickName"] = t
    s["_raw_strings"]["nickName"] = raw

    s["lastVehicle"] = r.u32()

    cars = []
    for _ in range(r.u32()):
        vid = r.u32()
        parts = []
        for _ in range(r.u32()):
            parts.append([r.u32(), r.u32()])       # [partId, status]
        cars.append({"vehicle": vid, "parts": parts})
    s["cars"] = cars

    s["prestigeValues"] = [r.u32() for _ in range(PRESTIGE_VECTOR_SIZE)]
    s["pubIndex"] = r.u32()
    s["driverType"] = r.u32()
    s["tuningPageIndex"] = r.u32()
    s["carsOpen"] = r.u32()
    s["tuningOpen"] = r.u32()
    s["winSum"] = r.u32()
    s["raceSum"] = r.u32()
    s["retries"] = r.u32()
    s["offeredRaces"] = r.u32()
    s["aiLevelMul"] = r.f32()

    chron = []
    for _ in range(r.u32()):
        rec = {}
        for k in CHRONICLE_FIELDS:
            rec[k] = r.f32() if k in CHRONICLE_FLOAT_FIELDS else r.u32()
        chron.append(rec)
    s["chronicles"] = chron

    s["bastardRaceFinished"] = r.u32()
    s["trialsCompleted"] = r.u32()
    s["trialProgress"] = r.u32()
    s["trials"] = [r.u32() for _ in range(TRIAL_COUNT)]
    s["prestige"] = r.u32()

    s["consumed"] = r.p
    s["payload_size"] = len(payload)
    return s


def load(path) -> dict:
    """读取并解析一个生涯存档文件。"""
    return loads(Path(path).read_bytes())


def build(s: dict) -> bytes:
    """把 `load()` 得到的字典（或手工构造的等价字典）序列化回完整 SDAT 文件。

    未修改的字段会逐字节还原；fileSize 字段重算；尾 12 字节原样保留。
    """
    w = Writer()
    raw_strings = s.get("_raw_strings", {})

    w.u32(SAVEFILEID_MAIN)
    w.u32(SAVEFILEVERSION_MAIN)
    w.string(s.get("lastSaveTime", ""), raw_strings.get("lastSaveTime"))
    w.string(s.get("nickName", ""), raw_strings.get("nickName"))
    w.u32(s.get("lastVehicle", 0))

    cars = s["cars"]
    w.u32(len(cars))
    for c in cars:
        w.u32(c["vehicle"])
        parts = c["parts"]
        w.u32(len(parts))
        for pid, status in parts:
            w.u32(pid)
            w.u32(status)

    pv = list(s["prestigeValues"])
    if len(pv) != PRESTIGE_VECTOR_SIZE:
        raise SaveError("prestigeValues 长度必须为 %d，实际 %d"
                        % (PRESTIGE_VECTOR_SIZE, len(pv)))
    for v in pv:
        w.u32(v)

    w.u32(s["pubIndex"])
    w.u32(s["driverType"])
    w.u32(s["tuningPageIndex"])
    w.u32(s["carsOpen"])
    w.u32(s["tuningOpen"])
    w.u32(s["winSum"])
    w.u32(s["raceSum"])
    w.u32(s["retries"])
    w.u32(s["offeredRaces"])
    w.f32(s["aiLevelMul"])

    chron = s["chronicles"]
    w.u32(len(chron))
    for rec in chron:
        for k in CHRONICLE_FIELDS:
            (w.f32 if k in CHRONICLE_FLOAT_FIELDS else w.u32)(rec[k])

    w.u32(s["bastardRaceFinished"])
    w.u32(s["trialsCompleted"])
    w.u32(s["trialProgress"])
    trials = list(s["trials"])
    if len(trials) != TRIAL_COUNT:
        raise SaveError("trials 长度必须为 %d，实际 %d" % (TRIAL_COUNT, len(trials)))
    for v in trials:
        w.u32(v)
    w.u32(s["prestige"])

    trailer = s.get("_trailer") or DEFAULT_TRAILER
    return wrap(bytes(w.out), trailer)


def dumps(s: dict) -> bytes:
    """`build()` 的别名。"""
    return build(s)


def save(s: dict, path, backup: bool = True):
    """把字典写回文件；默认先把原文件另存为 `<path>.bak`（只在 .bak 不存在时创建）。"""
    path = Path(path)
    blob = build(s)
    backup_path = None
    if backup and path.exists():
        cand = Path(str(path) + ".bak")
        if not cand.exists():
            cand.write_bytes(path.read_bytes())
        backup_path = cand
    path.write_bytes(blob)
    return path, backup_path


# --------------------------------------------------------------------------- #
# 校验（只报可疑，不阻止保存）
# --------------------------------------------------------------------------- #

def validate(s: dict):
    """对解析结果做一致性检查，返回中文警告字符串列表（空表示未见异常）。"""
    w = []

    if len(s.get("prestigeValues", [])) != PRESTIGE_VECTOR_SIZE:
        w.append("prestigeValues 长度 %d != %d" % (len(s.get("prestigeValues", [])), PRESTIGE_VECTOR_SIZE))
    if len(s.get("trials", [])) != TRIAL_COUNT:
        w.append("trials 长度 %d != %d" % (len(s.get("trials", [])), TRIAL_COUNT))

    # 车辆索引与 id 位域
    lv = s.get("lastVehicle", 0)
    if not 0 <= lv < VID_MAX:
        w.append("lastVehicle=%d 超出车辆索引范围 0..%d" % (lv, VID_MAX - 1))

    seen = set()
    for i, c in enumerate(s.get("cars", [])):
        vid = c["vehicle"]
        t, idx, case = split_id(vid)
        if t != PRID_VEHICLE:
            w.append("车[%d] id=0x%08x type=%d 应为 1（IVehicle.VHC_PRID）" % (i, vid, t))
        if idx >= VID_MAX:
            w.append("车[%d] id=0x%08x 车辆索引 %d >= %d（越界）" % (i, vid, idx, VID_MAX))
        if case != 0:
            w.append("车[%d] id=0x%08x 低位 case=%d 应为 0（车辆 id 不带零件槽）" % (i, vid, case))
        if idx in seen:
            w.append("车[%d] id=0x%08x 车辆索引 %d 与前车重复" % (i, vid, idx))
        seen.add(idx)

        if not (0 <= len(c["parts"]) <= PART_MASK):
            w.append("车[%d] 零件数 %d 异常" % (i, len(c["parts"])))
        for j, (pid, status) in enumerate(c["parts"]):
            pt, pidx, pcase = split_id(pid)
            if pt != PRID_VEHICLE:
                w.append("车[%d] 零件[%d] id=0x%08x type=%d 应为 1" % (i, j, pid, pt))
            if not 0 <= pcase <= PART_MASK:
                w.append("车[%d] 零件[%d] id=0x%08x case=%d 超出 0..%d"
                         % (i, j, pid, pcase, PART_MASK))
            if pidx != idx:
                w.append("车[%d] 零件[%d] id=0x%08x 的车辆索引 %d 与所属车 %d 不一致"
                         % (i, j, pid, pidx, idx))
            if status not in (0, 1):
                w.append("车[%d] 零件[%d] status=%d 非 0/1" % (i, j, status))

    if len(s.get("cars", [])) == 0:
        w.append("车辆列表为空（存档没有任何车）")

    # 比赛计数
    win, race = s.get("winSum", 0), s.get("raceSum", 0)
    if win > race:
        w.append("winSum(%d) > raceSum(%d)：胜场不应多于总场次" % (win, race))
    if s.get("retries", 0) > 1000000:
        w.append("retries=%d 异常偏大" % s.get("retries", 0))

    # 数值符号/范围（字段以 u32 存储，若语义为有符号则 >0x7FFFFFFF 即视为负数）
    if s.get("prestige", 0) > 0x7FFFFFFF:
        w.append("prestige=%d 作为有符号数时为负" % s.get("prestige", 0))
    for i, v in enumerate(s.get("prestigeValues", [])):
        if v > 0x7FFFFFFF:
            w.append("prestigeValues[%d]=%d 作为有符号数时为负" % (i, v))

    # 菜单 / 车手 / 酒馆
    if s.get("driverType", 0) >= DRIVER_COUNT:
        w.append("driverType=%d 超出 0..%d（IDriver.MAX=%d）"
                 % (s.get("driverType", 0), DRIVER_COUNT - 1, DRIVER_COUNT))
    if s.get("pubIndex", 0) == 0:
        w.append("pubIndex=0：load 时会 setCurrentPub(-1)，可疑")

    # 试验进度
    if s.get("trialsCompleted", 0) > TRIAL_COUNT:
        w.append("trialsCompleted=%d > %d" % (s.get("trialsCompleted", 0), TRIAL_COUNT))
    if s.get("trialProgress", 0) > TRIAL_COUNT:
        w.append("trialProgress=%d > %d" % (s.get("trialProgress", 0), TRIAL_COUNT))
    for i, v in enumerate(s.get("trials", [])):
        if v not in (0, 1):
            w.append("trials[%d]=%d 非 0/1" % (i, v))

    # AI 难度倍数
    ai = s.get("aiLevelMul", 0.0)
    if not math.isfinite(ai):
        w.append("aiLevelMul=%r 非有限数" % ai)
    elif ai <= 0.0:
        w.append("aiLevelMul=%r <= 0" % ai)

    # 编年史
    for i, rec in enumerate(s.get("chronicles", [])):
        lap = rec.get("bestLapTime", 0.0)
        if not math.isfinite(lap):
            w.append("chronicles[%d].bestLapTime=%r 非有限数" % (i, lap))
        elif lap < 0.0:
            w.append("chronicles[%d].bestLapTime=%r 为负" % (i, lap))

    return w


# --------------------------------------------------------------------------- #
# 一致性 / 自检工具
# --------------------------------------------------------------------------- #

def first_diff(a: bytes, b: bytes):
    """返回 (偏移, a字节, b字节)；完全相同返回 None。"""
    n = min(len(a), len(b))
    for i in range(n):
        if a[i] != b[i]:
            return i, a[i], b[i]
    if len(a) != len(b):
        return n, None, None
    return None


def roundtrip_report(path) -> dict:
    """对单个存档做「零改动回写」一致性检查，返回报告字典。"""
    blob = Path(path).read_bytes()
    s = loads(blob)
    rebuilt = build(s)
    d = first_diff(blob, rebuilt)
    return {
        "path": str(path),
        "original_len": len(blob),
        "rebuilt_len": len(rebuilt),
        "byte_identical": blob == rebuilt,
        "first_diff": d,
        "consumed": s["consumed"],
        "payload_size": s["payload_size"],
        "declared_file_size": s["declared_file_size"],
    }


def describe(s: dict, verbose: bool = True) -> str:
    """把解析结果渲染成人类可读文本。"""
    L = []
    L.append("== %s" % s.get("_path", "?"))
    L.append("   SDAT 版本      0x%08x  声明 fileSize %d" % (s["sdat_version"], s["declared_file_size"]))
    L.append("   payload %d 字节，已消耗 %d 字节%s"
             % (s["payload_size"], s["consumed"],
                "" if s["consumed"] == s["payload_size"] else "  <-- 不匹配!"))
    L.append("   lastSaveTime   %r" % s["lastSaveTime"])
    L.append("   nickName       %r" % s["nickName"])
    lv = s["lastVehicle"]
    L.append("   lastVehicle    %d (%s)" % (lv, vehicle_name(lv)))
    L.append("   pubIndex       %d   driverType %d   tuningPageIndex %d"
             % (s["pubIndex"], s["driverType"], s["tuningPageIndex"]))
    L.append("   carsOpen %d  tuningOpen %d  winSum %d  raceSum %d  retries %d  offeredRaces %d"
             % (s["carsOpen"], s["tuningOpen"], s["winSum"], s["raceSum"], s["retries"], s["offeredRaces"]))
    L.append("   aiLevelMul     %r" % s["aiLevelMul"])
    L.append("   prestige       %d" % s["prestige"])
    L.append("   bastardRaceFinished %d  trialsCompleted %d  trialProgress %d"
             % (s["bastardRaceFinished"], s["trialsCompleted"], s["trialProgress"]))
    L.append("   prestigeValues %s" % s["prestigeValues"])
    L.append("   车辆 %d 台:" % len(s["cars"]))
    for i, c in enumerate(s["cars"]):
        t, idx, case = split_id(c["vehicle"])
        L.append("     [%d] id=0x%08x type=%d idx=%d (%s)  零件 %d"
                 % (i, c["vehicle"], t, idx, vehicle_name(idx), len(c["parts"])))
        if verbose:
            for j, (pid, st) in enumerate(c["parts"]):
                pt, pidx, pcase = split_id(pid)
                L.append("          part[%d] id=0x%08x type=%d vidx=%d case=%d status=%d"
                         % (j, pid, pt, pidx, pcase, st))
    L.append("   编年史 %d 条" % len(s["chronicles"]))
    return "\n".join(L)


# --------------------------------------------------------------------------- #
# 自检：零改动回写 + 局部修改只影响目标字节
# --------------------------------------------------------------------------- #

def selftest(path, workdir=None) -> int:
    """真实执行的自检，返回退出码（0 = 全部通过）。

    1. load → build 应与原文件逐字节相同；
    2. 在内存里改两个同宽字段（retries、nickName 同长度），回写后只应差这些字节，
       且 fileSize 保持不变；改长昵称后 fileSize 应相应增大。
    """
    import shutil
    import tempfile

    src = Path(path)
    blob = src.read_bytes()
    ok = True

    print("### 自检 1：零改动回写逐字节一致")
    rep = roundtrip_report(src)
    print("   原文件 %d 字节 / 回写 %d 字节 / payload %d 消耗 %d"
          % (rep["original_len"], rep["rebuilt_len"], rep["payload_size"], rep["consumed"]))
    if rep["byte_identical"]:
        print("   [PASS] build(load(x)) == x，逐字节完全一致")
    else:
        print("   [FAIL] 字节不一致，首处偏移 %r" % (rep["first_diff"],))
        ok = False

    print("### 自检 2：局部修改只影响目标字节")
    s = loads(blob)
    old_retries = s["retries"]
    s["retries"] = (old_retries + 1) & 0xFFFFFFFF
    old_nick = s["nickName"]
    if len(old_nick) >= 1:
        # 改同长度昵称（大小写互换首字符），避免整体位移
        c0 = old_nick[0]
        s["nickName"] = ("z" if c0.islower() or c0.isalpha() else "z") + old_nick[1:]
    rebuilt = build(s)
    diffs = [i for i in range(min(len(blob), len(rebuilt))) if blob[i] != rebuilt[i]]
    print("   改动 retries %d->%d，nickName %r->%r"
          % (old_retries, s["retries"], old_nick, s["nickName"]))
    print("   差异字节数 %d，偏移 %s，长度 %d->%d"
          % (len(diffs), diffs, len(blob), len(rebuilt)))
    if len(rebuilt) == len(blob) and 1 <= len(diffs) <= 5:
        print("   [PASS] 仅目标字节变化，fileSize 不变（%d）" % rep["declared_file_size"])
    else:
        print("   [FAIL] 差异范围不符合预期")
        ok = False

    print("### 自检 3：改动长度后 fileSize 重算")
    s2 = loads(blob)
    s2["nickName"] = s2["nickName"] + "_XX"
    rebuilt2 = build(s2)
    declared = struct.unpack_from("<I", rebuilt2, 8)[0]
    print("   原 %d 字节 -> 新 %d 字节；头部 fileSize=%d（应等于文件长度 %d）"
          % (len(blob), len(rebuilt2), declared, len(rebuilt2)))
    if declared == len(rebuilt2) and len(rebuilt2) == len(blob) + 3:
        print("   [PASS] fileSize 已重算且增量正确")
    else:
        print("   [FAIL] fileSize 或长度增量不符")
        ok = False

    print("### 自检 4：写盘往返（写临时文件再读回）")
    tmpdir = Path(workdir) if workdir else Path(tempfile.mkdtemp(prefix="lasr_sav_"))
    tmpdir.mkdir(parents=True, exist_ok=True)
    dst = tmpdir / "001.sav"
    dst.write_bytes(blob)
    save(s2, dst, backup=True)
    back = load(dst)
    if back["nickName"] == s2["nickName"] and dst.with_suffix(".sav.bak").exists():
        print("   [PASS] 写盘后读回昵称一致，且生成了 .bak 备份")
    else:
        print("   [FAIL] 写盘往返异常")
        ok = False

    print("### 自检 5：id 工具函数")
    checks = []
    checks.append(("make_vehicle_id(1)", make_vehicle_id(1), 0x20010000))
    checks.append(("make_part_id(1, 5)", make_part_id(1, 5), 0x20010005))
    checks.append(("split_id(0x20010005)", split_id(0x20010005), (1, 1, 5)))
    checks.append(("vehicle_name(1)", vehicle_name(1), "VID_83_Phoenix_Trend"))
    for name, got, want in checks:
        status = "PASS" if got == want else "FAIL"
        if got != want:
            ok = False
        print("   [%s] %s = %r (want %r)" % (status, name, got, want))

    print("\n=> 自检结果：%s" % ("全部通过" if ok else "有失败项"))
    return 0 if ok else 1


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    verbose = True
    selftest_mode = False
    paths = []
    for a in argv:
        if a in ("-q", "--quiet"):
            verbose = False
        elif a == "--selftest":
            selftest_mode = True
        elif a in ("-h", "--help"):
            print(__doc__)
            print("用法: python -m editors.lasr_core.savefile <路径> [<路径>...] [--selftest] [-q]")
            return 0
        else:
            paths.append(a)

    if not paths:
        print("用法: python -m editors.lasr_core.savefile <存档路径> [--selftest] [-q]")
        return 2

    rc = 0
    for p in paths:
        print("=" * 70)
        try:
            blob = Path(p).read_bytes()
        except OSError as e:
            print("!! 无法读取 %s: %s" % (p, e))
            rc = 1
            continue
        try:
            s = loads(blob)
        except SaveError as e:
            print("!! %s 解析失败: %s" % (p, e))
            rc = 1
            continue
        s["_path"] = p
        print(describe(s, verbose=verbose))

        # 零改动回写一致性
        rebuilt = build(s)
        d = first_diff(blob, rebuilt)
        same = blob == rebuilt
        print("-" * 70)
        print("零改动回写: 原 %d 字节 -> 新 %d 字节  |  逐字节一致: %s"
              % (len(blob), len(rebuilt), same))
        if not same:
            print("   首个差异偏移: %r" % (d,))
            rc = 1

        warns = validate(s)
        print("校验: %s" % ("未见异常" if not warns else "%d 条警告" % len(warns)))
        for w in warns:
            print("   [!] %s" % w)

        if selftest_mode:
            print("=" * 70)
            rc |= selftest(p)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
