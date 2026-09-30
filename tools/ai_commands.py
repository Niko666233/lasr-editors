"""Extract the AI command table from LASR.exe's command dispatcher.

Java drives the AI entirely through text commands:

    bot.command("AI_level 1.4 1.0 -1 1.1");
    bot.command("AI_RaceSplineMore -1.0 1.0 maps/hills/Track_00_fast.spl2");

The native controller parses them in one long if/else chain of
`strcmp(cmd, "AI_xxx")` blocks, each block parsing its own arguments with
sscanf and writing selected fields of the controller object.  Disassembling that
chain with a proper instruction-aligned walk gives, per command:

  * the argument format string (arity and types),
  * float constants used as defaults,
  * the controller field offsets written ([ctrl + 0x33b8] etc),
  * the handler called.

    python tools/ai_commands.py --dump
    python tools/ai_commands.py --grep race
"""
import argparse
import json
import re
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pe_scan import PE
from native_fn import f32, look_like_float

ROOT = Path(__file__).resolve().parent.parent
STRCMP = 0x67C205
SSCANF = 0x5666C0
ARG_OFF = re.compile(r"\[(\w+) \+ (0x[0-9a-f]+)\]")


def load_ai_strings(pe):
    """Every .rdata string beginning with 'AI_' plus its VA."""
    out = {}
    d = pe.d
    i = 0
    while True:
        i = d.find(b"AI_", i)
        if i < 0:
            break
        va = pe.off2va(i)
        if va and pe.section_of(va) == ".rdata" and (i == 0 or d[i - 1] == 0):
            s = pe.cstr(va)
            if s and s.startswith("AI_"):
                out[va] = s
        i += 3
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", action="store_true")
    ap.add_argument("--grep")
    a = ap.parse_args()

    from capstone import Cs, CS_ARCH_X86, CS_MODE_32
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    pe = PE()
    strings = load_ai_strings(pe)
    print(f"AI_* 字符串 {len(strings)} 个")

    # A linear walk over .text desynchronises (x86 has no unambiguous linear
    # disassembly), so anchor on the exact `push <string>` addresses from the
    # xref scan instead - those are data-derived and always instruction-aligned.
    sites = []
    for va, name in strings.items():
        for hit in pe.xrefs(va):
            off, src, kind = hit[0], hit[1], hit[2]
            if kind == "abs" and pe.section_of(src) == ".text":
                sites.append((src, name, va))
    sites = sorted(set(sites))
    print(f"派发点（push 地址）{len(sites)}")
    if not sites:
        return 1

    out = []
    for k, (addr, name, sva) in enumerate(sites):
        nxt = sites[k + 1][0] if k + 1 < len(sites) else addr + 0x200
        off = pe.va2off(addr)
        block = pe.d[off:pe.va2off(nxt)]
        rec = {"cmd": name, "push_at": f"0x{addr:08x}", "fmts": [], "floats": [],
               "fields": [], "calls": []}
        for i in md.disasm(block, addr):
            for tok in re.findall(r"0x[0-9a-f]{5,8}", i.op_str):
                u = int(tok, 16)
                if look_like_float(u):
                    f = f32(u)
                    if 1e-7 < abs(f) < 1e7:
                        rec["floats"].append(round(f, 6))
            m = ARG_OFF.search(i.op_str)
            if m and m.group(1) in ("eax", "ebx", "ecx", "edx", "esi", "edi", "ebp"):
                o = int(m.group(2), 16)
                if 0x100 <= o <= 0x8000:
                    rec["fields"].append(hex(o))
            if i.mnemonic == "push" and i.op_str.startswith("0x"):
                v = int(i.op_str, 16)
                if pe.section_of(v) == ".rdata":
                    s = pe.cstr(v)
                    if s and "%" in s:
                        rec["fmts"].append(s)
            if i.mnemonic == "call":
                try:
                    t = int(i.op_str, 16)
                except ValueError:
                    continue
                if t == SSCANF:
                    # sscanf confirms the block parses arguments; keep the call
                    # list short by not recording the parser itself
                    continue
                rec["calls"].append(f"0x{t:08x}")
        del rec["calls"][8:]
        rec["fields"] = sorted(set(rec["fields"]), key=lambda x: int(x, 16))
        rec["floats"] = sorted(set(rec["floats"]))
        rec["fmts"] = sorted(set(rec["fmts"]))
        out.append(rec)

    for r in out:
        if a.grep and a.grep.lower() not in r["cmd"].lower():
            continue
        print(f"\n### {r['cmd']}  @{r['push_at']}")
        if r["fmts"]:
            print(f"    参数格式: {r['fmts']}")
        if r["floats"]:
            print(f"    浮点常量: {r['floats']}")
        if r["fields"]:
            print(f"    写入字段: {r['fields']}")
    if a.dump:
        p = ROOT / "out_ai_commands.json"
        p.write_text(json.dumps(out, indent=1))
        print(f"\nwrote {p.name} ({p.stat().st_size:,} B)  {len(out)} 条命令")
    return 0


if __name__ == "__main__":
    sys.exit(main())
