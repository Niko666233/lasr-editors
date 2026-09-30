"""在 .text 里找「某位移量被真正当作内存操作数使用」的位置（capstone 验证，不靠猜）。

教训来源：`0x20C` 的裸字节扫描会命中指令立即数/操作数巧合（`or al,2` 之类）。
本工具对每个候选位置，向前尝试 1..10 字节的指令起点，用 capstone 逐条解码，
只有当解码出的指令**恰好**以该位移作为内存操作数、且指令结束位置对得上时才报告。

用法: python tools/find_disp.py 0x140C [起始 VA 上限]
      python tools/find_disp.py 0x20C 0x48532d
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


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    disp = int(sys.argv[1], 16)
    limit = int(sys.argv[2], 16) if len(sys.argv) > 2 else 0
    pat = struct.pack("<I", disp)
    print(f"=== 查找位移 {disp:#x} 的**真实内存操作数**使用点（capstone 验证）===")
    found = 0
    for nm, b, ra, rsz in SECS:
        if nm != ".text":
            continue
        blob = E[ra:ra + rsz]
        i = 0
        while True:
            i = blob.find(pat, i)
            if i < 0:
                break
            va = b + i
            if limit and va > limit + 0x40:
                i += 1
                continue
            # 该位移在指令尾部（disp32 是最后 4 字节）：指令起点在 va-1..va-10
            for back in range(1, 11):
                st = va - back
                if st < b:
                    continue
                code = E[off(st)[0]: off(st)[0] + 16]
                insns = list(MD.disasm(code, st))
                if not insns:
                    continue
                ins = insns[0]
                if ins.address + ins.size != va + 4:
                    continue          # 必须正好结束在位移之后
                ops = ins.op_str
                if f"{disp:#x}" in ops and "[" in ops:
                    print(f"  {va:#x}  {ins.mnemonic:8s} {ops}")
                    found += 1
                    break
            i += 1
    print(f"命中 {found} 处")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
