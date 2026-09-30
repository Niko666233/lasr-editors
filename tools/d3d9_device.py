"""Locate the D3D9 objects: import sites -> IDirect3D9* -> IDirect3DDevice9*.

The disp-based scan (tools/d3d9_calls.py) is too noisy on its own because MSVC
caches vtable entries in stack slots (`call [ebp-x]`). This tool instead anchors on
the imported entry points, which is exact:

1. parse the import directory, list d3d9's IAT slots;
2. find every site that touches those IAT slots (`call [IAT]`, `mov eax,[IAT]`, ...);
3. report the globals those results are written to, i.e. the
   `IDirect3D9*` / `IDirect3DDevice9*` holders - the real anchor for render analysis.

    python tools/d3d9_device.py --imports
    python tools/d3d9_device.py --sites
"""
import argparse
import struct
import sys
from collections import Counter
from pathlib import Path

EXE = Path(r"C:\Games\LASR\LASR.exe")


def load():
    d = EXE.read_bytes()
    e = struct.unpack_from("<I", d, 0x3C)[0]
    base = struct.unpack_from("<I", d, e + 24 + 28)[0]
    optsz = struct.unpack_from("<H", d, e + 20)[0]
    opt = e + 24
    imp_rva, imp_sz = struct.unpack_from("<II", d, opt + 104)
    nsec = struct.unpack_from("<H", d, e + 6)[0]
    secs = []
    for i in range(nsec):
        o = e + 24 + optsz + i * 40
        nm = d[o:o + 8].rstrip(b"\0").decode("latin1")
        vsz, va, rsz, ra = struct.unpack_from("<IIII", d, o + 8)
        secs.append((nm, va, vsz, ra, rsz))
    return d, base, secs, imp_rva


def rva2off(secs, r):
    for nm, va, vsz, ra, rsz in secs:
        if va <= r < va + max(vsz, rsz):
            return ra + (r - va)
    return None


def text(secs, d):
    for nm, va, vsz, ra, rsz in secs:
        if nm == ".text":
            return va, d[ra:ra + rsz]
    raise SystemExit("no .text")


def cstr(d, off):
    return d[off:d.index(b"\0", off)].decode("latin1")


def imports():
    d, base, secs, imp_rva = load()
    o = rva2off(secs, imp_rva)
    out = {}
    while True:
        oft, ts, fc, nm_rva, ft = struct.unpack_from("<IIIII", d, o)
        if nm_rva == 0:
            break
        dll = cstr(d, rva2off(secs, nm_rva))
        if "d3d" in dll.lower() or "dx" in dll.lower() or "fmod" in dll.lower():
            names = []
            t = rva2off(secs, oft or ft)
            k = 0
            while True:
                ent = struct.unpack_from("<I", d, t + k * 4)[0]
                if ent == 0:
                    break
                if not (ent & 0x80000000):
                    names.append((base + ft + k * 4, cstr(d, rva2off(secs, ent) + 2)))
                else:
                    names.append((base + ft + k * 4, f"ord#{ent & 0xffff}"))
                k += 1
            out[dll] = names
        o += 20
    return out, base, secs, d


def sites(iat_vas):
    """Find instructions referencing the given absolute VAs."""
    d, base, secs, _ = load()
    tva, tb = text(secs, d)
    res = []
    for iat in iat_vas:
        needle = struct.pack("<I", iat)
        pos = 0
        while True:
            p = tb.find(needle, pos)
            if p < 0:
                break
            pos = p + 1
            # byte before the operand tells us the instruction shape
            if p >= 2:
                op, m = tb[p - 2], tb[p - 1]
                if op == 0xFF and m == 0x15:
                    res.append((base + tva + p - 2, iat, "call [IAT]"))
                    continue
                if op == 0xA1:
                    res.append((base + tva + p - 1, iat, "mov eax,[IAT]"))
                    continue
                if op == 0x8B:
                    res.append((base + tva + p - 2, iat, f"mov r32,[IAT] ({m:02x})"))
                    continue
                if op == 0x89:
                    res.append((base + tva + p - 2, iat, f"mov [IAT],r32 ({m:02x})"))
                    continue
    return res


