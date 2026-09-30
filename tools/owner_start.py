"""定位包含某个返回地址的真实函数起点，并验证"它是个函数"。

动机：仅凭"E8 目标 + 序言"的函数起点集会出现**假起点**——假起点的判据是
「既没有任何 E8 调用者，也没有任何 4 字节数据指针引用它」。此时应改用
int3 填充边界反推真起点。

用法: python tools/owner_start.py 0x504a71 [0x5032dd ...]
"""
import struct
import sys
from capstone import Cs, CS_ARCH_X86, CS_MODE_32


def load():
    exe = open(r"C:\Games\LASR\LASR.exe", "rb").read()
    pe = struct.unpack_from("<I", exe, 0x3C)[0]
    nsec = struct.unpack_from("<H", exe, pe + 6)[0]
    optsz = struct.unpack_from("<H", exe, pe + 20)[0]
    base = struct.unpack_from("<I", exe, pe + 24 + 28)[0]
    secs = []
    for i in range(nsec):
        o = pe + 24 + optsz + i * 40
        vsz, va, rsz, ra = struct.unpack_from("<IIII", exe, o + 8)
        secs.append((va, vsz, ra, rsz))
    return exe, base, secs


EXE, BASE, SECS = load()


def off(r):
    for va, vsz, ra, rsz in SECS:
        if va <= r < va + max(vsz, rsz):
            return ra + (r - va)
    return None


def callers(target, txt, tva):
    out = []
    for j in range(len(txt) - 5):
        if txt[j] == 0xE8:
            rel = struct.unpack_from("<i", txt, j + 1)[0]
            if BASE + tva + j + 5 + rel == target:
                out.append(BASE + tva + j)
    return out


def data_refs(target):
    pat = struct.pack("<I", target)
    out = []
    for va, vsz, ra, rsz in SECS:
        b = EXE[ra:ra + min(vsz, rsz)]
        s = 0
        while True:
            k = b.find(pat, s)
            if k < 0:
                break
            out.append(BASE + va + k)
            s = k + 1
    return out


def real_start(addr):
    """从 addr 往前找最近的 int3 填充边界（>=3 个 0xCC 之后）。"""
    o = off(addr - BASE)
    back = EXE[max(0, o - 8000):o]
    for k in range(len(back) - 1, 2, -1):
        if back[k] == 0xCC and back[k - 1] == 0xCC and back[k - 2] == 0xCC:
            return addr - (len(back) - (k + 1))
    return None


def main(addrs):
    tva, tvsz, tra, trsz = SECS[0]
    txt = EXE[tra:tra + tvsz]
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    for a in addrs:
        print(f"\n=== 地址 0x{a:08x} ===")
        cand = real_start(a)
        print(f"  最近的 int3 填充边界（真函数起点候选）= "
              f"{'0x%08x' % cand if cand else '未找到'}")
        for t in ([cand] if cand else []) + [a]:
            cs = callers(t, txt, tva)
            dr = data_refs(t)
            verdict = ("✓ 像真函数起点" if (cs or dr)
                       else "✗ 假的：无调用者也无数据指针 ⇒ 不是函数起点")
            print(f"  0x{t:08x}: E8 调用者 {len(cs)} 个 {[hex(c) for c in cs[:4]]}, "
                  f"数据指针 {len(dr)} 处 {[hex(x) for x in dr[:3]]}  {verdict}")
        if cand and cand != a:
            o = off(cand - BASE)
            print(f"  真起点起的 14 条:")
            for i, ins in enumerate(md.disasm(EXE[o:o + 90], cand)):
                if i >= 14:
                    break
                print(f"     0x{ins.address:08x}  {ins.mnemonic:7s} {ins.op_str}")


if __name__ == "__main__":
    main([int(x, 16) for x in sys.argv[1:]] or [0x504a71])
