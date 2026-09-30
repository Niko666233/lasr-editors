"""
Find every `jmp dword ptr [reg*4 + disp32]` jump table in LASR.exe and report the
tables that look like bytecode/opcode dispatchers (many entries, all targets
inside .text).

Usage: python tools/jumptables.py [min_entries]
"""
import collections
import struct
import sys

from capstone import Cs, CS_ARCH_X86, CS_MODE_32

EXE = r"C:\Games\LASR\LASR.exe"
IMAGE_BASE = 0x400000
TEXT_LO, TEXT_HI = 0x1000, 0x2E6000


def main():
    min_entries = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    d = open(EXE, "rb").read()
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    md.detail = True

    tables = collections.OrderedDict()
    # walk .text linearly; watch for `movzx reg, byte ptr [...]` then
    # `jmp dword ptr [reg*4 + disp]`
    prev_movzx = None
    for i in md.disasm(d[TEXT_LO:TEXT_HI], TEXT_LO):
        if i.mnemonic == "movzx" and "byte ptr" in i.op_str:
            try:
                prev_movzx = (i.address, i.op_str)
            except Exception:
                pass
            continue
        if i.mnemonic == "jmp" and "*4 +" in i.op_str and prev_movzx:
            disp = None
            for tok in i.op_str.replace("]", "").split():
                if tok.startswith("0x"):
                    disp = int(tok, 16)
            if disp is not None:
                tables[disp] = prev_movzx
        prev_movzx = None

    print(f"found {len(tables)} byte-index dispatch sites")
    rows = []
    for disp, mv in tables.items():
        rva = disp - IMAGE_BASE if disp >= IMAGE_BASE else disp
        # count consecutive dwords that are plausible code pointers
        n = 0
        while True:
            off = rva + 4 * n
            if off + 4 > len(d):
                break
            v = struct.unpack_from("<I", d, off)[0]
            if not (IMAGE_BASE + TEXT_LO <= v < IMAGE_BASE + TEXT_HI):
                break
            n += 1
        if n >= min_entries:
            rows.append((n, rva, mv))
    rows.sort(reverse=True)
    for n, rva, mv in rows[:40]:
        tgts = sorted({struct.unpack_from("<I", d, rva + 4 * k)[0] - IMAGE_BASE
                       for k in range(n)})
        print(f"\ntable rva {rva:#08x}  entries={n}  "
              f"(dispatch from movzx at rva {mv[0]:#x}: {mv[1]})")
        print(f"    distinct targets={len(tgts)}  first={[hex(t) for t in tgts[:12]]}")
        print(f"    entries: {[hex(struct.unpack_from('<I', d, rva + 4*k)[0]-IMAGE_BASE) for k in range(min(n,20))]}")


if __name__ == "__main__":
    main()
