#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""原生函数的「帧内局部量访问图」——把 [esp±X] 全部换算成帧内固定偏移，列出每个槽的读写点。

为什么需要：函数里 push 会让 `[esp+X]` 漂移，同一个局部量在不同位置写成不同 X；
grep 文本找写入者会漏（本工具在 `docs/55 §6` 追 info block 的输入 vec3 时就是为此而生）。

用法：
    python tools/native_frame_locals.py 0x4544a0 0x4556b8                # 全图
    python tools/native_frame_locals.py 0x4544a0 0x4556b8 --read 0x454762  # 只看某个读点对应的槽
    python tools/native_frame_locals.py 0x4544a0 0x4556b8 --slot 0x88     # 只看某个帧内偏移
"""
import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dis_va import EXE, sections, va2off                          # noqa: E402
from capstone import Cs, CS_ARCH_X86, CS_MODE_32                   # noqa: E402

ESP = re.compile(r"\[esp \+ (0x[0-9a-f]+|\d+)\]")
ESPN = re.compile(r"\[esp - (0x[0-9a-f]+|\d+)\]")


def analyze(lo, hi):
    d = Path(EXE).read_bytes()
    secs = sections(d)
    off = va2off(secs, lo)
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    ins = list(md.disasm(d[off:off + (hi - lo)], lo))

    D = 0
    frame = None
    slots = {}
    for x in ins:
        m, o = x.mnemonic, x.op_str
        if m == "push":
            D += 4
            continue
        if m == "pop":
            D -= 4
            continue
        if m == "sub" and o.startswith("esp, "):
            n = int(o.split(", ")[1], 0)
            D += n
            if frame is None:
                frame = n
            continue
        if m == "add" and o.startswith("esp, "):
            D -= int(o.split(", ")[1], 0)
            continue
        mm = ESP.search(o) or ESPN.search(o)
        if mm is None or frame is None:
            continue
        val = int(mm.group(1), 0)
        if o.startswith("[esp - "):
            val = -val
        foff = val - D + frame                      # 以「prologue 后的 esp」为 0
        # 判定读写方向：[esp…] 出现在第一个逗号之后 = 源（读）；否则是目的地（写）
        tail = o.split(",", 1)[1] if "," in o else ""
        kind = "读" if "[esp" in tail else "写"
        if m in ("mulss", "addss", "subss", "divss", "comiss", "fadd", "fsub", "fmul", "fdiv"):
            kind = "读"
        slots.setdefault(foff, []).append((kind, x.address, "%s %s" % (m, o)))
    return ins, frame, slots


def main(argv=None):
    ap = argparse.ArgumentParser(description="原生函数的帧内局部量访问图")
    ap.add_argument("lo"); ap.add_argument("hi")
    ap.add_argument("--read", help="只看这个地址上的读点所对应的槽")
    ap.add_argument("--slot", help="只看这个帧内偏移（如 0x88）")
    ap.add_argument("--ctx", type=int, default=6, help="每个槽列出的上下文条数")
    a = ap.parse_args(argv)

    lo, hi = int(a.lo, 0), int(a.hi, 0)
    ins, frame, slots = analyze(lo, hi)
    if frame is None:
        print("未找到 prologue 的 sub esp,imm")
        return 1
    byva = {x.address: i for i, x in enumerate(ins)}
    print("%s..%s：%d 条指令，帧 %#x；帧内槽 %d 个\n" % (a.lo, a.hi, len(ins), frame, len(slots)))

    want = None
    if a.slot:
        want = int(a.slot, 0)
    elif a.read:
        rva = int(a.read, 0)
        for foff, evs in slots.items():
            if any(k == "读" and va == rva for k, va, _ in evs):
                want = foff
                break
        if want is None:
            print("未在该函数的 [esp] 访问里找到 %s" % a.read)
            return 1
        print("读点 %s ⇒ 帧内偏移 %+#x\n" % (a.read, want))

    for foff in sorted(slots):
        if want is not None and foff != want:
            continue
        evs = slots[foff]
        reads = [e for e in evs if e[0] == "读"]
        writes = [e for e in evs if e[0] == "写"]
        print("槽 %+#08x   读 %d / 写 %d" % (foff, len(reads), len(writes)))
        for kind, va, txt in evs:
            print("   %s 0x%x  %s" % (kind, va, txt))
            if kind == "写" and a.ctx:
                i = byva.get(va)
                if i is not None:
                    for j in range(max(0, i - a.ctx), i):
                        p = ins[j]
                        print("        │ %s %s" % (p.mnemonic, p.op_str))
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
