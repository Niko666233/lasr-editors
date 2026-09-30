"""把镜像里任意地址按「u32 / float / 字符串引用」三视角 dump，用于读结构体模板。

用法: python tools/dump_struct.py <地址> [长度] [--from <起点>]
例:   python tools/dump_struct.py 0x763dcc 0x3c
"""
import struct
import sys

EXE = r"C:\Games\LASR\LASR.exe"


def load():
    E = open(EXE, "rb").read()
    PE = struct.unpack_from("<I", E, 0x3C)[0]
    NS = struct.unpack_from("<H", E, PE + 6)[0]
    OS = struct.unpack_from("<H", E, PE + 20)[0]
    base = struct.unpack_from("<I", E, PE + 24 + 28)[0]
    secs = []
    for i in range(NS):
        o = PE + 24 + OS + i * 40
        nm = E[o:o + 8].rstrip(b"\x00").decode("latin1")
        vsz, va, rsz, ra = struct.unpack_from("<IIII", E, o + 8)
        secs.append((nm, base + va, ra, rsz))
    return E, secs


E, SECS = load()


def off(va):
    for nm, b, ra, rsz in SECS:
        if b <= va < b + rsz:
            return ra + va - b, nm
    return None, None


def str_at(va):
    o, _ = off(va)
    if o is None:
        return None
    z = E[o:o + 64].split(b"\x00")[0]
    if len(z) > 2 and all(32 <= c < 127 for c in z):
        return z.decode("latin1")
    return None


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    va = int(sys.argv[1], 16)
    n = int(sys.argv[2], 16) if len(sys.argv) > 2 else 0x40
    base = va
    if "--from" in sys.argv:
        base = int(sys.argv[sys.argv.index("--from") + 1], 16)
        n = va - base
        va = base
    o, nm = off(va)
    if o is None:
        print(f"{va:#x} 不在任何节里")
        return 1
    print(f"=== {va:#x} 起 {n:#x} 字节  [{nm}] ===")
    for i in range(0, n, 4):
        a = va + i
        u = struct.unpack_from("<I", E, o + i)[0]
        f = struct.unpack_from("<f", E, o + i)[0]
        fs = repr(round(f, 6)) if (u == 0 or 1e-30 < abs(f) < 1e30) else "—"
        extra = ""
        s = str_at(u)
        if s:
            extra = f'  → "{s}"'
        elif 0x400000 <= u <= 0x9FFFFF:
            extra = "  (镜像内地址)"
        print(f"  +{i:#05x}  {u:#010x}  u={u:<12d} f={fs}{extra}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
