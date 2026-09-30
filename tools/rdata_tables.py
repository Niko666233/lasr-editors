"""Dump runs of code-pointer dwords in the .rdata region right after the VM
opcode-name strings - candidate node-type dispatch / handler tables."""
import struct
import sys

EXE = r"C:\Games\LASR\LASR.exe"
IB = 0x400000
TEXT_LO, TEXT_HI = 0x401000, 0x6E5809          # .text VA range

d = open(EXE, "rb").read()
lo = int(sys.argv[1], 16) if len(sys.argv) > 1 else 0x323e00
hi = int(sys.argv[2], 16) if len(sys.argv) > 2 else 0x325200

for base in range(lo, hi, 4):
    run = []
    off = base
    while off + 4 <= hi:
        v = struct.unpack_from("<I", d, off)[0]
        if TEXT_LO <= v <= TEXT_HI:
            run.append(v)
            off += 4
        else:
            break
    if len(run) >= 6:
        print(f"=== code-pointer run @ file {base:#x} (VA {IB+base:#x}), "
              f"{len(run)} entries ===")
        for i, v in enumerate(run):
            print(f"   [{i:3d}] {v:#010x}   (rva {v-IB:#x})")
        print()
