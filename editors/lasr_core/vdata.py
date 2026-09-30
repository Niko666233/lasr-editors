"""车辆数据（class 文件）读写：从游戏目录里读出零件类，改数，再写回 zip。

数据链路（每一环都已离线实测，见 editors/selftest_core.py）：

    vehicles/<车>/<body>/classes.zip
        | 解压 zip 条目 (deflate)
      FLZD 容器  --flzd.FlzdCodec.unpack-->  TUFA 类字节码
        |  改 TUFA 里 INT/FLOAT LITERAL 的 4 字节载荷（文件长度不变）
      FLZD 容器  <--flzd.FlzdCodec.pack----  改过的 TUFA
        | 重写 zip（保留其它条目原样，先备份）

FLZD 的 pack 用的是 LASR.exe 自己的例程（unicorn 模拟执行），实测能把原始
条目**逐字节**复现出来，所以写回去的容器和游戏自己产出的没有区别。
"""
import shutil
import struct
import zipfile
from pathlib import Path

from . import flzd_head, tufa

# unicorn（flzd.py）只在真的要解压/压缩时才 import —— 打包后的 exe 里
# `uc.emu_start` 必崩（docs/60 §6），走快照+明文写入就不需要它。
SNAPSHOT_DIR = Path(__file__).resolve().parent.parent / "data" / "classes"

GAME_CANDIDATES = (
    r"C:\Games\LASR",
    r"C:\Program Files\LASR",
    r"C:\Program Files (x86)\LASR",
)


def codec_available(exe):
    """能不能用 unicorn 跑游戏自己的压缩器（打包 exe 里通常不行）。"""
    try:
        from . import flzd
        flzd.FlzdCodec(exe)
        return True
    except Exception:  # noqa: BLE001
        return False


def snapshot_for(zip_path, entry):
    """zip 路径 + 条目名 -> 快照 .tufa 路径（可能不存在）。

    `java/classes.zip` 的快照放在 `data/classes/_java/`，车包放在
    `data/classes/<Car>/<body>/`。
    """
    zp = Path(zip_path)
    stem = Path(entry).stem
    if zp.parent.name.lower() == "java":
        return SNAPSHOT_DIR / "_java" / (stem + ".tufa")
    try:
        car, body = zp.parts[-3], zp.parts[-2]
    except IndexError:
        return SNAPSHOT_DIR / (stem + ".tufa")
    return SNAPSHOT_DIR / car / body / (stem + ".tufa")


_SNAP_INDEX = None


def snapshot_index():
    """{类短名: [快照路径, ...]}，只扫一次。

    按**路径**推 car/body 只在 zip 位于 `vehicles/<Car>/<body>/` 时成立；工具用户
    也可能把 zip 复制到别处（测试就是这么干的），所以再加一层按类名的索引。
    """
    global _SNAP_INDEX
    if _SNAP_INDEX is None:
        _SNAP_INDEX = {}
        if SNAPSHOT_DIR.is_dir():
            for p in SNAPSHOT_DIR.rglob("*.tufa"):
                _SNAP_INDEX.setdefault(p.stem, []).append(p)
    return _SNAP_INDEX


def snapshot_candidates(zip_path, entry):
    """按类名给出候选快照（优先同 car/body 目录下的）。"""
    stem = Path(entry).stem
    hits = list(snapshot_index().get(stem, ()))
    if not hits:
        return []
    zp = Path(zip_path)
    try:
        car, body = zp.parts[-3], zp.parts[-2]
    except IndexError:
        car = body = None
    pref = [h for h in hits if car and h.parent.name == body
            and h.parent.parent.name == car]
    return pref + [h for h in hits if h not in pref]


def snapshot_hit(zip_path, entry, raw):
    """快照能用吗：文件在，且大小 == 容器头里的 uncompressedSize。"""
    if not flzd_head.is_flzd(raw):
        return None
    try:
        usize = flzd_head.parse_header(raw)[1]
    except flzd_head.FlzdError:
        return None
    for snap in snapshot_candidates(zip_path, entry):
        if snap.is_file() and snap.stat().st_size == usize:
            return snap
    return None


def read_zip_entry(zip_path, entry, codec=None):
    """读一个 zip 条目，返回明文 TUFA 字节。

    优先走随工具发布的快照（**不需要 unicorn**）；只有快照缺失/与当前安装不一致时
    才真的去解 FLZD（那一步才需要模拟器）。
    """
    with zipfile.ZipFile(zip_path) as zf:
        raw = zf.read(entry)
    snap = snapshot_hit(zip_path, entry, raw)
    if snap is not None:
        return snap.read_bytes()
    if not flzd_head.is_flzd(raw):
        return raw
    if codec is None:
        from . import flzd
        game = find_game_dir(str(Path(zip_path).parent))
        exe = (game / "LASR.exe") if game else (Path(zip_path).parent / "LASR.exe")
        codec = flzd.FlzdCodec(exe)
    return codec.unpack(raw)


