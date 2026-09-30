"""线性反汇编：从一个**已知是指令起点**的地址出发，先往前找函数起点（最近的
0xCC 填充或 ret 之后），再用 capstone 线性扫出真实指令流。

为什么需要它：`at.py` 的启发式会对不齐；而 capstone 能确认某个地址是指令起点，
却又不知道前面从哪开始。本工具把两件事合起来 —— 起点由「padding/ret 边界」给定，
解码交给 capstone，结果是**逐条可信**的（不会出现把立即数当指令的假起点）。

用法: python tools/dis_linear.py <地址> [向前搜索字节数=0x600] [向后显示的字节数=0x200]
例:   python tools/dis_linear.py 0x47af4e
      python tools/dis_linear.py 0x564319
"""
import struct
import sys

from capstone import Cs, CS_ARCH_X86, CS_MODE_32

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
MD = Cs(CS_ARCH_X86, CS_MODE_32)


def off(va):
    for nm, b, ra, rsz in SECS:
        if b <= va < b + rsz:
            return ra + va - b, nm
    return None, None


def find_start(va, back):
    """往前找最近的 0xCC 填充块之后（函数边界的可靠标志）"""
    o, _ = off(va)
    for k in range(1, back):
        b = E[o - k]
        if b == 0xCC and E[o - k - 1] == 0xCC:
            return va - k + 1
    return va - back


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    tgt = int(sys.argv[1], 16)
    back = int(sys.argv[2], 16) if len(sys.argv) > 2 else 0x600
    fwd = int(sys.argv[3], 16) if len(sys.argv) > 3 else 0x200
    start = find_start(tgt, back)
    o, nm = off(start)
    if o is None:
        print(f"{start:#x} 不在任何节")
        return 1
    print(f"=== 起点 {start:#x}（距目标 {tgt - start:#x} 字节） [{nm}] ===")
    code = E[o:o + (tgt - start) + fwd]
    for ins in MD.disasm(code, start):
        mark = "   ←★" if f"A + 0x{tgt - start:x}" == "" else ""
        print(f"  {ins.address:#010x}  {ins.mnemonic:8s} {ins.op_str}{mark}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
