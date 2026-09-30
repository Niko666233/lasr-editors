"""
Cross-check the opcode width table against the compiler's emit sites.

The statistical solver (tools/opcode_align.py) recovers 99.77% of method
records, but leaves 19 opcodes where the recovered width disagrees with what
the opcode's name implies.  Two independent signals in LASR.exe can settle
those:

  A) EMIT SITES.  The compiler emits `<u8 opcode>` and then, for opcodes that
     take an operand, a 4-byte value.  So a `mov byte ptr [reg+disp], imm8`
     with imm8 <= 0x54 followed (within a few instructions) by a 4-byte store
     proves that opcode carries an operand; the same instruction with no
     following dword store proves it does not.  The imm8 values that appear
     are also the *emitted* opcode set.

  B) DISPATCH.  The interpreter reads the opcode byte and compares it.  A
     cluster of `cmp <byte reg>, imm8` with imm8 <= 0x54 marks the dispatcher;
     the immediates that occur are again the opcode set.

Both are printed alongside the recovered table so disagreements stand out.
"""
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path

from capstone import Cs, CS_ARCH_X86, CS_MODE_32

sys.path.insert(0, str(Path(__file__).parent))

EXE = r"C:\Games\LASR\LASR.exe"
MAX_OP = 0x54                       # name table has 85 entries -> opcode <= 0x54


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


def main():
    d = Path(EXE).read_bytes()
    secs = sections(d)
    text = next(s for s in secs if s[0] == ".text")
    nm, va, vsz, raw, rsz = text
    code = d[raw:raw + rsz]
    print(f".text  VA 0x{0x400000+va:x}  file 0x{raw:x}  {rsz:,} bytes")

    md = Cs(CS_ARCH_X86, CS_MODE_32)
    md.detail = True

    emit = defaultdict(lambda: {"n": 0, "dword_after": 0, "float_after": 0,
                                "offsets": []})
    cmpc = Counter()
    cmpcluster = defaultdict(int)
    insns = list(md.disasm(code, 0x400000 + va))
    print(f"disassembled {len(insns):,} instructions")

    # ---- A) emit sites: mov byte ptr [mem], imm8
    for i, ins in enumerate(insns):
        if ins.mnemonic != "mov" or len(ins.operands) != 2:
            continue
        dst, src = ins.operands
        if dst.type != 0 or src.type != 2:      # X86_OP_MEM=3? use cs constants
            pass
        try:
            from capstone.x86_const import X86_OP_MEM, X86_OP_IMM, X86_OP_REG
        except Exception:
            continue
        if dst.type != X86_OP_MEM or src.type != X86_OP_IMM:
            continue
        if dst.size != 1:
            continue
        imm = src.imm
        if not (0 <= imm <= MAX_OP):
            continue
        rec = emit[imm]
        rec["n"] += 1
        rec["offsets"].append(ins.address)
        # look ahead a little for a 4-byte store / float move
        for j in range(i + 1, min(i + 8, len(insns))):
            nx = insns[j]
            if nx.mnemonic in ("ret", "call", "jmp"):
                break
            if nx.mnemonic != "mov" or len(nx.operands) != 2:
                continue
            a, b = nx.operands
            if a.type == X86_OP_MEM and a.size == 4 and b.type in (X86_OP_REG, X86_OP_IMM):
                rec["dword_after"] += 1
                break
        for j in range(i + 1, min(i + 8, len(insns))):
            nx = insns[j]
            if nx.mnemonic in ("fld", "fstp", "fsts", "movss", "push") and "0x" in nx.op_str:
                rec["float_after"] += 1
                break

    # ---- B) cmp clusters: cmp <8-bit reg>, imm8
    try:
        from capstone.x86_const import X86_OP_IMM, X86_OP_REG
    except Exception:
        return
    for ins in insns:
        if ins.mnemonic != "cmp" or len(ins.operands) != 2:
            continue
        a, b = ins.operands
        if a.type != X86_OP_REG or b.type != X86_OP_IMM:
            continue
        if a.size != 1 or not (0 <= b.imm <= MAX_OP):
            continue
        cmpc[b.imm] += 1
        cmpcluster[ins.address >> 12] += 1

    print(f"\n=== A) emit sites: `mov byte ptr [mem], imm8` with imm8 <= 0x54 ===")
    print(f"  distinct imm8 values: {len(emit)}   total sites: {sum(v['n'] for v in emit.values())}")
    ops = sorted(emit)
    print(f"  values: {' '.join(f'{v:02x}' for v in ops)}")
    print(f"\n  {'imm':>4} {'count':>6} {'dwordStoreAfter':>16} {'floatNear':>10}")
    for v in ops:
        r = emit[v]
        print(f"  0x{v:02x} {r['n']:>6} {r['dword_after']:>16} {r['float_after']:>10}")

    print(f"\n=== B) cmp <byte reg>, imm8 clusters ===")
    print(f"  distinct imm8 values: {len(cmpc)}   total sites: {sum(cmpc.values())}")
    print(f"  values: {' '.join(f'{v:02x}' for v in sorted(cmpc))}")
    top = cmpcluster.most_common(6)
    print("  densest 4 KB pages:", " ".join(f"0x{p<<12:x}:{n}" for p, n in top))


if __name__ == "__main__":
    main()
