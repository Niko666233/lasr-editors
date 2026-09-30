"""`configureType("…")` 字符串里的参数：解析 + **原地**改值。

为什么需要它：零件的很多物理量不在 INT/FLOAT 字面量里，而在常量池的
configureType 字符串里 —— 例如碰撞体质量（`body` 的第 7 个 float = kg，
减重件/保险杠/引擎盖的重量就在这）、尾翼气动系数（`wing`）、零件挂点（`slot`）。
「全部数值」页只看字面量，所以这些值以前一行都看不到（见 docs/61）。

改法**只做同长度原地替换**：把新数字写回原来那几个字节，短了就补空格
（游戏的解析器是 `sscanf` 风格，会跳过多余空白），因此文件长度、常量池
条目数、所有偏移都不变 —— 不需要重序列化容器。新值比原值长就拒绝。

    from lasr_core import cfgstr, tufa
    t = tufa.Tufa(open(path, "rb").read())
    for cfg in cfgstr.parse(t):
        print(cfg.key, cfg.comment, [tk.text for tk in cfg.tokens])
"""
import re

from . import tufa as _tufa

# ---------------------------------------------------------------- 字段表
# key -> 该行「数值 token」按出现顺序的中文名。数量比表长时用通用名补齐。
# ★ = 会进物理/性能的量。
SCHEMA = {
    "body": ["位置 X", "位置 Y", "位置 Z", "旋转 X", "旋转 Y", "旋转 Z",
             "★质量 (kg)", "尺寸 1", "尺寸 2", "尺寸 3", "尺寸 4"],
    "wing": ["气动类型", "位置 X", "位置 Y", "位置 Z", "方向 X", "方向 Y",
             "方向 Z", "★系数 1", "★系数 2"],
    "slot": ["挂点 X", "挂点 Y", "挂点 Z", "旋转 X", "旋转 Y", "旋转 Z",
             "物理槽 id"],
    "damage": ["★损伤系数"],
    "flexible": ["★形变系数", "★阻尼"],
    "lod": ["起始 LOD", "结束 LOD"],
    "lods": ["LOD 级数", "距离 1", "距离 2", "距离 3", "距离 4", "距离 5",
             "距离 6", "标志位"],
    "use_mesh": ["网格序号", "布尔"],
    "flags": ["标志位"],
    "slottype": ["槽类型"],
    "slotdmgmode": ["槽损伤模式"],
    "slotdeform": ["槽形变"],
    "dirt_texture": ["污渍组", "贴图数量", "贴图 id"],
    "camera": ["位置 X", "位置 Y", "位置 Z", "旋转 X", "旋转 Y", "旋转 Z",
               "FOV", "参数 1", "参数 2", "参数 3", "参数 4"],
    "ext_camera": ["FOV", "座舱位 X", "座舱位 Y", "座舱位 Z", "注视点 X",
                   "注视点 Y", "注视点 Z", "视点 X", "视点 Y", "视点 Z",
                   "参数"],
    "wheel": ["位置 X", "位置 Y", "位置 Z", "旋转 X", "旋转 Y", "旋转 Z",
              "缩放 X", "缩放 Y", "缩放 Z", "缩放 W"],
    "maxsteer": ["★最大转向角", "★转向速率", "★速度相关"],
    "steerhelp": ["★助力 1", "★助力 2", "★助力 3", "★助力 4", "★助力 5",
                  "★助力 6"],
    "steerspeed": ["★转向速度 1", "★转向速度 2", "★转向速度 3"],
    "spring": ["★弹簧刚度", "★阻尼", "★行程"],
    "flap": ["位置 X", "位置 Y", "位置 Z", "方向 X", "方向 Y", "方向 Z",
             "法线 X", "法线 Y", "法线 Z", "参数 1", "参数 2"],
    "steering": ["位置 X", "位置 Y", "位置 Z", "旋转 X", "旋转 Y", "旋转 Z",
                 "半径"],
    "seat": ["位置 X", "位置 Y", "位置 Z", "旋转 X", "旋转 Y", "旋转 Z"],
    "shifter": ["位置 X", "位置 Y", "位置 Z", "旋转 X", "旋转 Y", "旋转 Z"],
    "pedals": ["位置 X", "位置 Y", "位置 Z", "参数"],
    "controller": ["控制器项"],
    "cockpit_rpm": ["仪表 RPM 源"],
    "cockpit_speed": ["仪表速度源"],
}

