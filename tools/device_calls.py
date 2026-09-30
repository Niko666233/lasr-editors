"""Device-call recovery by data flow (not by blind disp scanning).

The blind `FF 5X disp` scan is useless here: MSVC loads the device global into a
register, pulls the vtable pointer out of it, and calls through that, so the
`call [reg+disp]` sites carry no information about the object at all. The previous
attempt "found" `Present` inside `WheelRef.setForce` - pure noise.

Method: track the short data flow explicitly.
    mov ecx, [DEVICE]      <- exact load of the device global
    mov eax, [ecx]         <- vtable pointer
    call [eax + disp]      <- slot = disp/4
Registers are tracked through a few instructions; `DEVICE` itself is verified
independently (see tools/d3d9_device.py: `[0x781e00]` is written right after the
Direct3DCreate9 call, and `[0x781e04]` is the adjacent slot).

    python tools/device_calls.py --hist        # slot histogram through the device
    python tools/device_calls.py --sites       # per-slot call sites
    python tools/device_calls.py --byfunction  # group the calls by native method
"""
import argparse
import csv
import struct
import sys
from bisect import bisect_right
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from d3d9_device import load, text                       # noqa: E402
from d3d9_calls import SLOTS                             # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DEVICE = 0x781e04                      # verified: adjacent to the IDirect3D9* global
REGS = ["eax", "ecx", "edx", "ebx", "esp", "ebp", "esi", "edi"]

try:
    from capstone import Cs, CS_ARCH_X86, CS_MODE_32
except ImportError:
    raise SystemExit("需要 capstone")


def device_loads():
    """All `mov r32, [DEVICE]` sites: `8B <modrm> disp32` with mod=00, rm=101."""
    d, base, secs, _ = load()
    tva, tb = text(secs, d)
    needle = struct.pack("<I", DEVICE)
    out = []
    pos = 0
    while True:
        p = tb.find(needle, pos)
        if p < 0:
            break
        pos = p + 1
        if p < 2 or tb[p - 2] != 0x8B:
            continue
        modrm = tb[p - 1]
        if (modrm >> 6) == 0 and (modrm & 7) == 5:          # [disp32]
            out.append((base + tva + p - 2, (modrm >> 3) & 7))
    return out


def walk(va, dst, steps=8):
    """From a device load, follow the vtable-pointer load and the call."""
    d, base, secs, _ = load()
    tva, tb = text(secs, d)
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    off = va - base - tva
    alias = {REGS[dst]: "DEV"}
    n = 0
    for ins in md.disasm(tb[off:off + 64], va):
        n += 1
        if n > steps:
            return None
        op = ins.op_str
        if ins.mnemonic == "mov" and "[" in op and "]" in op:
            left, right = op.split(",", 1)
            left = left.strip()
            if "[" not in right:                     # store form `mov [mem], reg`
                continue
            inner = right[right.index("[") + 1:right.index("]")].strip()
            src = inner.split("+")[0].strip()
            if src in alias:
                alias[left] = "VT" if alias[src] == "DEV" else alias[src]
                continue
        if ins.mnemonic == "call" and "dword ptr [" in op:
            inner = op[op.index("[") + 1:op.index("]")]
            reg = inner.split("+")[0].strip()
            if reg in alias and alias[reg] in ("VT", "DEV"):
                disp = 0
                if "+" in inner:
                    try:
                        disp = int(inner.split("+")[1].strip(), 16)
                    except ValueError:
                        return None
                if disp % 4 == 0 and disp // 4 in SLOTS:
                    return (SLOTS[disp // 4], disp // 4)
                return (f"slot{disp // 4}", disp // 4)
        if ins.mnemonic in ("ret", "jmp", "jmp  "):
            return None
    return None


def natives():
    rows = []
    with open(ROOT / "out_native_methods.csv", newline="", encoding="latin1") as f:
        for r in csv.DictReader(f):
            try:
                rows.append((int(r["fn"], 16), r["class"], r["name"]))
            except (ValueError, KeyError):
                continue
    rows.sort()
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hist", action="store_true")
    ap.add_argument("--sites", action="store_true")
    ap.add_argument("--byfunction", action="store_true")
    a = ap.parse_args()
    loads = device_loads()
    print(f"设备全局 0x{DEVICE:06x} 的精确加载点 {len(loads)} 处")
    calls = []
    for va, dst in loads:
        r = walk(va, dst)
        if r:
            calls.append((va, r[0], r[1]))
    print(f"其中 {len(calls)} 处立即通过 vtable 调用（其余是加载后做别的事）")
    if a.hist or not (a.sites or a.byfunction):
        c = Counter(n for _, n, _ in calls)
        print("\n=== 通过设备的调用（按 slot 名）===")
        for n, k in c.most_common(40):
            print(f"   {k:>5}x  {n}")
    if a.sites:
        print("\n=== 逐点 ===")
        for va, n, slot in calls:
            print(f"   0x{va:06x}  {n}")
    if a.byfunction:
        rows = natives()
        vas = [r[0] for r in rows]
        g = defaultdict(list)
        for va, n, slot in calls:
            i = bisect_right(vas, va) - 1
            if i >= 0 and va - vas[i] < 0x4000:
                g[rows[i]].append((va, n))
            else:
                g[(0, "?", "engine-internal")].append((va, n))
        print(f"\n=== 按原生方法分组（{len(g)} 组）===")
        for (fva, cls, name), lst in sorted(g.items(), key=lambda kv: -len(kv[1])):
            c = Counter(n for _, n in lst)
            print(f"  0x{fva:06x} {cls}.{name}  {len(lst)} 次: {dict(c.most_common(6))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
