"""Disassemble a region of LASR.exe (rva == file offset for .text)."""
import sys
from capstone import Cs, CS_ARCH_X86, CS_MODE_32

EXE = r"C:\Games\LASR\LASR.exe"
IMAGE_BASE = 0x400000


def main():
    start = int(sys.argv[1], 16)
    end = int(sys.argv[2], 16)
    d = open(EXE, "rb").read()
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    for i in md.disasm(d[start:end], start):
        note = ""
        if i.mnemonic == "call":
            try:
                t = int(i.op_str, 16)
                note = f"   -> rva {t:#x}"
            except ValueError:
                pass
        elif i.mnemonic.startswith("j"):
            try:
                t = int(i.op_str, 16)
                note = f"   -> rva {t:#x}"
            except ValueError:
                pass
        print(f"{i.address:06x}  {i.bytes.hex():<22} {i.mnemonic} {i.op_str}{note}")


if __name__ == "__main__":
    main()
