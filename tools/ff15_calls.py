"""把 exe 里 `call [绝对地址]`（FF 15）的调用点解析成导入函数名。

动机：目标程序**不**通过 `call [reg+disp]` 调设备的 COM 方法，而是走 IAT 跳板
（`call dword ptr [IAT_slot]` = FF 15 + 4 字节绝对地址）。只看 ModRM 的扫描器
会得出"程序从不创建纹理"这种错误结论——实际是**编码形式不同**。
本工具解析导入目录建立 IAT 槽 → "DLL!函数名" 的映射，再把所有 FF 15 调用点
连同名字、上下文窗口一起打出来。

用法:
    python tools/ff15_calls.py                # 全部 FF 15 调用点（按名字聚合）
    python tools/ff15_calls.py --grep Create  # 只看名字含 Create 的
    python tools/ff15_calls.py --grep D3DX --window
"""
import re
import struct
import sys

from capstone import Cs, CS_ARCH_X86, CS_MODE_32

IMAGE = r"C:\Games\LASR\LASR.exe"
EXE = open(IMAGE, "rb").read()
PE = struct.unpack_from("<I", EXE, 0x3C)[0]
NSEC = struct.unpack_from("<H", EXE, PE + 6)[0]
OPTSZ = struct.unpack_from("<H", EXE, PE + 20)[0]
BASE = struct.unpack_from("<I", EXE, PE + 24 + 28)[0]
IMPDIR = struct.unpack_from("<II", EXE, PE + 24 + 96 + 8 * 1)

SECS = []
for _i in range(NSEC):
    _o = PE + 24 + OPTSZ + _i * 40
    _nm = EXE[_o:_o + 8].rstrip(b"\0").decode("latin1")
    _vsz, _va, _rsz, _ra = struct.unpack_from("<IIII", EXE, _o + 8)
    SECS.append({"n": _nm, "va": _va, "vsz": _vsz, "ra": _ra, "rsz": _rsz})


def off(rva):
    for s in SECS:
        if s["va"] <= rva < s["va"] + max(s["vsz"], s["rsz"]):
            return s["ra"] + (rva - s["va"])
    return None


def cstr(rva, limit=200):
    o = off(rva)
    if o is None:
        return None
    raw = EXE[o:o + limit]
    end = raw.find(b"\0")
    return raw[:end].decode("latin1", "replace") if end > 0 else None


def build_iat_map():
    """IAT 槽 VA -> 'dll!Func'"""
    m = {}
    if not IMPDIR[0]:
        return m
    o = off(IMPDIR[0])
    if o is None:
        return m
    k = 0
    while True:
        desc = EXE[o + k * 20: o + k * 20 + 20]
        if len(desc) < 20:
            break
        oft, _ts, _fc, name_rva, ft = struct.unpack("<IIIII", desc)
        if not (oft or ft or name_rva):
            break
        dll = cstr(name_rva) or "?"
        ilt = oft or ft
        j = 0
        while True:
            eo = off(ilt + j * 4)
            if eo is None:
                break
            ent = struct.unpack_from("<I", EXE, eo)[0]
            if ent == 0:
                break
            if ent & 0x80000000:
                fname = f"#{ent & 0xFFFF}"
            else:
                fname = cstr(ent + 2) or "?"
            m[BASE + ft + j * 4] = f"{dll}!{fname}"
            j += 1
        k += 1
    return m


IAT = build_iat_map()
print(f"IAT 槽位映射: {len(IAT)} 条")

MD = Cs(CS_ARCH_X86, CS_MODE_32)
tva, tvsz, tra, trsz = SECS[0]["va"], SECS[0]["vsz"], SECS[0]["ra"], SECS[0]["rsz"]
text = EXE[tra:tra + tvsz]

sites = []
for j in range(len(text) - 6):
    if text[j] == 0xFF and text[j + 1] == 0x15:          # call [abs32]
        absaddr = struct.unpack_from("<I", text, j + 2)[0]
        nm = IAT.get(absaddr)
        if nm:
            sites.append((BASE + tva + j, absaddr, nm))

print(f"FF 15 调用点（能解析到导入名）: {len(sites)}\n")

grep = None
window = False
args = sys.argv[1:]
if "--grep" in args:
    grep = args[args.index("--grep") + 1]
if "--window" in args:
    window = True

from collections import Counter
agg = Counter(nm for _a, _s, nm in sites)
print("=== 按导入函数聚合（前 40）===")
for nm, c in agg.most_common(40):
    if grep and grep.lower() not in nm.lower():
        continue
    print(f"   {c:4d}x  {nm}")

if grep:
    print(f"\n=== 名字含 '{grep}' 的调用点及其上下文 ===")
    for addr, slot, nm in sites:
        if grep.lower() not in nm.lower():
            continue
        rva = addr - BASE
        o = off(rva)
        pushes = []
        for ins in MD.disasm(EXE[max(0, o - 80):o + 6], addr - 80):
            if ins.mnemonic == "push":
                pushes.append(ins.op_str)
        print(f"\n  0x{addr:08x}  → {nm}")
        print(f"       前置 push: {pushes[-10:]}")
        if window:
            for ins in MD.disasm(EXE[max(0, o - 80):o + 20], addr - 80):
                mk = " <<<" if ins.address == addr else ""
                print(f"         0x{ins.address:08x}  {ins.mnemonic:7s} {ins.op_str}{mk}")
