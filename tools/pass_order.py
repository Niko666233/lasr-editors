"""Recover the render pass order: dump a function's call sequence.

Anchors used:
  * `[0x781e00]` holds IDirect3D9*   (proven: it is written right after the
    `Direct3DCreate9` call at 0x502a85);
  * `[0x781e04]` / `[0x781e80]` are the engine's own render objects (~1660 / ~850
    references - far too many to be a leaf).

What this tool does: disassemble a function (linear sweep from its prologue, with a
resync when capstone desyncs) and print only the control transfers, so the order of
operations is readable. D3D9 vtable calls are annotated with the slot name.

    python tools/pass_order.py --find            # functions that draw / begin / clear
    python tools/pass_order.py --fn 0x505110     # call sequence of one function
    python tools/pass_order.py --deep 0x505110   # follow one level of direct calls
"""
import argparse
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from d3d9_device import load, text                      # noqa: E402
from d3d9_calls import SLOTS, REG                       # noqa: E402

try:
    from capstone import Cs, CS_ARCH_X86, CS_MODE_32
except ImportError:
    raise SystemExit("需要 capstone（用 .capenv 的 python）")


def disasm(va, max_bytes=0x4000):
    """Linear sweep from va; stops at a ret followed by padding or on desync."""
    d, base, secs, _ = load()
    tva, tb = text(secs, d)
    off = va - base - tva
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    end = min(len(tb), off + max_bytes)
    out = []
    pos = off
    while pos < end:
        got = list(md.disasm(tb[pos:pos + 16], base + tva + pos, count=1))
        if not got:
            pos += 1
            continue
        ins = got[0]
        out.append(ins)
        pos += ins.size
        if ins.mnemonic in ("ret", "retn", "jmp") and ins.op_str.startswith("0x") is False:
            break
    return out


def calls_of(va):
    """[(va, kind, target_or_slot_name)] for control transfers in one function."""
    res = []
    for ins in disasm(va):
        if ins.mnemonic not in ("call", "jmp", "jmp  "):
            continue
        op = ins.op_str
        if op.startswith("dword ptr [") and "+ 0x" in op:
            try:
                disp = int(op.split("+ 0x")[1].split("]")[0], 16)
            except ValueError:
                continue
            if disp % 4 == 0 and disp // 4 in SLOTS:
                res.append((ins.address, "D3D", SLOTS[disp // 4], disp))
            else:
                res.append((ins.address, "vcall", op, disp))
        elif op.startswith("0x"):
            res.append((ins.address, "call", op, None))
    return res


def find_candidates():
    """Functions containing a D3D draw / BeginScene / Clear / Present call."""
    from d3d9_calls import scan, device_groups, prologue_before
    hits = scan()
    pos = defaultdict(list)
    for va, slot, reg, kind in hits:
        if slot in (20, 44, 45, 46, 84, 85, 86, 87):
            pos[slot].append(va)
    d, base, secs, _ = load()
    tva, tb = text(secs, d)
    byfunc = defaultdict(set)
    for slot, vas in pos.items():
        for va in vas:
            f = prologue_before(tb, tva, base, va - base - tva)
            byfunc[f].add(SLOTS[slot])
    print(f"含 DRAW/BeginScene/Clear/Present 的函数 {len(byfunc)} 个:")
    for f, names in sorted(byfunc.items(), key=lambda kv: -len(kv[1])):
        print(f"  0x{f:06x}  {sorted(names)}")
    return byfunc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--find", action="store_true")
    ap.add_argument("--fn", type=lambda s: int(s, 0))
    ap.add_argument("--deep", type=lambda s: int(s, 0))
    a = ap.parse_args()
    if a.find:
        find_candidates()
        return 0
    for tag, fn in (("direct", a.fn), ("deep", a.deep)):
        if not fn:
            continue
        print(f"\n=== 0x{fn:06x} 的调用序列（{tag}）===")
        seq = calls_of(fn)
        for va, kind, name, disp in seq:
            mark = "◆" if kind == "D3D" else " "
            print(f" {mark} 0x{va:06x}  {kind:<6} {name}")
        if tag == "deep":
            tgts = [int(n, 16) for _, k, n, _ in seq if k == "call"]
            for t in tgts[:40]:
                sub = calls_of(t)
                d3d = [n for _, k, n, _ in sub if k == "D3D"]
                if d3d:
                    print(f"   └─ 0x{t:06x}: " + ", ".join(Counter(d3d).most_common(6)
                          and [f"{n}×{c}" for n, c in Counter(d3d).most_common(6)]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
