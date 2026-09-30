"""打印某个调用点前后的指令窗口，并把 push 的立即数解析成字符串/指针。

用法: python tools/call_window.py 0x4c0d44 0x4c19e9 [before] [after]

为什么需要它：判断"某个调用点的上下文在干什么"时，最有力的信号是
push 进去的立即数——如果它其实是个 char* 指向 .rdata 里的 ASCII，
那就是函数名/文件名/着色器名/调试串，一眼定性。
"""
import struct
import sys
from capstone import Cs, CS_ARCH_X86, CS_MODE_32

IMG = r"C:\Games\LASR\LASR.exe"
EXE = open(IMG, "rb").read()
PE = struct.unpack_from("<I", EXE, 0x3C)[0]
NSEC = struct.unpack_from("<H", EXE, PE + 6)[0]
OPTSZ = struct.unpack_from("<H", EXE, PE + 20)[0]
BASEOK = struct.unpack_from("<I", EXE, PE + 24 + 28)[0]
SECS = []
for _i in range(NSEC):
    _o = PE + 24 + OPTSZ + _i * 40
    _nm = EXE[_o:_o + 8].rstrip(b"\0").decode("latin1")
    _vsz, _va, _rsz, _ra = struct.unpack_from("<IIII", EXE, _o + 8)
    SECS.append({"n": _nm, "va": _va, "vsz": _vsz, "ra": _ra, "rsz": _rsz})

MD = Cs(CS_ARCH_X86, CS_MODE_32)


def off(rva):
    for s in SECS:
        if s["va"] <= rva < s["va"] + max(s["vsz"], s["rsz"]):
            return s["ra"] + (rva - s["va"])
    return None


def sec_of(rva):
    for s in SECS:
        if s["va"] <= rva < s["va"] + max(s["vsz"], s["rsz"]):
            return s
    return None


def as_string(va):
    """把虚拟地址当 C 字符串读；只在可读节里、且是真 ASCII 时返回。"""
    rva = va - BASEOK
    s = sec_of(rva)
    if not s:
        return None
    o = s["ra"] + (rva - s["va"])
    raw = EXE[o:o + 200]
    end = raw.find(b"\0")
    if end < 4:
        return None
    txt = raw[:end]
    if all(32 <= c < 127 or c in (9, 10, 13) for c in txt):
        try:
            return txt.decode("latin1")
        except Exception:
            return None
    return None


def window(addr, before=70, after=30):
    rva = addr - BASEOK
    o = off(rva - before)
    if o is None:
        print(f"  0x{addr:08x}: 地址不在镜像内")
        return
    code = EXE[o:o + before + after]
    for ins in MD.disasm(code, addr - before):
        mark = " <<<<<< 调用点" if ins.address == addr else ""
        note = ""
        if ins.mnemonic == "push":
            op = ins.op_str
            try:
                v = int(op, 16) if op.startswith("0x") else int(op)
            except ValueError:
                v = None
            if v is not None:
                st = as_string(v)
                if st:
                    note = f'   ; "{st}"'
                else:
                    s = sec_of(v - BASEOK) if v > BASEOK else None
                    if s:
                        note = f"   ; {s['n']} 内"
        print(f"  0x{ins.address:08x}  {ins.mnemonic:7s} {ins.op_str}{note}{mark}")


if __name__ == "__main__":
    args = sys.argv[1:]
    b = int(args.pop()) if args and args[-1].isdigit() else 70
    a = int(args.pop()) if args and args[-1].isdigit() else 30
    for x in args:
        print(f"\n{'=' * 70}\n★ 调用点 0x{int(x, 16):08x} 前后窗口\n{'=' * 70}")
        window(int(x, 16), b, a)
