"""
Locate the JavaMachine engine inside LASR.exe.

1. Locate the string literals and every code xref (push imm32 / mov reg, imm32).
2. Find enclosing function entries by scanning backwards for prologue padding.
3. Dump the enclosing function of each xref.

Output is plain text on stdout, meant to be read by a human.
"""
import re
import struct
import sys

from capstone import Cs, CS_ARCH_X86, CS_MODE_32

EXE = r"C:\Games\LASR\LASR.exe"
IMAGE_BASE = 0x400000

STRINGS = [
    "JavaMachine::isProductive: unknown parent node type: ",
    "JavaMachine::isProductive: unknown node type: ",
    "JavaMachine::loadClass: failed to load ",
    "JVM::stringConversion: cannot convert ",
    "parentclass cannot be specified for java.lang.Object",
    "Invalid mesh version! -> %s",
]

secs = []


def load():
    d = open(EXE, "rb").read()
    pe = struct.unpack_from("<I", d, 0x3C)[0]
    base = struct.unpack_from("<I", d, pe + 0x34)[0]
    assert base == IMAGE_BASE
    nsec = struct.unpack_from("<H", d, pe + 6)[0]
    optsz = struct.unpack_from("<H", d, pe + 20)[0]
    o = pe + 24 + optsz
    for i in range(nsec):
        p = o + 40 * i
        nm = d[p:p + 8].rstrip(b"\0").decode()
        vs, va, rs, ra = struct.unpack_from("<IIII", d, p + 8)
        secs.append((nm, va, vs, ra, rs))
    return d


def rva2off(rva):
    for nm, va, vs, ra, rs in secs:
        if va <= rva < va + max(vs, rs):
            return ra + (rva - va)
    return None


def off2rva(off):
    for nm, va, vs, ra, rs in secs:
        if ra <= off < ra + rs:
            return va + (off - ra)
    return None


def find_strings(d):
    out = {}
    for s in STRINGS:
        i = d.find(s.encode())
        if i < 0:
            print(f"  !! string not found: {s[:40]}")
            continue
        rva = off2rva(i)
        out[s] = (i, rva, IMAGE_BASE + rva)
        print(f"  {s[:50]!r:54s} fileoff={i:#x} rva={rva:#x} va={IMAGE_BASE+rva:#x}")
    return out


def xrefs_to(d, va):
    """Find push imm32 / mov reg, imm32 instructions whose immediate == va."""
    hits = []
    pat = struct.pack("<I", va)
    for m in re.finditer(re.escape(pat), d):
        off = m.start()
        rva = off2rva(off)
        if rva is None or not (0x1000 <= rva < 0x2E7000):
            continue
        # opcode byte(s) immediately before the immediate
        prev = d[off - 1]
        if prev in (0x68,):                      # push imm32
            hits.append((off, "push"))
        elif prev == 0x50 + 0 and d[off - 5] == 0xB8:   # eax
            hits.append((off - 5, "mov eax"))
        elif d[off - 5] in (0xB8, 0xB9, 0xBA, 0xBB, 0xBE, 0xBF):
            hits.append((off - 5, "mov r"))
        elif d[off - 6] == 0xC7 and d[off - 5] in (0x05, 0xC0, 0xC1):
            hits.append((off - 6, "mov m"))
    return hits


def func_start(d, rva, back=0x2000):
    """Walk backwards over int3 padding then take the byte after it."""
    start = max(0x1000, rva - back)
    i = rva
    # step back to the previous int3 run
    runs = []
    j = rva - 1
    while j > start:
        if d[j] == 0xCC:
            k = j
            while k > start and d[k] == 0xCC:
                k -= 1
            runs.append(k + 1)
            j = k - 1
            if len(runs) >= 1:
                break
        else:
            j -= 1
    return runs[0] if runs else start


def main():
    d = load()
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    print("=== strings ===")
    strs = find_strings(d)
    print("\n=== xrefs ===")
    for s, (off, rva, va) in strs.items():
        print(f"\n--- {s[:60]!r} va={va:#x}")
        hits = sorted(set(xrefs_to(d, va)))
        if not hits:
            print("    (no code xref)")
        for hoff, kind in hits:
            hrva = off2rva(hoff)
            print(f"    xref fileoff={hoff:#x} rva={hrva:#x} ({kind})")
        # dump each enclosing function
        for hoff, kind in hits[:3]:
            hrva = off2rva(hoff)
            fs = func_start(d, hrva)
            print(f"    enclosing function starts near rva {fs:#x} "
                  f"(va {IMAGE_BASE+fs:#x})")


if __name__ == "__main__":
    main()
