"""
Find the VM's opcode dispatch jump table.

The interpreter reads the opcode byte and dispatches.  Two shapes are common:

    jmp dword ptr [reg*4 + disp32]      FF 24 8D/85/95/9D/B5/BD ...
    movzx eax, byte [reg] ; jmp [eax*4 + disp32]

Either way a table of code pointers appears in .rdata/.text whose length is the
size of the opcode enum.  If that length is 85 it independently confirms the
name-table size, and the handler bodies tell us which opcodes consume a 4-byte
operand (those handlers read [stream+1]).
"""
import struct
import sys
from pathlib import Path

from capstone import Cs, CS_ARCH_X86, CS_MODE_32
from capstone.x86_const import X86_OP_MEM, X86_OP_REG

sys.path.insert(0, str(Path(__file__).parent))
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
            o = raw + (r - sva)
            return o if 0 <= o < 0x1000000 else None
    return None


def sweep(md, code, base):
    """Linear sweep that resynchronises after undecodable bytes.

    Plain `md.disasm` STOPS at the first byte it cannot decode, which silently
    truncates the scan to a fraction of .text (a 3 MB .text appeared to hold
    only 79k instructions).  Skip one byte and carry on instead.
    """
    out = []
    off = 0
    n = len(code)
    while off < n:
        got = False
        for ins in md.disasm(code[off:off + 64], base + off):
            out.append(ins)
            off += ins.size
            got = True
            break
        if not got:
            off += 1
    return out


def main():
    d = Path(EXE).read_bytes()
    secs = sections(d)
    t = next(s for s in secs if s[0] == ".text")
    code = d[t[3]:t[3] + t[4]]

    md = Cs(CS_ARCH_X86, CS_MODE_32)
    md.detail = True
    insns = sweep(md, code, IB + t[1])
    print(f".text {len(insns):,} instructions "
          f"({len(code)/max(len(insns),1):.1f} bytes/insn)")

    # ---- candidate dispatch jumps
    cands = []
    for i, ins in enumerate(insns):
        if ins.mnemonic != "jmp" or len(ins.operands) != 1:
            continue
        op = ins.operands[0]
        if op.type != X86_OP_MEM:
            continue
        m = op.mem
        if not (m.index and 4 == op.size == 4):
            continue
        if m.scale != 4:
            continue
        cands.append((ins.address, m.disp, i))

    print(f"jmp dword ptr [reg*4+disp] sites: {len(cands)}")

    seen = {}
    for addr, disp, i in cands:
        seen.setdefault(disp, []).append(addr)

    print(f"\n{'table VA':>12} {'entries':>8} {'all .text?':>10}  jmp sites")
    report = []
    for disp, sites in seen.items():
        off = va2off(secs, disp)
        if off is None:
            continue
        n = 0
        while True:
            o = off + n * 4
            if o + 4 > len(d):
                break
            v = struct.unpack_from("<I", d, o)[0]
            if va2off(secs, v) is None:
                break
            n += 1
            if n > 4096:
                break
        if n < 8:
            continue
        report.append((n, disp, sites))
    report.sort(reverse=True)
    for n, disp, sites in report[:14]:
        print(f"  0x{disp:08x} {n:>8} {'yes':>10}  {len(sites)} sites @ "
              + " ".join(f"0x{a:x}" for a in sites[:4]))
    print()
    for n, disp, sites in report[:6]:
        print(f"  table 0x{disp:08x} ({n} entries) first 12:")
        off = va2off(secs, disp)
        vals = [struct.unpack_from("<I", d, off + k * 4)[0] for k in range(min(n, 12))]
        print("    " + " ".join(f"0x{v:x}" for v in vals))


if __name__ == "__main__":
    main()
