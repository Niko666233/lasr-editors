"""FLZD 容器头的纯 Python 读写（**不**引入 unicorn）。

`flzd.py`（重打包/解压需要跑游戏自己的机器码）会 import unicorn；而 PyInstaller
产物里调 `uc.emu_start` 必 0xC0000409（docs/60 §6）。凡是只需要看容器头的场合
（判断是不是 FLZD、拿 uncompressedSize 校验快照）都用本模块，这样打包后的工具
不需要 unicorn 也能跑。
"""
import struct

MAGIC = b"FLZD"
HEADER = 13
LEVELS = (9, 10, 11, 12, 13)
DEFAULT_LEVEL = 11


class FlzdError(Exception):
    pass


def is_flzd(blob):
    return len(blob) >= HEADER and blob[:4] == MAGIC


def parse_header(blob):
    """-> (level, uncompressed_size, payload)；不是 FLZD 或头非法就抛 FlzdError。"""
    if not is_flzd(blob):
        raise FlzdError("not an FLZD container (bad magic)")
    a, b = struct.unpack_from("<II", blob, 4)
    level = blob[12]
    if a - 4 > len(blob) - HEADER:
        raise FlzdError("declared payload %d > available %d"
                        % (a - 4, len(blob) - HEADER))
    if not (9 <= level < 14):
        raise FlzdError("unsupported level %d (valid 9..13)" % level)
    return level, b, blob[HEADER:]


def build_header(uncompressed_size, payload_len, level=DEFAULT_LEVEL):
    return MAGIC + struct.pack("<II", payload_len + 4, uncompressed_size) + bytes([level])
