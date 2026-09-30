"""Scan LASR.exe .text for imm32 references to given strings' virtual addresses."""
import struct
import sys

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
EXECUTE = 0x20000000


def va_of_off(off):
    for nm, va, vsz, ra, rsz, ch in secs:
        if ra <= off < ra + rsz:
            return va + (off - ra)
    return None


for s in sys.argv[1:]:
    i = EXE.find(s.encode("latin1") + b"\0")
    if i < 0:
        print("%-40s NOT FOUND" % s)
        continue
    va = va_of_off(i)
    pat = struct.pack("<I", va)
    hits = []
    for nm, v, vs, ra, rs, ch in secs:
        if not (ch & EXECUTE) or not rs:
            continue
        blob = EXE[ra:ra + rs]
        j = 0
        while True:
            j = blob.find(pat, j)
            if j < 0:
                break
            hits.append(v + (j - ra))
            j += 1
    print("%-40s va=%s refs=%d %s" % (s, hex(va), len(hits),
                                      " ".join(hex(x) for x in hits[:12])))
