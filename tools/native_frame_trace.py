#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""原生 getter 的栈缓冲追踪器 —— 解开「先填栈缓冲、再逐槽搬进 float[]」的返回值布局。

用途（`docs/55 §6` 未决 #1 起）：
    原生函数常见形态是
        lea edx, [esp + B]; push edx; push <arg>; call <填充器>   ← 先把物理量写进栈缓冲
        push 0x13 | 0 | <类>; call <分配器>                       ← 分配 N 元素 float[]
        再对每个槽： mov reg, [esp + X]; push reg; push <槽号>; push <数组>; call 0x6438f0
    由于 push 会不断移动 esp，**读到的 [esp+X] 偏移会随调用累积漂移**，肉眼无法直接对位。
    本工具跟踪「未清理的 push 字节数 D」，把每个值换算成**相对帧基址的固定偏移**，
    于是槽号 ↔ 缓冲偏移的对应关系一次列出（同一偏移重复出现 = 同一物理量被复用）。

用法：
    python tools/native_frame_trace.py --fn 0x486f20:0x487150 [--helper 0x6438f0] [--immediate 0x649170]
"""
import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dis_va import EXE, IB, sections, va2off                      # noqa: E402
from capstone import Cs, CS_ARCH_X86, CS_MODE_32                   # noqa: E402


def load():
    d = Path(EXE).read_bytes()
    return d, sections(d)


def trace(fn_lo, fn_hi, helper, immediates=()):
    d, secs = load()
    off = va2off(secs, fn_lo)
    raw = d[off:off + (fn_hi - fn_lo)]
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    ins = list(md.disasm(raw, fn_lo))

    D = 0                 # 尚未清理的 push 字节数
    frame_base = None     # `lea reg,[esp+X]` 的 X（缓冲基址，相对帧）
    pending = None        # 最近一次「从 [esp+X] 取值」的帧内偏移
    events = []           # (kind, data, va)
    alloc = None
    for x in ins:
        m, o = x.mnemonic, x.op_str
        if m == "push":
            D += 4
            continue
        if m == "pop":
            D -= 4
            continue
        if m == "sub" and o.startswith("esp, "):
            D += int(o.split(", ")[1], 0)
            continue
        if m == "add" and o.startswith("esp, "):
            D -= int(o.split(", ")[1], 0)
            continue
        if m == "lea" and "[esp" in o:
            mm = re.search(r"\[esp \+ (0x[0-9a-f]+|\d+)\]", o)
            if mm and frame_base is None:
                frame_base = int(mm.group(1), 0) - D
            continue
        if m in ("mov", "movss", "movsd", "movaps", "movups") and "[esp" in o:
            # ★ 只认「以 [esp] 为源」的读；写栈局部量（目的地是 [esp+X]）不算取值，
            #   否则会把 `movss [esp+0x48], xmm0` 这类局部量写入误判成槽值来源。
            tail = o.split(",", 1)[1] if "," in o else ""
            if "[esp" not in tail:
                continue
            mm = re.search(r"\[esp \+ (0x[0-9a-f]+|\d+)\]", tail)
            if mm:
                pending = (int(mm.group(1), 0) - D, x.address, o)
            continue
        if m in ("mulss", "addss", "subss", "divss") and "[esp" in o:
            mm = re.search(r"\[esp \+ (0x[0-9a-f]+|\d+)\]", o)
            if mm:
                pending = ("计算", int(mm.group(1), 0) - D, x.address, o)
            continue
        if m == "call":
            if o == hex(helper):
                events.append(("slot", pending, x.address))
                pending = None
            elif o in [hex(v) for v in immediates]:
                events.append(("call", (frame_base, o), x.address))
            continue
    return ins, frame_base, events


def main(argv=None):
    ap = argparse.ArgumentParser(description="原生 getter 的栈缓冲槽追踪")
    ap.add_argument("--fn", required=True, help="起始:结束（VA，十六进制）")
    ap.add_argument("--helper", default="0x6438f0", help="逐槽写入 helper（array_set）")
    ap.add_argument("--immediate", action="append", default=[], help="顺带标记的调用地址（如分配器）")
    a = ap.parse_args(argv)

    lo_s, _, hi_s = a.fn.partition(":")
    ins, base, events = trace(int(lo_s, 0), int(hi_s, 0), int(a.helper, 0),
                              [int(v, 0) for v in a.immediate])
    print("指令 %d 条；缓冲基址 = 帧 + %s" % (len(ins), ("0x%x" % base) if base is not None else "?"))
    print("helper = %s（逐槽写入）\n" % a.helper)
    slots, notes = [], []
    for kind, data, va in events:
        if kind == "call":
            notes.append("  0x%x call %s（帧基址=%s）" % (va, data[1], data[0]))
            continue
        if data is None:
            slots.append((None, "?", va))
        elif data[0] == "计算":
            slots.append(("计算", "偏移 %+d 参与乘加" % (data[1] - base) if base is not None else data[3], va))
        else:
            off = data[0]
            slots.append((off, ("帧+0x%x" % off) if off >= 0 else ("帧%d" % off), va))
    for i, (off, desc, va) in enumerate(slots):
        print("  槽 %2d ← %-16s (0x%x)" % (i, desc, va))
    # 相对最低读偏移的浮点下标（绝对标定不影响相对布局 ⇒ 这是可信的部分）
    ints = [off for off, _, _ in slots if isinstance(off, int)]
    if ints:
        lo = min(ints)
        print("\n相对缓冲起点的浮点下标（lo = 0x%x）:" % lo)
        for i, (off, desc, va) in enumerate(slots):
            if isinstance(off, int):
                print("  槽 %2d ← buf[%d]   （字节 %+d）" % (i, (off - lo) // 4, off - lo))
            else:
                print("  槽 %2d ← %s" % (i, desc))
    if notes:
        print("\n其他调用：")
        print("\n".join(notes))
    # 汇总：偏移 → 槽号
    seen = {}
    for i, (off, desc, va) in enumerate(slots):
        if isinstance(off, int):
            seen.setdefault(("帧+0x%x" % off) if off >= 0 else ("帧%d" % off), []).append(i)
    print("\n偏移复用（同一物理量多处出现）：")
    for k, v in sorted(seen.items(), key=lambda kv: -len(kv[1])):
        print("  %-10s → 槽 %s%s" % (k, v, "  ★ 重复" if len(v) > 1 else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
