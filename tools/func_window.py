"""从一个【函数起点】对齐地反汇编，列出其中的 call 与 push 的立即数/字符串。

为什么不截窗口：从任意地址前后截窗口会落在指令中间，capstone 会静默给出垃圾
指令（例如 insb / add al,0x89），而关键的那个 call 往往刚好在窗口之外。本工具
先用"E8 目标集 + 向前找 int3 填充/ret"求出函数真正起点，再从起点**对齐**反汇编。

输出每行：地址 指令（call 会解析目标；push 立即数若指向 .rdata 的 ASCII 会直接打印）

用法: python tools/func_window.py 0x4c0d44 [最多指令数]
"""
import struct
import sys

from capstone import CS_ARCH_X86, CS_MODE_32, Cs

IMG = r"C:\Games\LASR\LASR.exe"
EXE = open(IMG, "rb").read()
PE = struct.unpack_from("<I", EXE, 0x3C)[0]
NSEC = struct.unpack_from("<H", EXE, PE + 6)[0]
OPTSZ = struct.unpack_from("<H", EXE, PE + 20)[0]
BASE = struct.unpack_from("<I", EXE, PE + 24 + 28)[0]
SECS = []
for _i in range(NSEC):
    _o = PE + 24 + OPTSZ + _i * 40
    _nm = EXE[_o:_o + 8].rstrip(b"\0").decode("latin1")
    _vsz, _va, _rsz, _ra = struct.unpack_from("<IIII", EXE, _o + 8)
    _va += BASE                             # ★ 节表 VA 是 RVA，必须加 ImageBase
    SECS.append({"n": _nm, "va": _va, "vsz": _vsz, "ra": _ra, "rsz": _rsz})

MD = Cs(CS_ARCH_X86, CS_MODE_32)


def off(va):
    for s in SECS:
        if s["va"] <= va < s["va"] + s["vsz"]:
            return s["ra"] + (va - s["va"])
    return None


def sec_of(va):
    for s in SECS:
        if s["va"] <= va < s["va"] + s["vsz"]:
            return s
    return None


def read(va, n):
    o = off(va)
    if o is None:
        return None
    return EXE[o:o + n]


def cstr(va, maxlen=64):
    b = read(va, maxlen)
    if not b:
        return None
    end = b.find(b"\0")
    if end < 6:
        return None
    chunk = b[:end]
    if all(32 <= c < 127 or c in (9, 10, 13) for c in chunk):
        return chunk.decode("latin1")
    return None


def func_starts():
    """所有 E8 rel32 的目标 = 函数起点候选。"""
    text = b""
    starts_va = 0
    for s in SECS:
        if s["n"] == ".text":
            text = EXE[s["ra"]:s["ra"] + s["rsz"]]
            starts_va = s["va"]
            break
    out = set()
    i = 0
    while True:
        i = text.find(b"\xe8", i)
        if i < 0 or i + 5 > len(text):
            break
        rel = struct.unpack_from("<i", text, i + 1)[0]
        out.add(starts_va + i + 5 + rel)
        i += 1
    return out


STARTS = func_starts()


def real_start(va):
    """向前退到最近的函数起点；若落在 int3 填充/ret 之后也算。"""
    best = None
    for s in STARTS:
        if s <= va and (best is None or s > best):
            best = s
    # 从 best 对齐解码到 va：若中途出现对不齐就退回
    if best is not None:
        ok = False
        for ins in MD.disasm(read(best, va - best), best):
            if ins.address == va:
                ok = True
                break
        if ok:
            return best, "E8 目标"
    # 回退：向前找 int3 填充或 ret 之后
    for back in range(1, 4096):
        b = read(va - back, 1)
        if b and b[0] == 0xCC:
            return va - back + 1, "int3 边界"
    return best or va, "猜测"


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    va = int(sys.argv[1], 16)
    maxi = int(sys.argv[2]) if len(sys.argv) > 2 else 80
    st, how = real_start(va)
    print(f"★ 调用点 {va:#x} → 函数起点 {st:#x}（{how}），偏移 +{va - st:#x}")
    print(f"{'地址':<12} 指令")
    n = 0
    for ins in MD.disasm(read(st, 4096), st):
        ann = ""
        if ins.mnemonic == "call":
            try:
                t = int(ins.op_str, 16)
            except ValueError:
                t = None
            if t is not None:
                ann = f"    → {t:#x}"
        elif ins.mnemonic == "push":
            try:
                imm = int(ins.op_str, 16)
            except ValueError:
                imm = None
            if imm:
                s = cstr(imm)
                if s:
                    ann = f'    → "{s}"'
                else:
                    sec = sec_of(imm)
                    ann = f"    → 立即数 {imm:#x}" + (f"（在 {sec['n']}）" if sec else "")
        print(f"{ins.address:#012x} {ins.mnemonic:<7} {ins.op_str}{ann}")
        n += 1
        if n >= maxi:
            print("  …（截断）")
            break
        if ins.mnemonic == "ret":
            break
    return 0


if __name__ == "__main__":
    sys.exit(main())
