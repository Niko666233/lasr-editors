"""PE helpers for LASR.exe work: sections, string scan, xref search.

    python tools/pe_scan.py sections
    python tools/pe_scan.py strings <keyword> [keyword...]
    python tools/pe_scan.py xrefs <hex-va|0x...> [--limit N]
    python tools/pe_scan.py disasm <hex-va> [count]
"""
import argparse
import re
import struct
import sys
from pathlib import Path

EXE = Path("C:/Games/LASR/LASR.exe")


class PE:
    def __init__(self, path=EXE):
        self.d = Path(path).read_bytes()
        self.e_lfanew = struct.unpack_from("<I", self.d, 0x3C)[0]
        pe = self.e_lfanew
        assert self.d[pe:pe + 4] == b"PE\0\0"
        opt = struct.unpack_from("<H", self.d, pe + 0x14)[0]
        self.n_sections = struct.unpack_from("<H", self.d, pe + 6)[0]
        self.image_base = struct.unpack_from("<I", self.d, pe + 0x34)[0]
        self.size_of_image = struct.unpack_from("<I", self.d, pe + 0x50)[0]
        self.entry = struct.unpack_from("<I", self.d, pe + 0x28)[0]
        self.sections = []
        o = pe + 0x18 + opt
        for i in range(self.n_sections):
            s = o + 40 * i
            name = self.d[s:s + 8].rstrip(b"\0").decode("latin1")
            vsize, va, rsize, ra = struct.unpack_from("<4I", self.d, s + 8)
            self.sections.append((name, va, vsize, ra, rsize))

    def off2va(self, off):
        for name, va, vsize, ra, rsize in self.sections:
            if ra <= off < ra + rsize:
                return self.image_base + va + (off - ra)
        return None

    def va2off(self, va):
        rva = va - self.image_base
        for name, sva, vsize, ra, rsize in self.sections:
            span = max(vsize, rsize)
            if sva <= rva < sva + span:
                return ra + (rva - sva)
        return None

    def section_of(self, va):
        """Section name containing this VA ('.text', '.rdata', '.data', ...)."""
        rva = va - self.image_base
        for name, sva, vsize, ra, rsize in self.sections:
            if sva <= rva < sva + max(vsize, rsize):
                return name
        return None

    def cstr(self, va):
        off = self.va2off(va)
        if off is None:
            return None
        end = self.d.find(b"\0", off)
        return self.d[off:end].decode("latin1", "replace")

    def xrefs(self, va):
        """Find references to this VA. MSVC emits `push imm32` for the absolute
        form; relative calls (`E8 disp32`) need a separate scan, otherwise every
        call site is invisible."""
        out = []
        for pat, tag in ((struct.pack("<I", va), "abs"),
                         (struct.pack("<I", va - self.image_base), "rva")):
            i = self.d.find(pat)
            while i != -1:
                out.append((i, tag))
                i = self.d.find(pat, i + 1)
        keep = []
        for off, tag in out:
            v = self.off2va(off)
            if v is None:
                continue
            for name, sva, vsize, ra, rsize in self.sections:
                if ra <= off < ra + rsize:
                    keep.append((off, v, tag, name))
                    break
        return keep

    def callers(self, va):
        """Scan .text for relative `call` (E8) / `jmp` (E9) instructions whose
        target is `va`. Linear-scan based: a byte 0xE8 inside another
        instruction's operand can show up as a false positive, so treat hits as
        candidates and confirm by disassembling around them."""
        _, tva, tvsize, tra, trsize = self.sections[0]
        hits = []
        blob = self.d[tra:tra + trsize]
        for opcode, kind in ((0xE8, "call"), (0xE9, "jmp")):
            i = blob.find(bytes([opcode]))
            while i != -1:
                if i + 5 <= len(blob):
                    disp = struct.unpack_from("<i", blob, i + 1)[0]
                    src = self.image_base + tva + i
                    if src + 5 + disp == va:
                        hits.append((tra + i, src, kind))
                i = blob.find(bytes([opcode]), i + 1)
        return sorted(hits)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["sections", "strings", "xrefs", "disasm", "cstr", "callers"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("--limit", type=int, default=40)
    a = ap.parse_args()
    pe = PE()

    if a.cmd == "sections":
        print(f"ImageBase 0x{pe.image_base:x}  SizeOfImage 0x{pe.size_of_image:x}  "
              f"entry 0x{pe.image_base + pe.entry:x}  sections {pe.n_sections}")
        for name, va, vsize, ra, rsize in pe.sections:
            print(f"   {name:<8} VA=0x{pe.image_base + va:08x} VSize=0x{vsize:07x} "
                  f"RAW=0x{ra:08x} RSize=0x{rsize:07x}")

    elif a.cmd == "strings":
        keys = a.args
        rx = re.compile(rb"[ -~]{4,160}")
        seen = 0
        for m in rx.finditer(pe.d):
            t = m.group().decode("latin1")
            if any(k.lower() in t.lower() for k in keys):
                va = pe.off2va(m.start())
                if va is None:
                    continue
                print(f"0x{m.start():06x} VA 0x{va:08x} {t[:110]!r}")
                seen += 1
                if seen >= a.limit * 20:
                    return
        print(f"({seen} hits)")

    elif a.cmd == "callers":
        for s in a.args:
            va = int(s, 16)
            hits = pe.callers(va)
            print(f"=== relative callers of 0x{va:08x}: {len(hits)}")
            for off, src, kind in hits[:a.limit]:
                print(f"   {kind} at 0x{src:08x} (file 0x{off:06x})")

    elif a.cmd == "cstr":
        for s in a.args:
            va = int(s, 16)
            print(f"0x{va:08x} -> {pe.cstr(va)!r}")

    elif a.cmd == "xrefs":
        for s in a.args:
            va = int(s, 16)
            hits = pe.xrefs(va)
            print(f"=== xrefs to 0x{va:08x} ({pe.cstr(va)!r}): {len(hits)}")
            for off, v, tag, name in hits[:a.limit]:
                print(f"   file 0x{off:06x} VA 0x{v:08x} [{tag}] in {name}")

    elif a.cmd == "disasm":
        from capstone import Cs, CS_ARCH_X86, CS_MODE_32
        va = int(a.args[0], 16)
        n = int(a.args[1]) if len(a.args) > 1 else 40
        off = pe.va2off(va)
        md = Cs(CS_ARCH_X86, CS_MODE_32)
        for ins in md.disasm(pe.d[off:off + n * 8], va):
            print(f"0x{ins.address:08x}  {ins.mnemonic:<7} {ins.op_str}")
            n -= 1
            if n <= 0:
                break


if __name__ == "__main__":
    sys.exit(main())
