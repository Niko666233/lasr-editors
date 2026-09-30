"""按**位移区间**找真实内存操作数的使用点（capstone 验证）。

背景：Pacejka 的 36 个系数在对象里是 `[base + slot*4]`，`base = +0x20C`。
力公式读某个槽时，指令形态必然是
    movss xmm?, dword ptr [reg + 0x20C + 4*K]
⇒ 只要把**位移落在 [0x20C, 0x2A0) 区间内**的真实操作数全找出来，
  每条命中的「位移 → 槽号 = (位移-0x20C)/4」，配合该处上下文就能给槽命名。

验证方式与 find_disp.py 一致：对每个候选位置向前试 1..10 字节的指令起点，
用 capstone 解码，只接受「是内存操作数、位移在该区间、且指令恰好结束于位移之后」。

用法: python tools/find_disp_range.py 0x20C 0x2A0
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
    lo = int(sys.argv[1], 16)
    hi = int(sys.argv[2], 16) if len(sys.argv) > 2 else lo + 4
    rlo = int(sys.argv[3], 16) if len(sys.argv) > 3 else 0     # ★ 可选：限定代码地址范围
    rhi = int(sys.argv[4], 16) if len(sys.argv) > 4 else 0xFFFFFFFF
    print(f"=== 位移区间 [{lo:#x}, {hi:#x}) 的真实内存操作数"
          f"（代码范围 {rlo:#x}–{rhi:#x}）===")
    hits = {}
    for nm, b, ra, rsz in SECS:
        if nm != ".text":
            continue
        blob = E[ra:ra + rsz]
        for d in range(lo, hi, 4):
            pat = struct.pack("<I", d)
            i = 0
            while True:
                i = blob.find(pat, i)
                if i < 0:
                    break
                va = b + i
                if not (rlo <= va < rhi):
                    i += 1
                    continue
                for back in range(1, 11):
                    st = va - back
                    if st < b:
                        continue
                    o, _ = off(st)
                    insns = list(MD.disasm(E[o:o + 16], st))
                    if not insns:
                        continue
                    ins = insns[0]
                    if ins.address + ins.size != va + 4:
                        continue
                    if "[" in ins.op_str and f"{d:#x}" in ins.op_str:
                        hits.setdefault(d, []).append(
                            (va, f"{ins.mnemonic} {ins.op_str}"))
                        break
                i += 1
    tot = 0
    for d in sorted(hits):
        slot = (d - lo) // 4 if lo == 0x20C else None
        tag = f"槽 {slot}" if slot is not None else ""
        print(f"\n--- 位移 {d:#x} {tag}  ({len(hits[d])} 处) ---")
        for va, txt in hits[d]:
            print(f"    {va:#010x}  {txt}")
        tot += len(hits[d])
    print(f"\n合计 {tot} 处")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
