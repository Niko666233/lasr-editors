"""看任意地址处的代码：向前找对齐起点，反汇编到该地址（含）为止。

为什么反复需要它：x86 是变长编码，从错误起点反汇编会得到整片垃圾；而"函数起点
推断"又容易被数据里的 E8 骗。可靠办法是从该地址向前尝试若干起始偏移，只接受
能**精确解码到**该地址的那一条路径（优先偏移最大的，即前文最准确）。

用法:
  python tools/at.py 0x509097 [前文指令数]
  python tools/at.py 0x509097 30 --raw      # 额外打印原始字节
"""
import struct
import sys

from capstone import CS_ARCH_X86, CS_MODE_32, Cs

IMG = r"C:\Games\LASR\LASR.exe"
EXE = open(IMG, "rb").read()
PE = struct.unpack_from("<I", EXE, 0x3C)[0]
NSEC = struct.unpack_from("<H", EXE, PE + 6)[0]
OPTSZ = struct.unpack_from("<H", EXE, PE + 20)[0]
BASE = struct.unpack_from("<I", EXE, PE + 24 + 28)[0]      # ★ 节表 VA 是 RVA
SECS = []
for _i in range(NSEC):
    _o = PE + 24 + OPTSZ + _i * 40
    _nm = EXE[_o:_o + 8].rstrip(b"\0").decode("latin1")
    _vsz, _va, _rsz, _ra = struct.unpack_from("<IIII", EXE, _o + 8)
    SECS.append({"n": _nm, "va": BASE + _va, "vsz": _vsz, "ra": _ra, "rsz": _rsz})

MD = Cs(CS_ARCH_X86, CS_MODE_32)


def off(va):
    for s in SECS:
        if s["va"] <= va < s["va"] + s["vsz"]:
            return s["ra"] + (va - s["va"])
    return None


def read(va, n):
    o = off(va)
    return None if o is None else EXE[o:o + n]


def cstr(va, maxlen=80):
    b = read(va, maxlen)
    if not b:
        return None
    e = b.find(b"\0")
    if e < 5:
        return None
    c = b[:e]
    if all(32 <= x < 127 or x in (9, 10, 13) for x in c):
        return c.decode("latin1")
    return None


def aligned_to(va, count):
    for start in range(va - 96, va):
        if start < 0:
            continue
        buf = read(start, (va - start) + 16)
        if not buf:
            continue
        ins = list(MD.disasm(buf, start))
        for k, x in enumerate(ins):
            if x.address == va:
                return ins[max(0, k - count):k + 1]
    return []


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    va = int(sys.argv[1], 16)
    count = int(sys.argv[2]) if len(sys.argv) > 2 else 24
    raw = "--raw" in sys.argv
    if "--from" in sys.argv:
        # 从该地址**向后**反汇编（用于"这里就是函数起点"的场合：已知的 call 目标）
        buf = read(va, 8192)
        if not buf:
            print(f"✗ 无法读取 {va:#x}")
            return 1
        print(f"★ 从 {va:#x} 向后反汇编（最多 {count} 条）")
        n = 0
        for x in MD.disasm(buf, va):
            ann = ""
            if x.mnemonic == "push":
                try:
                    imm = int(x.op_str, 16)
                except ValueError:
                    imm = None
                if imm:
                    s = cstr(imm)
                    ann = f'    → "{s}"' if s else f"    → {imm:#x} (= {imm})"
            elif x.mnemonic == "call":
                try:
                    t = int(x.op_str, 16)
                except ValueError:
                    t = None
                if t:
                    ann = f"    → {t:#x}"
            elif "0x" in x.op_str:
                for tok in x.op_str.replace(",", " ").split():
                    if tok.startswith("0x") and len(tok) >= 5:
                        try:
                            v = int(tok, 16)
                        except ValueError:
                            continue
                        s = cstr(v)
                        if s:
                            ann = f'    → "{s}"'
                            break
            print(f"   {x.address:#012x} {x.mnemonic:<8} {x.op_str}{ann}")
            if raw:
                o = off(x.address)
                print(f"                   bytes: {EXE[o:o + x.size].hex(' ')}")
            n += 1
            if n >= count:
                print("  …（截断）")
                break
            if x.mnemonic == "ret":
                break
        return 0
    ins = aligned_to(va, count)
    if not ins:
        print(f"✗ 无法对齐解码 {va:#x}")
        return 1
    print(f"★ 反汇编到 {va:#x}（自 {ins[0].address:#x} 起，共 {len(ins)} 条）")
    for x in ins:
        ann = ""
        if x.mnemonic == "push":
            try:
                imm = int(x.op_str, 16)
            except ValueError:
                imm = None
            if imm:
                s = cstr(imm)
                ann = f'    → "{s}"' if s else f"    → {imm:#x} (= {imm})"
        elif x.mnemonic == "call":
            try:
                t = int(x.op_str, 16)
            except ValueError:
                t = None
            if t:
                ann = f"    → {t:#x}"
        elif x.mnemonic in ("mov", "cmp", "add", "sub", "and", "or") and "0x" in x.op_str:
            for tok in x.op_str.replace(",", " ").split():
                if tok.startswith("0x") and len(tok) >= 5:
                    try:
                        v = int(tok, 16)
                    except ValueError:
                        continue
                    s = cstr(v)
                    if s:
                        ann = f'    → "{s}"'
                        break
        mark = "  ←★ 目标" if x.address == va else ""
        print(f"   {x.address:#012x} {x.mnemonic:<8} {x.op_str}{ann}{mark}")
        if raw:
            o = off(x.address)
            print(f"                   bytes: {EXE[o:o + x.size].hex(' ')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
