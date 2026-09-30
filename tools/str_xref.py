"""Locate xrefs to a set of byte-strings inside LASR.exe (push imm32 of the VA)."""
import struct
import sys
from capstone import CS_ARCH_X86, CS_MODE_32, Cs

EXE = open(r"C:\Games\LASR\LASR.exe", "rb").read()
PE = struct.unpack_from("<I", EXE, 0x3C)[0]
NSEC = struct.unpack_from("<H", EXE, PE + 6)[0]
OPTSZ = struct.unpack_from("<H", EXE, PE + 20)[0]
BASE = struct.unpack_from("<I", EXE, PE + 24 + 28)[0]
secs = []
for i in range(NSEC):
    o = PE + 24 + OPTSZ + i * 40
    nm = EXE[o:o + 8].rstrip(b"\0").decode("latin1")
    vsz, va, rsz, ra = struct.unpack_from("<IIII", EXE, o + 8)
    ch = struct.unpack_from("<I", EXE, o + 36)[0]
    secs.append((nm, va + BASE, vsz, ra, rsz, ch))


def va_of_off(off):
    for nm, va, vsz, ra, rsz, ch in secs:
        if ra <= off < ra + rsz:
            return va + (off - ra)
    return None


targets = {}
for want in sys.argv[1:]:
    b = want.encode("latin1") + b"\0"
    i = EXE.find(b)
    va = va_of_off(i) if i >= 0 else None
    targets[want] = va
    print("%-45s file=%s va=%s" % (want, hex(i) if i >= 0 else None,
                                   hex(va) if va else None))

TEXT = None
for nm, va, vsz, ra, rsz, ch in secs:
    if ch & 0x20000000 and rsz:
        TEXT = (va, EXE[ra:ra + rsz])
tv, tb = TEXT
md = Cs(CS_ARCH_X86, CS_MODE_32)
md.detail = True
EXECUTE = 0x20000000
found = {k: [] for k in targets}
for ins in md.disasm(tb, tv):
    if ins.mnemonic == "push" and ins.operands:
        op = ins.operands[0]
        if op.type == 2:  # imm
            v = op.imm & 0xFFFFFFFF
            for k, t in targets.items():
                if t is not None and v == t:
                    found[k].append(ins.address)
for k, v in found.items():
    print("--- xref to %r: count=%d" % (k, len(v)))
    for a in v[:12]:
        print("    push %s" % hex(a))