def find_thunks(iat_va):
    """`jmp dword ptr [IAT]` stubs; the real callers do `call <stub>`."""
    d, base, secs, _ = load()
    tva, tb = text(secs, d)
    needle = b"\xFF\x25" + struct.pack("<I", iat_va)
    res = []
    pos = 0
    while True:
        p = tb.find(needle, pos)
        if p < 0:
            break
        pos = p + 1
        res.append(base + tva + p)
    return res


def callers_of(target_va):
    """All `call rel32` (E8) sites that land exactly on target_va."""
    d, base, secs, _ = load()
    tva, tb = text(secs, d)
    res = []
    i = 0
    while i < len(tb) - 5:
        if tb[i] == 0xE8:
            rel = struct.unpack_from("<i", tb, i + 1)[0]
            site = base + tva + i
            if site + 5 + rel == target_va:
                res.append(site)
            i += 5
            continue
        i += 1
    return res


def disas(va, count=60):
    """Disassemble `count` instructions at VA (capstone, x86-32)."""
    try:
        from capstone import Cs, CS_ARCH_X86, CS_MODE_32
    except ImportError:
        print("capstone 未安装（用 .capenv 的 python）")
        return
    d, base, secs, _ = load()
    tva, tb = text(secs, d)
    off = va - base - tva
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    md.detail = False
    for ins in md.disasm(tb[off:off + count * 8], va):
        print(f"  0x{ins.address:08x}  {ins.bytes.hex():<20} {ins.mnemonic} {ins.op_str}")
        count -= 1
        if count <= 0:
            break


def refs_to(target_va, window=4):
    """Instructions referencing an absolute address (mov/call/jmp/push forms)."""
    d, base, secs, _ = load()
    tva, tb = text(secs, d)
    needle = struct.pack("<I", target_va)
    out = []
    pos = 0
    while True:
        p = tb.find(needle, pos)
        if p < 0:
            break
        pos = p + 1
        before = tb[max(0, p - 4):p]
        out.append((base + tva + p, before.hex()))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--imports", action="store_true")
    ap.add_argument("--sites", action="store_true")
    ap.add_argument("--fn", default="Direct3DCreate9")
    ap.add_argument("--dis", type=lambda s: int(s, 0))
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--refs", type=lambda s: int(s, 0))
    a = ap.parse_args()
    if a.dis:
        print(f"=== 反汇编 0x{a.dis:08x} ===")
        disas(a.dis, a.n)
        return 0
    if a.refs:
        r = refs_to(a.refs)
        print(f"=== 0x{a.refs:08x} 被引用 {len(r)} 处（显示指令前 4 字节）===")
        for va, b in r[:60]:
            print(f"  0x{va:08x}  ...{b}")
        return 0
    imp, base, secs, d = imports()
    if a.imports:
        for dll, names in imp.items():
            print(f"=== {dll} ({len(names)} 项) ===")
            for va, nm in names:
                print(f"   IAT 0x{va:08x}  {nm}")
    if a.sites:
        for dll, names in imp.items():
            for va, nm in names:
                if a.fn and a.fn.lower() not in nm.lower():
                    continue
                thunks = find_thunks(va)
                print(f"\n=== {nm}  IAT 0x{va:08x}  桩 {[hex(t) for t in thunks]} ===")
                total = 0
                for t in thunks:
                    cs = callers_of(t)
                    total += len(cs)
                    print(f"  --- 桩 0x{t:08x}: {len(cs)} 个调用点 ---")
                    for c in cs:
                        print(f"      0x{c:08x}")
                if total == 0:
                    print("  （无调用点）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
