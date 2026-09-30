"""找出所有 call（E8 rel32）到指定函数的调用点，并把每个调用点【前文】对齐反汇编。

为什么不用"找函数起点"：x86 是变长编码，从错误的起点出发往往也能"解码到"目标
地址（只是沿途全是垃圾指令），所以起点推断很容易被骗。反过来做更可靠：
先精确扫描出所有 E8 调用点，再对每个调用点尝试若干起始偏移，**只接受**那条
解码路径里该地址确实是 `call` 的偏移 —— 这样前文就是真的对齐的。

用法: python tools/calls_to.py 0x504a20 [前文指令数]
"""
import struct
import sys

from capstone import CS_ARCH_X86, CS_MODE_32, Cs

IMG = r"C:\Games\LASR\LASR.exe"
EXE = open(IMG, "rb").read()
PE = struct.unpack_from("<I", EXE, 0x3C)[0]
NSEC = struct.unpack_from("<H", EXE, PE + 6)[0]
OPTSZ = struct.unpack_from("<H", EXE, PE + 20)[0]
SECS = []
EXEC = []                                   # [(va, blob)] 所有含执行位的节
# ★★ 节表里的 VirtualAddress 是 RVA！必须加 ImageBase 才是运行时的绝对地址。
#   漏掉这一步会得到"任何目标都 0 匹配"的假结论（踩过）。
BASE = struct.unpack_from("<I", EXE, PE + 24 + 28)[0]
for _i in range(NSEC):
    _o = PE + 24 + OPTSZ + _i * 40
    _nm = EXE[_o:_o + 8].rstrip(b"\0").decode("latin1")
    _vsz, _va, _rsz, _ra = struct.unpack_from("<IIII", EXE, _o + 8)
    _chars = struct.unpack_from("<I", EXE, _o + 36)[0]
    _va += BASE                             # RVA → 绝对地址
    d = {"n": _nm, "va": _va, "vsz": _vsz, "ra": _ra, "rsz": _rsz, "ch": _chars}
    SECS.append(d)
    # 不靠节名（写死 ".text" 太脆）：凡带 IMAGE_SCN_MEM_EXECUTE(0x20000000) 的都扫
    if _rsz and (_chars & 0x20000000):
        EXEC.append((_va, EXE[_ra:_ra + _rsz]))

MD = Cs(CS_ARCH_X86, CS_MODE_32)


def off(va):
    for s in SECS:
        if s["va"] <= va < s["va"] + s["vsz"]:
            return s["ra"] + (va - s["va"])
    return None


def read(va, n):
    o = off(va)
    return None if o is None else EXE[o:o + n]


def cstr(va, maxlen=72):
    b = read(va, maxlen)
    if not b:
        return None
    e = b.find(b"\0")
    if e < 6:
        return None
    c = b[:e]
    if all(32 <= x < 127 or x in (9, 10, 13) for x in c):
        return c.decode("latin1")
    return None


def call_sites(target):
    out = []
    for va0, blob in EXEC:
        i = 0
        while True:
            i = blob.find(b"\xe8", i)
            if i < 0 or i + 5 > len(blob):
                break
            rel = struct.unpack_from("<i", blob, i + 1)[0]
            site = va0 + i
            if (site + 5 + rel) == target:
                out.append(site)
            i += 1
    return sorted(out)


def aligned_back(site, count=14):
    """返回 (起始偏移, 指令列表)；挑能精确解码到 site 且 site 是 call 的偏移。"""
    for start in range(site - 64, site):
        if start < 0:
            continue
        buf = read(start, (site - start) + 8)
        if not buf:
            continue
        ins = list(MD.disasm(buf, start))
        hit = [k for k, x in enumerate(ins) if x.address == site]
        if not hit:
            continue
        if ins[hit[0]].mnemonic != "call":
            continue
        k = hit[0]
        return start, ins[max(0, k - count):k + 1]
    return None, []


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    target = int(sys.argv[1], 16)
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 14
    sites = call_sites(target)
    print(f"★ 调用 {target:#x} 的 E8 调用点共 {len(sites)} 个:")
    for s in sites:
        print(f"   {s:#x}")
    for s in sites:
        st, ins = aligned_back(s, n)
        print(f"\n=== 调用点 {s:#x}（前文自 {st and hex(st)} 对齐）===")
        if not ins:
            print("   ✗ 无法对齐解码")
            continue
        for x in ins:
            ann = ""
            if x.mnemonic == "push":
                try:
                    imm = int(x.op_str, 16)
                except ValueError:
                    imm = None
                if imm:
                    cs = cstr(imm)
                    ann = f'    → "{cs}"' if cs else f"    → {imm:#x}"
            elif x.mnemonic == "call":
                try:
                    t = int(x.op_str, 16)
                except ValueError:
                    t = None
                if t:
                    ann = f"    → {t:#x}"
            print(f"   {x.address:#012x} {x.mnemonic:<8} {x.op_str}{ann}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
