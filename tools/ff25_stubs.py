"""建立 FF 25 跳转桩索引：把静态导入的 API 名字接到所有调用点上。

为什么必须有它（踩过两次）：
引擎**不**用 `call [IAT]`（FF 15）去调 D3D —— 它调的是**导入跳转桩**：
    <stub>:  FF 25 <IAT 绝对地址>        ; jmp dword ptr [IAT]
调用方是         E8 <stub>               ; call stub
于是"只扫 FF 15"会得出"这个程序从不调用 D3D"的假结论。本工具把两者接起来：
  1) 解析导入目录 → IAT 槽绝对地址 → DLL!函数名
  2) 在可执行节里找所有 FF 25 disp32（= jmp [abs]）→ 桩地址 → 槽 → 名字
  3) 找所有 E8 目标落在某个桩上的调用点 → 调用点 → 名字
输出即"调用点 → DLL!函数名"的完整表，可按名字过滤。

用法:
  python tools/ff25_stubs.py                # 概览：桩数、调用点数、按 DLL 汇总
  python tools/ff25_stubs.py --grep d3d     # 只看名字含 d3d 的
  python tools/ff25_stubs.py --func CreateTexture
"""
import struct
import sys

IMG = r"C:\Games\LASR\LASR.exe"
EXE = open(IMG, "rb").read()
PE = struct.unpack_from("<I", EXE, 0x3C)[0]
NSEC = struct.unpack_from("<H", EXE, PE + 6)[0]
OPTSZ = struct.unpack_from("<H", EXE, PE + 20)[0]
BASE = struct.unpack_from("<I", EXE, PE + 24 + 28)[0]      # ★ 节表 VA 是 RVA
OPT = PE + 24
DDIR = OPT + (96 if OPTSZ >= 96 + 16 * 8 else 96)          # DataDirectory 起于 +96
IMP_RVA, IMP_SZ = struct.unpack_from("<II", EXE, DDIR + 8 * 1)
SECS, EXEC = [], []
for _i in range(NSEC):
    _o = OPT + OPTSZ + _i * 40
    _nm = EXE[_o:_o + 8].rstrip(b"\0").decode("latin1")
    _vsz, _va, _rsz, _ra = struct.unpack_from("<IIII", EXE, _o + 8)
    _ch = struct.unpack_from("<I", EXE, _o + 36)[0]
    _va += BASE
    SECS.append({"n": _nm, "va": _va, "vsz": _vsz, "ra": _ra, "rsz": _rsz})
    if _rsz and (_ch & 0x20000000):
        EXEC.append((_va, EXE[_ra:_ra + _rsz]))


def off(va):
    for s in SECS:
        if s["va"] <= va < s["va"] + s["vsz"]:
            return s["ra"] + (va - s["va"])
    return None


def read(va, n):
    o = off(va)
    return None if o is None else EXE[o:o + n]


def cstr(va, maxlen=200):
    b = read(va, maxlen)
    if not b:
        return None
    e = b.find(b"\0")
    return b[:e].decode("latin1") if e > 0 else None


def parse_imports():
    """返回 {IAT 绝对地址: 'DLL!函数名'}"""
    out = {}
    if not IMP_RVA:
        return out
    va = BASE + IMP_RVA
    i = 0
    while True:
        ent = read(va + i * 20, 20)
        if not ent or ent[:20] == b"\0" * 20:
            break
        oft, ts, fc, namerva, first = struct.unpack("<IIIII", ent)
        dll = cstr(BASE + namerva) or "?"
        thunk = BASE + (oft or first)
        k = 0
        while True:
            t = read(thunk + k * 4, 4)
            if not t:
                break
            v = struct.unpack("<I", t)[0]
            if v == 0:
                break
            slot = BASE + first + k * 4
            if v & 0x80000000:
                out[slot] = f"{dll}!ordinal#{v & 0xFFFF}"
            else:
                nm = read(BASE + v + 2, 128) or b""
                e = nm.find(b"\0")
                out[slot] = f"{dll}!{nm[:e].decode('latin1')}"
            k += 1
        i += 1
    return out


IMP = parse_imports()


def find_stubs():
    """FF 25 disp32 → {桩地址: IAT 槽}"""
    out = {}
    for va0, blob in EXEC:
        i = 0
        while True:
            i = blob.find(b"\xff\x25", i)
            if i < 0 or i + 6 > len(blob):
                break
            slot = struct.unpack_from("<I", blob, i + 2)[0]
            if slot in IMP:
                out[va0 + i] = slot
            i += 1
    return out


STUBS = find_stubs()


def call_sites(target):
    out = []
    for va0, blob in EXEC:
        i = 0
        while True:
            i = blob.find(b"\xe8", i)
            if i < 0 or i + 5 > len(blob):
                break
            rel = struct.unpack_from("<i", blob, i + 1)[0]
            if (va0 + i + 5 + rel) == target:
                out.append(va0 + i)
            i += 1
    return sorted(out)


def main():
    args = sys.argv[1:]
    grep = None
    func = None
    if "--grep" in args:
        grep = args[args.index("--grep") + 1].lower()
    if "--func" in args:
        func = args[args.index("--func") + 1]

    by_fn = {}
    for stub, slot in STUBS.items():
        by_fn.setdefault(IMP[slot], []).append(stub)

    # ★ 反查模式：给定桩地址，说出它是哪个导入函数（音频/FMOD 调查反复需要）
    if "--stub" in args or "--stubs" in args:
        if "--stub" in args:
            for a in args[args.index("--stub") + 1:]:
                try:
                    v = int(a, 16)
                except ValueError:
                    break
                slot = STUBS.get(v)
                if slot is None:
                    print(f"{v:#x}: ✗ 不是 FF 25 桩（或不在导入表内）")
                else:
                    print(f"{v:#x} → IAT {slot:#x} → {IMP[slot]}")
        else:
            print(f"{'桩地址':<12} {'IAT 槽':<12} DLL!函数")
            for stub, slot in sorted(STUBS.items()):
                print(f"{stub:#x}   {slot:#x}   {IMP[slot]}")
        return 0

    # 调用点
    total_sites = 0
    rows = []
    for name, stubs in by_fn.items():
        if func and name.split("!")[-1] != func:
            continue
        if grep and grep not in name.lower():
            continue
        sites = []
        for s in stubs:
            sites.extend(call_sites(s))
        total_sites += len(sites)
        rows.append((name, len(stubs), sites))

    print(f"导入函数 {len(IMP)} 个；其中的跳转桩 {len(STUBS)} 个；"
          f"命中的静态调用点合计 {total_sites} 个")
    rows.sort(key=lambda r: -len(r[2]))
    print(f"{'DLL!函数':<46} 桩 调用点数 前几个调用点")
    for name, ns, sites in rows[:60]:
        head = " ".join(f"{s:#x}" for s in sites[:5])
        print(f"{name:<46} {ns:>2} {len(sites):>7}  {head}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
