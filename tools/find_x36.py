"""找出所有「按 36 槽做索引计算」的位置 —— 即 Pacejka 系数的**访问点**。

原理：系数访问必然形如 `p[entry*36 + slot]`。MSVC 会把它编成
  ① `imul reg, reg, 0x24`            (= *36)              字节 6B ?? 24
  ② `lea  reg, [reg + reg*8]`        (= *9，随后 *4)      字节 8D ?? C0 一类
  ③ `lea  reg, [reg + reg*4]`        (= *5)
本工具扫 ①②，并把结果按代码区归类 —— 落在车辆物理区（0x44–0x4c）的就是候选。

用法: python tools/find_x36.py
"""
import struct

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


def scan_imul():
    """imul reg, reg, 0x24  → 6B /r 24"""
    out = []
    for nm, b, ra, rsz in SECS:
        if nm != ".text":
            continue
        blob = E[ra:ra + rsz]
        i = 0
        while True:
            i = blob.find(b"\x6b", i)
            if i < 0:
                break
            va = b + i
            if i + 2 < len(blob) and blob[i + 2] == 0x24:
                ins = list(MD.disasm(E[ra + i:ra + i + 8], va))
                if ins and ins[0].mnemonic == "imul" and "0x24" in ins[0].op_str:
                    out.append((va, f"{ins[0].mnemonic} {ins[0].op_str}"))
            i += 1
    return out


def scan_mul9():
    """lea reg,[reg+reg*8] → 8D ?? C0/C1/...（modrm 后紧跟 SIB 且 scale=3）"""
    out = []
    for nm, b, ra, rsz in SECS:
        if nm != ".text":
            continue
        blob = E[ra:ra + rsz]
        i = 0
        while True:
            i = blob.find(b"\x8d", i)
            if i < 0:
                break
            va = b + i
            # modrm: mod=00, reg=目标, rm=100(SIB)；SIB: scale=11, index=reg, base=reg
            if i + 3 < len(blob):
                m = blob[i + 1]
                s = blob[i + 2]
                if (m & 0xC7) == 0x04 and (s & 0xC7) == 0xC0 and (s >> 6) == 3:
                    ins = list(MD.disasm(E[ra + i:ra + i + 8], va))
                    if ins and ins[0].mnemonic == "lea":
                        op = ins[0].op_str.replace(" ", "")
                        # 形如 eax,[eax+eax*8]
                        dst = op.split(",")[0]
                        if f"[{dst}+{dst}*8]" in op:
                            out.append((va, f"lea {ins[0].op_str}   (= *9)"))
            i += 1
    return out


a = scan_imul()
b = scan_mul9()
print(f"=== imul reg,reg,0x24（×36）: {len(a)} 处 ===")
for va, t in a:
    tag = "   ← 车辆物理区" if 0x440000 <= va < 0x4c0000 else ""
    print(f"  {va:#010x}  {t}{tag}")
print(f"\n=== lea reg,[reg+reg*8]（×9，配合 *4 得 ×36）: {len(b)} 处 ===")
for va, t in b:
    tag = "   ← 车辆物理区" if 0x440000 <= va < 0x4c0000 else ""
    print(f"  {va:#010x}  {t}{tag}")
