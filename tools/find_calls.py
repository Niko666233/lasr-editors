"""Find every direct call/jmp (E8/E9 rel32) targeting a given RVA."""
import struct
import sys

EXE = r"C:\Games\LASR\LASR.exe"


def main():
    target = int(sys.argv[1], 16)
    d = open(EXE, "rb").read()
    lo, hi = 0x1000, 0x2E6000
    hits = []
    for off in range(lo, hi - 5):
        op = d[off]
        if op not in (0xE8, 0xE9):
            continue
        disp = struct.unpack_from("<i", d, off + 1)[0]
        if off + 5 + disp == target:
            hits.append((off, "call" if op == 0xE8 else "jmp"))
    print(f"{len(hits)} references to rva {target:#x} (va {0x400000+target:#x})")
    for off, kind in hits:
        print(f"  {kind} at rva {off:#x}")


if __name__ == "__main__":
    main()