def find_game_dir(hint=None):
    """Locate the LASR install (must contain LASR.exe + vehicles/)."""
    cands = []
    if hint:
        cands.append(Path(hint))
    cands += [Path(p) for p in GAME_CANDIDATES]
    for c in cands:
        try:
            if (c / "LASR.exe").is_file() and (c / "vehicles").is_dir():
                return c
        except OSError:
            pass
    return None


def humanname(class_name):
    """`Coupe_RS_IEngine_stage_II` -> (family, variant) best effort."""
    tail = class_name.split(".")[-1]
    parts = tail.split("_")
    for i, p in enumerate(parts):
        if p.startswith("I") and len(p) > 1 and p[1].isupper():
            fam = "_".join(parts[i:i + 1])
            variant = "_".join(parts[i + 1:])
            return fam, variant
    return tail, ""


class PartStats:
    """Read-only summary of one class: name, method table, curve look."""
    def __init__(self, entry, class_name, t):
        self.entry = entry
        self.class_name = class_name
        self.tufa = t

    @property
    def param_methods(self):
        return [m for m in self.tufa.methods if m.linear and m.prog]

    def display_name(self):
        """Call the class's own getName()/getLongName() and read the string."""
        for want in ("getName", "getLongName"):
            for m in self.tufa.find(want):
                if m.desc != "()Ljava.lang.String;":
                    continue
                s = self._string_return(m)
                if s:
                    return s
        return None

    def _string_return(self, m):
        # `STRING LITERAL idx; RETURN`  or  `FIELD_REF.. ; ..; RETURN`
        payloads = [p for _o, _op, _w, p in (m.prog or []) if p is not None]
        for _o, op, _w, pay in (m.prog or []):
            if op == 0x08 and pay is not None:          # STRING LITERAL
                s = self.tufa.pool.utf8(pay)
                if s:
                    return s
        for _o, op, _w, pay in (m.prog or []):
            if op in (0x1F, 0x20, 0x21) and pay is not None:   # ref ops
                r = self.tufa.pool.ref(pay)
                if r and r[2] == "()Ljava.lang.String;" and r[1]:
                    return r[1]
        del payloads
        return None


class Curve:
    """A `()[F` method: its literals are [arraySize, pad] + data values."""
    def __init__(self, method, literals):
        self.method = method
        self.literals = literals

    @property
    def name(self):
        return self.method.name

    @property
    def data(self):
        return self.literals[2:]

    @property
    def count(self):
        return len(self.data)

    def values(self):
        """[(literal_index, value)] for the data literals."""
        return [(i, v) for (i, _off, _kind, v) in self.data]


def curves(t):
    """All float-array methods of a class that follow the `[size, pad, data..]`
    layout (verified: size literal == number of remaining literals)."""
    out = []
    for m in t.methods:
        if not m.linear or m.desc != "()[F":
            continue
        lits = t.literals(m)
        if len(lits) < 3 or lits[0][3] != len(lits) - 2:
            continue
        # every data literal must be an int pushed through I2F, or a float
        if any(k not in ("int", "float") for _i, _o, k, _v in lits[2:]):
            continue
        out.append(Curve(m, lits))
    return out


def scalars(t):
    """[(method, literal_index, kind, value)] for every non-curve literal."""
    curve_ids = set()
    for c in curves(t):
        curve_ids.add(c.method.index)
    out = []
    for m in t.methods:
        if not m.linear or m.index in curve_ids:
            continue
        for i, _off, kind, value in t.literals(m):
            out.append((m, i, kind, value))
    return out


