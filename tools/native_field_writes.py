#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""原生「填结构」函数的字段写入扫描器 —— 一次列出 `movss/mov [reg+off], src` 的全部写点。

用途（`docs/55 §6` 未决 #1）：
    原生把物理量算进一块结构/缓冲时，写点形如 `mov [esi+0x40], xmm0`。本工具按
    「输出寄存器 + 偏移」聚合所有写点，并给出每个写点的**上下文**（前若干条指令）
    与**浮点常量真值**（`.rdata` 里的 VA 直接解成 float），用于反推字段语义。
    配合 `tools/native_frame_trace.py`（槽 → 缓冲下标）即可把返回值逐槽对上物理量。

用法：
    python tools/native_field_writes.py 0x4544a0 0x4556a0 --reg esi
    python tools/native_field_writes.py 0x4544a0 0x4556a0 --reg esi --ctx 8
"""
import argparse
import re
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dis_va import EXE, sections, va2off                         # noqa: E402
from capstone import Cs, CS_ARCH_X86, CS_MODE_32                  # noqa: E402


def read_float_globals(d, secs, vas):
    out = {}
    for va in vas:
        off = va2off(secs, va)
        if off is None:
            continue
        out[va] = struct.unpack_from("<f", d, off)[0]
    return out


def slice_for(ins, i, dst, limit=14):
    """回看算出 dst 的那几条指令（遇到上一次 store 或 call 停），压缩成一个表达式串。"""
    out = []
    for j in range(i - 1, max(-1, i - limit) - 1, -1):
        pre = ins[j]
        o = pre.op_str
        if pre.mnemonic == "call" and not out:
            out.append("%s %s" % (pre.mnemonic, o))
            break
        d = o.split(",")[0].strip()
        if d == dst or d.startswith(dst):
            out.append("%s %s" % (pre.mnemonic, o))
        elif pre.mnemonic in ("mulss", "addss", "subss", "divss", "xorps") and out:
            out.append("%s %s" % (pre.mnemonic, o))
    return list(reversed(out))


def main(argv=None):
    ap = argparse.ArgumentParser(description="原生填结构函数的字段写入扫描")
    ap.add_argument("lo"); ap.add_argument("hi")
    ap.add_argument("--reg", default="esi", help="输出基址寄存器（默认 esi）")
    ap.add_argument("--ctx", type=int, default=6, help="每个写点回看的指令数")
    ap.add_argument("--slice", action="store_true", help="紧凑模式：每个字段只列算出它的那几条指令")
    ap.add_argument("--limit", type=int, default=18, help="紧凑模式回看上限")
    a = ap.parse_args(argv)

    d = Path(EXE).read_bytes()
    secs = sections(d)
    lo, hi = int(a.lo, 0), int(a.hi, 0)
    off = va2off(secs, lo)
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    ins = list(md.disasm(d[off:off + (hi - lo)], lo))

    store = re.compile(r"dword ptr \[%s \+ (0x[0-9a-f]+|\d+)\]" % a.reg)
    glob_re = re.compile(r"\[0x([0-9a-f]{6,8})\]")
    writes = []
    globs = set()
    for i, x in enumerate(ins):
        o = x.op_str
        m = store.search(o)
        # ★ x87（fstp/fst/fadd… [reg+off]）也会写字段 —— 只认 mov* 会漏掉整段浮点计算
        if m and (x.mnemonic.startswith("mov") or x.mnemonic.startswith("fst")
                  or x.mnemonic in ("faddp", "fsubp", "fmulp", "fdivp", "fadd", "fsub")):
            writes.append((int(m.group(1), 0), i, x))
        for g in glob_re.findall(o):
            globs.add(int(g, 16))
    fv = read_float_globals(d, secs, globs)

    print("%s..%s：%d 条指令；对 [%s+off] 的写入 %d 处\n" % (a.lo, a.hi, len(ins), a.reg, len(writes)))
    if a.slice:
        for off_b, i, x in writes:
            dst = x.op_str.split("], ")[-1].strip()
            parts = slice_for(ins, i, dst, a.limit)
            txt = "  |  ".join(parts).replace("dword ptr ", "").replace("xmmword ptr ", "")
            print("[%s+0x%02x] = %s   (0x%x)" % (a.reg, off_b, txt or dst, x.address))
        print()
        print("浮点常量真值（.rdata）：")
        for va, v in sorted(fv.items()):
            print("  0x%x = %.9g" % (va, v))
        return 0

    last = None
    for off_b, i, x in writes:
        if last is not None and off_b < last:
            pass
        last = off_b
        print("── %s[%+d] = %-28s  (0x%x)" % (a.reg, off_b, x.op_str.split("], ")[-1], x.address))
        for j in range(max(0, i - a.ctx), i):
            pre = ins[j]
            extra = ""
            for g in glob_re.findall(pre.op_str):
                gv = fv.get(int(g, 16))
                if gv is not None:
                    extra += "   ; f32(%s) = %.6g" % (g, gv)
            print("      %-8s %s%s" % (pre.mnemonic, pre.op_str, extra))
        print()
    print("浮点常量真值（.rdata）：")
    for va, v in sorted(fv.items()):
        print("  0x%x = %.9g" % (va, v))
    return 0


if __name__ == "__main__":
    sys.exit(main())