# key -> 这行是干什么的（界面里显示在「作用」列）
NOTE = {
    "body": "碰撞体：位置/旋转 + ★质量(kg) + 形状 + 尺寸。零件有多重就看「★质量」"
            "—— 减重件(WeightReduction)、保险杠、引擎盖、车门等的质量都在这里。",
    "wing": "气动点：类型(4=升力面 5=其它) + 位置/方向 + 两个系数。尾翼/前杠的气动就是这两条系数。",
    "slot": "零件挂点：位置/旋转 + 物理槽 id（装到这槽的零件会挂在这）。",
    "damage": "损伤系数（越大越容易撞坏）。",
    "flexible": "形变材质参数（软硬/回弹）。",
    "lod": "LOD 起止级别。",
    "lods": "LOD 各级切换距离 + 标志位。",
    "use_mesh": "用哪个网格 / 是否启用。",
    "flags": "标志位（渲染/损伤层的开关，语义未完）。",
    "slottype": "槽类型。",
    "slotdmgmode": "槽的损伤模式。",
    "slotdeform": "槽形变开关。",
    "dirt_texture": "污渍贴图组。",
    "camera": "相机位（车外跟车）。",
    "ext_camera": "座舱/车内视角。",
    "wheel": "车轮挂点位置/旋转/缩放。",
    "maxsteer": "★转向：最大转角 / 速率 / 速度相关项。",
    "steerhelp": "★转向助力参数。",
    "steerspeed": "★转向速率曲线。",
    "spring": "★悬挂：弹簧刚度 / 阻尼 / 行程。",
    "flap": "车门/盖的开合铰链（位置/方向/法线）。",
    "steering": "方向盘位置与半径。",
    "seat": "座椅位置/朝向。",
    "shifter": "挡把位置。",
    "pedals": "踏板位置。",
    "controller": "控制器项。",
    "cockpit_rpm": "仪表 RPM 信号源。",
    "cockpit_speed": "仪表速度信号源。",
}

# 类名片段 -> 界面顶部提示（这些类的关键值不在 configureType 里）
HINTS = (
    ("Tyre_", "抓地力 = Pacejka 槽2 的 µ：各配方 <init> 里 6 个接触面数组的第 1 个 float。"
              "沥青 µ：NC 1.30 / SH 1.50 / SM 1.66 / SS 1.85 / RH 2.00 / RS 2.25"
              "（冰面 0.10–0.30）。⚠ 按字面量序号通常是第 10 个，但 Tyre_SS 是第 9 个。"),
    ("INitrous", "容量与基础加成在 onInstall：每档一对 (加成, 容量) = (0.55,4.0) / "
                 "(0.5,6.0) / (0.45,8.0) / (0.4,10.0) / (0.45,12.0)，末位 1.0 = 消耗率；"
                 "容量刻度 = 干净计时段（1 段 = 1.0，一圈 = 5.0）。"),
    ("IEngine", "turboPeakP 是涡轮总开关（>0.01 才增压）；turboTable 全 0 时开了也几乎没推力。"),
    ("WeightReduction", "真正的减重量 = 本类 configureType「body」第 2 行的★质量(kg)"
                        "（例如 Hatch_S2：394→250→203→147→113）。唯一那个字面量是无意义的 return 0。"),
)

TOKEN = re.compile(r"0[xX][0-9A-Fa-f]+|-?\d+\.\d*(?:[eE][-+]?\d+)?"
                   r"|-?\d+(?:[eE][-+]?\d+)?|\S+")
KEY_OK = re.compile(r"^[a-z_]{2,16}$")


class CfgError(Exception):
    pass


class Tok:
    __slots__ = ("field", "idx", "off", "text", "kind")

    def __init__(self, field, idx, off, text, kind):
        self.field, self.idx, self.off = field, idx, off
        self.text, self.kind = text, kind


class Cfg:
    """一行 configureType。`off` 是字符串内容在**文件里**的绝对偏移。"""

    __slots__ = ("key", "text", "off", "tokens", "comment")

    def __init__(self, key, text, off, tokens, comment):
        self.key, self.text, self.off = key, text, off
        self.tokens, self.comment = tokens, comment

    def label(self, i):
        names = SCHEMA.get(self.key, ())
        if i < len(names):
            return names[i]
        return "第 %d 个数值" % (i + 1)


