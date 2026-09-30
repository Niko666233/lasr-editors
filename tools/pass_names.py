"""Name the render passes: map D3D9 render calls onto native method entry points.

Function boundaries are the hard part of x86 analysis (no table in a 32-bit MSVC
image), but this binary hands us 1523 of them for free: every VM native method is
registered as `push fn / push sig / push name / push class / call registerNative`,
so `out_native_methods.csv` holds real function entry addresses.

For each D3D9 render call (BeginScene / EndScene / Clear / Draw* / Present /
SetRenderTarget / SetDepthStencilSurface) we take the nearest native entry below it
and report the distance, so a call that is NOT inside a native is visible instead of
being silently mis-attributed.

    python tools/pass_names.py            # table of passes + their natives
    python tools/pass_names.py --frame    # who calls Present, and what it calls
"""
import argparse
import csv
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from d3d9_device import load, text                      # noqa: E402
from d3d9_calls import scan, prologue_before, SLOTS, DRAW  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
FRAME_SLOTS = {20: "Present", 44: "BeginScene", 45: "EndScene", 46: "Clear",
               40: "SetRenderTarget", 42: "SetDepthStencilSurface"}
ALL = set(FRAME_SLOTS) | DRAW


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


def containing(rows, va):
    lo, hi = 0, len(rows) - 1
    best = None
    while lo <= hi:
        mid = (lo + hi) // 2
        if rows[mid][0] <= va:
            best = rows[mid]
            lo = mid + 1
        else:
            hi = mid - 1
    if best is None:
        return None
    return best, va - best[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frame", action="store_true")
    a = ap.parse_args()
    rows = natives()
    print(f"原生方法入口 {len(rows)} 个")
    hits = [(va, slot) for va, slot, reg, kind in scan() if slot in ALL]
    print(f"D3D 渲染类调用 {len(hits)} 处\n")
    bynative = defaultdict(list)
    outside = []
    for va, slot in hits:
        c = containing(rows, va)
        if c and c[1] < 0x8000:                     # within 32 KB of a native entry
            bynative[c[0]].append((va, slot, c[1]))
        else:
            outside.append((va, slot))
    print(f"落在原生方法内的 {len(bynative)} 个原生方法；落在方法外的 {len(outside)} 处")
    print("\n=== 渲染相关原生方法（按地址）===")
    for (fva, cls, name), lst in sorted(bynative.items()):
        kinds = Counter(SLOTS[s] for _, s, _ in lst)
        draw = sum(v for k, v in kinds.items() if k in ("DrawIndexedPrimitive",
                   "DrawPrimitive", "DrawPrimitiveUP", "DrawIndexedPrimitiveUP"))
        print(f"  0x{fva:06x} {cls}.{name}  [Δmax {max(d for _,_,d in lst)}]")
        print(f"       {dict(kinds.most_common(6))}   DRAW={draw}")
    if a.frame:
        print("\n=== 调用 Present 的原生方法（帧函数候选）===")
        for (fva, cls, name), lst in sorted(bynative.items()):
            if any(s == 20 for _, s, _ in lst):
                print(f"  0x{fva:06x} {cls}.{name}")
        print("\n（下一步：反汇编候选帧函数，取其 call 目标序列）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
