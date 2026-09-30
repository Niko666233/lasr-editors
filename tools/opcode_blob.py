"""
Dump the .rdata string blob that holds the VM's opcode / node names, in
address order.

If the opcodes are stored as an enum, the compiler's name table usually lists
them in numeric order, so the *position* of a name in the blob is its opcode
number.  The termination byte observed at the end of TREE method records is
0x16 = 22, so the 22nd name in the blob should read like a method-return or
end-of-block token.

Usage: python tools/opcode_blob.py [--va 0x723a98] [--span 0x800]
"""
import re
import struct
import sys
from pathlib import Path

EXE = r"C:\Games\LASR\LASR.exe"
IB = 0x400000


def sections(d):
    pe = struct.unpack_from("<I", d, 0x3C)[0]
    nsec = struct.unpack_from("<H", d, pe + 6)[0]
    optsz = struct.unpack_from("<H", d, pe + 20)[0]
    base = pe + 24 + optsz
    out = []
    for i in range(nsec):
        o = base + 40 * i
        nm = d[o:o + 8].rstrip(b"\0").decode("latin1")
        vsz, va, rsz, raw = struct.unpack_from("<IIII", d, o + 8)
        out.append((nm, va, vsz, raw, rsz))
    return out


def va2off(secs, va):
    va -= IB                       # section table holds RVAs, not VAs
    for nm, sva, vsz, raw, rsz in secs:
        if sva <= va < sva + max(vsz, rsz):
            return raw + (va - sva)
    return None


def main():
    d = open(EXE, "rb").read()
    secs = sections(d)
    print("sections:", [(s[0], hex(s[1]), hex(s[3])) for s in secs])

    va = 0x723A98
    span = 0x800
    use_off = "--off" in sys.argv
    if "--va" in sys.argv:
        va = int(sys.argv[sys.argv.index("--va") + 1], 0)
    if "--span" in sys.argv:
        span = int(sys.argv[sys.argv.index("--span") + 1], 0)

    if use_off:
        off = va                      # 0x723a98 exceeds SizeOfImage, so the
        va = None                     # recorded value is a file offset
    else:
        off = va2off(secs, va)
    print(f"start={va if va is not None else ''} -> file {off:#x}"
          if off is not None else "unmapped")
    if off is None:
        return
    buf = d[off - span:off + span]
    base = va - span if va is not None else off - span

    # every NUL-terminated printable run, with its address
    lbl = "VA" if va is not None else "file"
    print(f"\nstrings around {lbl} {hex(base + span)} in ADDRESS order:\n")
    i = 0
    idx = 0
    while i < len(buf):
        j = i
        while j < len(buf) and 0x20 <= buf[j] < 0x7F:
            j += 1
        if j - i >= 3 and j < len(buf) and buf[j] == 0:
            sva = va - span + i
            print(f"  [{idx:3d}] {sva:#09x}  {buf[i:j].decode('latin1')}")
            idx += 1
            i = j + 1
        else:
            i += 1


if __name__ == "__main__":
    main()
