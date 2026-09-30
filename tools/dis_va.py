"""
Disassemble a VA range of LASR.exe.

Usage:  python tools/dis_va.py 0x653880 0x653980 [--raw]

Prints each instruction with its VA, so a dispatch site found by
tools/dispatch_table.py can be read in context.  --raw prints the bytes too,
which matters when checking whether a `movzx` reads one byte or two.
"""
import struct
import sys
from pathlib import Path

from capstone import Cs, CS_ARCH_X86, CS_MODE_32

EXE = r"C:\Games\LASR\LASR.exe"
IB = 0x400000


def sections(d):
    pe = struct.unpack_from("<I", d, 0x3C)[0]
    n = struct.unpack_from("<H", d, pe + 6)[0]
    opt = struct.unpack_from("<H", d, pe + 20)[0]
    out = []
    for i in range(n):
        o = pe + 24 + opt + i * 40
        nm = d[o:o + 8].rstrip(b"\0").decode("latin1")
        vsz, va, rsz, raw = struct.unpack_from("<IIII", d, o + 8)
        out.append((nm, va, vsz, raw, rsz))
    return out


def va2off(secs, va):
    r = va - IB
    for nm, sva, vsz, raw, rsz in secs:
        if sva <= r < sva + max(vsz, rsz):
            return raw + (r - sva)
    return None


def sweep(md, code, base, limit):
    out, off = [], 0
    while off < len(code) and len(out) < limit:
        for ins in md.disasm(code[off:off + 32], base + off):
            out.append(ins)
            off += ins.size
            break
        else:
            off += 1
    return out


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    raw = "--raw" in sys.argv
    start = int(args[0], 0)
    end = int(args[1], 0) if len(args) > 1 else start + 0x100
    d = Path(EXE).read_bytes()
    secs = sections(d)
    o = va2off(secs, start)
    if o is None:
        print("not mapped")
        return
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    md.detail = True
    insns = sweep(md, d[o:o + (end - start)], start, 400)
    for ins in insns:
        line = f"0x{ins.address:x}  {ins.mnemonic:<7} {ins.op_str}"
        if raw:
            line = f"0x{ins.address:x}  {ins.bytes.hex():<20} {ins.mnemonic:<7} {ins.op_str}"
        print(line)


if __name__ == "__main__":
    main()
