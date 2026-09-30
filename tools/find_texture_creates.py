"""找出 D3D9 的 "创建表面/纹理" 调用点，并打印附近 push 的尺寸立即数。

动机：判定某个离屏渲染目标是什么（阴影图 / 镜像 / 后处理）最快的一步，
是看它的创建尺寸——阴影图往往是固定且非屏幕比例的（如 1664x1024），
镜像通常等于屏幕尺寸，后处理通常等于屏幕或半屏。

D3D9 设备槽号：CreateRenderTarget=23(0x5c)、CreateDepthStencilSurface=24(0x60)、
CreateTexture=25(0x64)、CreateOffscreenPlainSurface=35(0x8c)。
"""
import re
import struct

from capstone import Cs, CS_ARCH_X86, CS_MODE_32

EXE = open(r"C:\Games\LASR\LASR.exe", "rb").read()
PE = struct.unpack_from("<I", EXE, 0x3C)[0]
NSEC = struct.unpack_from("<H", EXE, PE + 6)[0]
OPTSZ = struct.unpack_from("<H", EXE, PE + 20)[0]
BASE = struct.unpack_from("<I", EXE, PE + 24 + 28)[0]
SECS = []
for _i in range(NSEC):
    _o = PE + 24 + OPTSZ + _i * 40
    _vsz, _va, _rsz, _ra = struct.unpack_from("<IIII", EXE, _o + 8)
    SECS.append((_va, _vsz, _ra, _rsz))

MD = Cs(CS_ARCH_X86, CS_MODE_32)
NAMES = {23: "CreateRenderTarget", 24: "CreateDepthStencilSurface",
         25: "CreateTexture", 35: "CreateOffscreenPlainSurface",
         26: "CreateVertexBuffer", 27: "CreateIndexBuffer"}
OFF2SLOT = {v * 4: k for k, v in NAMES.items()}

tva, tvsz, tra, trsz = SECS[0]
text = EXE[tra:tra + tvsz]
sites = []
for j in range(len(text) - 6):
    # call dword ptr [reg + disp8/disp32] : FF 50 xx / FF 90 xx xx xx xx
    if text[j] != 0xFF:
        continue
    b1 = text[j + 1]
    if 0x50 <= b1 <= 0x57:                       # call [reg + disp8]
        disp = text[j + 2]
    elif 0x90 <= b1 <= 0x97:                     # call [reg + disp32]
        disp = struct.unpack_from("<i", text, j + 2)[0]
    else:
        continue
    if disp in OFF2SLOT:
        sites.append((BASE + tva + j, OFF2SLOT[disp]))

print(f"找到 {len(sites)} 个 创建类 调用点\n")
for addr, slot in sites:
    o = None
    rva = addr - BASE
    for va, vsz, ra, rsz in SECS:
        if va <= rva < va + max(vsz, rsz):
            o = ra + (rva - va)
            break
    back = EXE[max(0, o - 60):o + 6]
    pushes = []
    for ins in MD.disasm(back, addr - 60):
        if ins.mnemonic == "push" and not ins.op_str.startswith(("e", "d", "c", "b")):
            pushes.append(ins.op_str)
    nums = []
    for p in pushes:
        try:
            nums.append(int(p, 16))
        except ValueError:
            nums.append(p)
    print(f"  0x{addr:08x}  {NAMES[slot]:<28} push 序列: {pushes}")
    cand = [n for n in nums if isinstance(n, int) and n > 64]
    if cand:
        print(f"        ⇒ 候选尺寸/常量: {[hex(c) + f'({c})' for c in cand[-6:]]}")
