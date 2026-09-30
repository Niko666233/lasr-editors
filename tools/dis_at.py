"""以「已知的指令起点」为基准，向前找能**精确解码到**它的起点，再线性输出。

与 at.py 的区别：解码全部交给 capstone，且向前搜索的判据是
「从候选起点线性解码，必须有一条指令的结束地址**正好等于**目标地址」——
x86 变长编码下这是强判据，能把假起点排除掉（at.py 的启发式在 0x47af4e 上失败过）。

用法: python tools/dis_at.py <目标地址> [向前字节=0x200] [向后字节=0x180]
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


def find_precise_start(tgt, back):
    """找一个起点，使线性解码中某条指令恰好结束于 tgt"""
    o, _ = off(tgt - back)
    if o is None:
        return None
    code = E[o:o + back + 16]
    best = None
    for ins in MD.disasm(code, tgt - back):
        if ins.address + ins.size == tgt:
            best = ins.address
        if ins.address >= tgt:
            break
    return best


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    tgt = int(sys.argv[1], 16)
    back = int(sys.argv[2], 16) if len(sys.argv) > 2 else 0x200
    fwd = int(sys.argv[3], 16) if len(sys.argv) > 3 else 0x180
    st = find_precise_start(tgt, back)
    if "--from" in sys.argv:
        st = tgt                      # 目标本身就是已知的指令起点，直接从这里往后读
    if st is None:
        print(f"✗ 在 {back:#x} 字节内找不到能精确解码到 {tgt:#x} 的起点")
        return 1
    o, nm = off(st)
    disp = tgt - st
    print(f"=== 精确起点 {st:#x}（目标 {tgt:#x} 即 +{disp:#x}） [{nm}] ===")
    for ins in MD.disasm(E[o:o + disp + fwd], st):
        mark = "   ←★目标" if ins.address == tgt else ""
        print(f"  {ins.address:#010x}  {ins.mnemonic:8s} {ins.op_str}{mark}")
        if ins.address > tgt + fwd:
            break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