class ZipPartEditor:
    """Read / modify one part class inside a `classes.zip`, with a backup.

    两种写入格式（`write_mode`）：
      * "flzd" —— 用游戏自己的压缩器重打包（格式与原始条目完全一致，需要
        unicorn 模拟器；打包后的 exe 里 unicorn 的 JIT 会 0xC0000409 崩，
        所以 exe 里只能选原样）。
      * "raw"  —— 直接把 TUFA 明文写进 zip 条目（zip 自己仍然 deflate）。
        游戏的文件加载器对非 FLZD 数据是「跳过解压、原样交给解析器」
        （0x55aead / 0x4cb089 两处 `test ebp,ebp; jle skip`），所以明文
        TUFA 有很高概率能被直接读进来 —— 但**这一条还没有实机验证过**。
    """

    def __init__(self, game_dir, zip_path, exe=None, write_mode="raw"):
        self.game_dir = Path(game_dir)
        self.zip_path = Path(zip_path)
        self.exe = exe or (self.game_dir / "LASR.exe")
        self.write_mode = write_mode
        self._codec = None
        self._zip = zipfile.ZipFile(self.zip_path)

    # ---------------------------------------------------------------- codec
    @property
    def codec(self):
        if self._codec is None:
            from . import flzd                 # 懒加载：只有真要解压/压缩时才引 unicorn
            self._codec = flzd.FlzdCodec(self.exe)
        return self._codec

    def snapshot_path(self, entry):
        """路径式快照定位（zip 在标准位置时用）；找不到时 vdata 会按类名兜底。"""
        car = self.zip_path.parts[-3]
        body = self.zip_path.parts[-2]
        return SNAPSHOT_DIR / car / body / (Path(entry).stem + ".tufa")

    def entries(self):
        return [i.filename for i in self._zip.infolist()]

    def part_entries(self):
        return [e for e in self.entries()
                if e.endswith(".class") and "/" in e]

    # ----------------------------------------------------------------- read
    def load(self, entry, allow_snapshot=True):
        """读一个零件类。

        优先用随工具发布的**明文快照**（不需要 unicorn），并用容器头里的
        uncompressedSize 校验它跟当前安装一致；不一致才回退到真解压。
        """
        raw = self._zip.read(entry)
        data = None
        if allow_snapshot:
            snap = snapshot_hit(self.zip_path, entry, raw)
            if snap is not None:
                data = snap.read_bytes()
        if data is None:
            if flzd_head.is_flzd(raw):
                from . import flzd
                data = self.codec.unpack(raw)
            else:
                data = raw          # 明文类：不需要（也绝不能碰）unicorn
        t = tufa.Tufa(data)
        cls = entry.split("/")[-1][:-6]
        full = t.pool.utf8(0) or cls
        return PartStats(entry, full, t)

    # ---------------------------------------------------------------- write
    def save(self, edits, backup=True, dry_run=False):
        """edits = {entry: patched TUFA bytes}.  Rewrites the zip atomically.

        Every other member is copied through untouched; the original zip is
        kept as `<name>.bak` the first time.
        """
        edits = {k: v for k, v in edits.items() if v is not None}
        if not edits:
            return None
        if dry_run:
            return None
        infos = self._zip.infolist()
        payloads = {}
        for info in infos:
            if info.filename in edits:
                data = edits[info.filename]
                payloads[info.filename] = (data if self.write_mode == "raw"
                                           else self.codec.pack(data))
            else:
                payloads[info.filename] = self._zip.read(info.filename)
        self._zip.close()
        bak = Path(str(self.zip_path) + ".bak")
        if backup and not bak.exists():
            shutil.copy2(self.zip_path, bak)
        tmp = Path(str(self.zip_path) + ".tmp")
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zo:
            for info in infos:
                zi = zipfile.ZipInfo(info.filename, date_time=info.date_time)
                zi.compress_type = zipfile.ZIP_DEFLATED
                zi.external_attr = info.external_attr
                zo.writestr(zi, payloads[info.filename])
        tmp.replace(self.zip_path)
        self._zip = zipfile.ZipFile(self.zip_path)
        return bak if backup else None

    def restore(self):
        bak = Path(str(self.zip_path) + ".bak")
        if bak.exists():
            shutil.copy2(bak, self.zip_path)
            self._zip.close()
            self._zip = zipfile.ZipFile(self.zip_path)
            return True
        return False

    def close(self):
        self._zip.close()


def apply_curve_scale(curve, factor):
    """Return {literal_index: new_value} scaling only the data literals."""
    return {i: v * factor for i, v in curve.values()}


def apply_curve_set(curve, values):
    """Return {literal_index: new_value} setting data literals positionally."""
    out = {}
    for (i, _old), v in zip(curve.values(), values):
        out[i] = v
    return out


def _selftest():
    import sys
    game = find_game_dir()
    if not game:
        print("找不到游戏目录")
        return 1
    zp = game / "vehicles" / "Phoenix_RS_1997" / "coupe" / "classes.zip"
    ed = ZipPartEditor(game, zp)
    st = ed.load("classes/Coupe_RS_IEngine_stock.class")
    print("class        :", st.class_name)
    print("display name :", st.display_name())
    print("methods      :", [m.name for m in st.tufa.methods])
    for c in curves(st.tufa):
        print("curve %-8s %d 点: %s" % (c.name, c.count,
                                       [v for _i, v in c.values()]))
    print("scalars      :", [(m.name, i, k, v) for m, i, k, v in scalars(st.tufa)])
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