def _kind(s):
    if re.fullmatch(r"0[xX][0-9A-Fa-f]+", s):
        return "hex"
    if re.fullmatch(r"-?\d+", s):
        return "int"
    if re.fullmatch(r"-?\d+\.\d*(?:[eE][-+]?\d+)?|-?\d+(?:[eE][-+]?\d+)", s):
        return "float"
    return "text"


def cons_base(t):
    """CONS chunk 的 body 在文件里的绝对偏移（pool.offsets 是相对它的）。"""
    cons = t.ck.get("CONS")
    if not cons:
        raise CfgError("没有 CONS 常量池")
    return cons[0][0]


def parse(t, keys=None):
    """[Cfg]：本 class 里所有 `key\\t…` 形态的字符串及其数值 token。

    文本**每次从 `t.data` 重读**（不用 `pool.utf8` 的缓存），这样原地改完
    立刻能再解析出新的值 —— 和 `Tufa.literals()` 的行为一致。
    """
    base = cons_base(t)
    out = []
    for idx in sorted(t.pool.offsets):
        p = base + t.pool.offsets[idx]
        end = t.data.find(b"\x00", p)
        if end < 0:
            continue
        text = bytes(t.data[p:end]).decode("latin-1")
        if "\t" not in text:
            continue
        key = text.split("\t", 1)[0]
        if not KEY_OK.match(key):
            continue
        if keys and key not in keys:
            continue
        body = text.split(";", 1)[0]                    # 去掉行尾注释
        comment = text.split(";", 1)[1].strip() if ";" in text else ""
        toks = []
        for m in TOKEN.finditer(body):
            s = m.group(0)
            if s == "\t":
                continue
            field = body.count("\t", 0, m.start()) + 1
            k = _kind(s)
            if k != "text":
                toks.append(Tok(field, len(toks), p + m.start(), s, k))
        out.append(Cfg(key, text, p, toks, comment))
    return out


def fmt_like(new, old):
    """把新值格式化成与旧文本**同长度**的写法。

    同长度是硬约束（这样文件长度、池条目、所有偏移都不变），所以宽度不够时
    **宁可拒绝也不静默丢精度** —— 例如 3 个字符的位置写 `0.05` 只能写成 `0.1`
    （差 100%），这种就报错让用户换个写法，而不是偷偷改错值。
    """
    n = len(old)
    if _kind(old) == "hex":
        w = len(old) - 2
        s = "0x%0*X" % (w, int(new, 0) if isinstance(new, str) else int(new))
        if len(s) > n:
            raise CfgError("十六进制位数不够：%s 装不进 %s" % (s, old))
        return s
    val = float(new)
    cands = []
    if "." in old:
        for d in range(len(old.split(".")[1]), -1, -1):
            cands.append("%.*f" % (d, val))
    cands += ["%g" % val, "%d" % round(val)]
    best = None
    for s in cands:
        if len(s) > n:
            continue
        try:
            got = float(s)
        except ValueError:
            continue
        if best is None or abs(got - val) < abs(best[1] - val):
            best = (s, got)
    if best is None:
        raise CfgError("新值 %g 比原来的 %r 占位更长，会改变文件长度 —— "
                       "请填一个更短的值" % (val, old))
    s, got = best
    if abs(got - val) > max(1e-6, abs(val) * 0.001):
        raise CfgError("这个位置只有 %d 个字符宽，最接近的写法是 %r，与你要的 %g "
                       "相差 %.1f%% —— 拒绝静默丢精度，请换个能写下的值"
                       % (n, got, val,
                          100.0 * abs(got - val) / max(1e-9, abs(val))))
    return s + " " * (n - len(s))        # sscanf 会跳过多余空白


def set_token(t, tk, new_text):
    """把 token 原地改成 new_text（同长度）。返回实际写入的文本。"""
    s = fmt_like(new_text, tk.text)
    off = tk.off
    t.data[off:off + len(tk.text)] = s.encode("latin-1")
    tk.text = s
    return s


def hint_for(class_short):
    """这些类的关键值不在 configureType 里，界面上给一句提示。"""
    for frag, msg in HINTS:
        if frag in (class_short or ""):
            return msg
    return ""


def dump(path):
    t = _tufa.Tufa(open(path, "rb").read())
    for c in parse(t):
        print("%-13s %-60s %s" % (c.key, [tk.text for tk in c.tokens][:10],
                                  c.comment))
