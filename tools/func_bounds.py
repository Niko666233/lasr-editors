"""找函数边界：判断 0x55a018（报 "Missing class"）与 0x55aea3（解 FLZD）
是不是同一个函数 —— 是的话，那 0x55axxx 就是类加载器，而它对非 FLZD 数据
是「跳过解压、原样留给解析器」（0x55aead: test ebp,ebp; jle skip）。
"""
import struct
import sys

sys.path.insert(0, "tools")
from capstone import CS_ARCH_X86, CS_MODE_32, Cs

EXE = open(r"C:\Games\LASR\LASR.exe", "rb").read()
PE = struct.unpack_from("<I", EXE, 0x3C)[0]
NSEC = struct.unpack_from("<H", EXE, PE + 6)[0]
OPTSZ = struct.unpack_from("<H", EXE, PE + 20)[0]
BASE = struct.unpack_from("<I", EXE, PE + 24 + 28)[0]
SECS = []
for i in range(NSEC):
    o = PE + 24 + OPTSZ + i * 40
    nm = EXE[o:o + 8].rstrip(b"\0").decode("latin1")
    vsz, va, rsz, ra = struct.unpack_from("<IIII", EXE, o + 8)
    SECS.append((nm, va + BASE, vsz, ra, rsz))

TEXT = [(va, EXE[ra:ra + rsz]) for nm, va, vsz, ra, rsz in SECS
        if nm == ".text" and rsz][0]
TV, TB = TEXT
md = Cs(CS_ARCH_X86, CS_MODE_32)
md.detail = True

START, END = 0x559000, 0x55b400
off = START - TV
blob = TB[off:END - TV]
prologues, rets = [], []
for ins in md.disasm(blob, START):
    m = ins.mnemonic
    if m == "ret" or m.startswith("ret"):
        rets.append((ins.address, m))
    elif m == "int3":
        pass
    elif m in ("push", "mov", "sub", "lea"):
        # 典型 prologue 头
        ops = ins.op_str
        if (m == "sub" and ops.startswith("esp, 0x")) or \
           (m == "push" and ops == "ebp") or \
           (m == "push" and ops.startswith("0x") and len(ops) >= 6) or \
           (m == "mov" and ops.startswith("edi, edi")):
            prologues.append((ins.address, "%s %s" % (m, ops)))

print("== 目标地址 ==")
for a in (0x55a018, 0x55a342, 0x55ae97, 0x55aea3, 0x55a26f, 0x55a2f0):
    prev_ret = max([r for r, _ in rets if r < a], default=0)
    prev_pro = max([p for p, _ in prologues if p <= a], default=0)
    next_ret = min([r for r, _ in rets if r > a], default=0)
    print("  %#x  前一个 ret=%#x 最近 prologue=%#x 下一个 ret=%#x"
          % (a, prev_ret, prev_pro, next_ret))

print("\n== 前一个 prologue 详情（看是不是函数开头）==")
for target in (0x55a018, 0x55aea3):
    prev_pro = max([p for p, _ in prologues if p <= target], default=0)
    prev_ret = max([r for r, _ in rets if r < target], default=0)
    print("target %#x: 最近 prologue %#x, 前一个 ret %#x -> 同一函数: %s"
          % (target, prev_pro, prev_ret, prev_pro > prev_ret))
