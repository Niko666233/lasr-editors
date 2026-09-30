"""Recover field offsets for every native property by disassembling its handler.

The engine's config pipeline (LASR.exe):

    Java  configureType("maxsteer\\t0.750 2.406 10.0")
      -> 0x4afc70  split into lines
      -> 0x4afb30  cut at ; # / then tokenise on " \\r\\n\\t" ([0x743210])
      -> linear scan of the <name*, handler*> table in .data
      -> handler(this, value_string)
      -> handler  sscanf(value, fmt, &field, &field, ...)   (0x5666c0)

So each handler's `push <dst>` arguments before the sscanf call are the struct
offsets of that property's fields, and the pushed format string states their
count and type.  Both are recovered here mechanically.

    python tools/native_fields.py --dump            # json + csv
    python tools/native_fields.py --prop maxsteer   # one property
    python tools/native_fields.py --audit           # only entries that failed
"""
import argparse
import csv
import json
import re
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pe_scan import PE
import native_props as NP

ROOT = Path(__file__).resolve().parent.parent
SScanf = 0x5666C0          # the game's sscanf wrapper
ARG_RE = re.compile(r"\[(\w+) \+ (0x[0-9a-f]+)\]")


def handler_fields(pe, hvain, md):
    """Walk a handler; return (fmt, [offsets], notes)."""
    off = pe.va2off(hvain)
    ins = list(md.disasm(pe.d[off:off + 400], hvain))
    fmt = None
    dsts = []
    notes = []
    pending = []          # pushed operands, in push order
    for k, i in enumerate(ins):
        if i.mnemonic == "call" and i.op_str == hex(SScanf):
            # the argument pushes for this call are everything after the
            # previous call/ret (lea/add set the destination registers in
            # between, so the pushes are not contiguous)
            j = k - 1
            run = []
            while j >= 0 and ins[j].mnemonic not in ("call", "ret", "int3"):
                if ins[j].mnemonic == "push":
                    run.append(ins[j].op_str)
                j -= 1
            run.reverse()
            if len(run) >= 2:
                src = run[-1]
                fmtop = run[-2]
                if fmtop.startswith("0x"):
                    fmt = pe.cstr(int(fmtop, 16))
                # the count of conversion specifiers in the format IS the
                # number of destinations; take exactly that many pushes.
                n = len(re.findall(r"%(?!%)", fmt or ""))
                if n and n <= len(run) - 2:
                    dsts = run[-2 - n:-2]
                    notes.append(f"fmt wants {n}, run has {len(run) - 2}")
                else:
                    dsts = []
                    notes.append(f"fmt wants {n}, run has {len(run) - 2} (short)")
        elif i.mnemonic == "ret":
            break
    # After the parse, stack temporaries are copied into the real fields:
    # `movss [reg+off], xmm` / `mov [reg+off], eax` with a non-stack base.
    # Collect those; they are the struct writes for handlers that parse via
    # the stack (array properties like wheel/arm/hub do exactly this).
    post = []
    seen_call = False
    for i in ins:
        if i.mnemonic == "call" and i.op_str == hex(SScanf):
            seen_call = True
            continue
        if not seen_call:
            continue
        m = ARG_RE.search(i.op_str.split(",")[0]) if "," in i.op_str else None
        if m and m.group(1) not in ("esp", "ebp"):
            if i.mnemonic in ("movss", "mov", "movsd", "movd"):
                post.append(f"{m.group(1)}+{m.group(2)}")
    # resolve dst operands: direct [reg+off] or a register set by lea
    offsets = []
    leas = {}
    for i in ins:
        if i.mnemonic == "lea":
            m = ARG_RE.match(i.op_str.split(",")[1].strip())
            if m:
                leas[i.op_str.split(",")[0].strip()] = int(m.group(2), 16)
        if i.mnemonic == "add" and i.op_str.count(",") == 1:
            parts = [p.strip() for p in i.op_str.split(",")]
            m = re.match(r"^(0x[0-9a-f]+)$", parts[1])
            if m:
                leas[parts[0]] = int(m.group(1), 16)
    for op in dsts:
        m = ARG_RE.search(op)
        if m:
            offsets.append((m.group(1), int(m.group(2), 16), op))
        elif op.strip() in leas:
            offsets.append(("?", leas[op.strip()], op))
        else:
            offsets.append(("?", None, op))
    return fmt, offsets, notes, post


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", action="store_true")
    ap.add_argument("--prop")
    ap.add_argument("--audit", action="store_true")
    a = ap.parse_args()
    from capstone import Cs, CS_ARCH_X86, CS_MODE_32
    pe = PE()
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    md.detail = False

    tables = NP.find_tables(pe)
    out = []
    for ti, t in enumerate(tables):
        for addr, name, nmva, hvain in t:
            fmt, offsets, notes, post = handler_fields(pe, hvain, md)
            out.append({"table": ti, "name": name, "handler": f"0x{hvain:08x}",
                        "fmt": fmt,
                        "fields": [{"base": b, "off": (f"0x{o:03x}" if o is not None else None)}
                                   for b, o, _ in offsets],
                        "post_stores": post,
                        "raw_dsts": [op for _, _, op in offsets]})

    if a.prop:
        for r in out:
            if r["name"] == a.prop:
                print(json.dumps(r, indent=1))
        return 0

    ok = [r for r in out if r["fmt"]]
    nf = [r for r in out if not r["fmt"]]
    print(f"properties {len(out)}   with sscanf fmt {len(ok)}   no fmt {len(nf)}")
    print(f"\n{'prop':<20}{'fmt':<28}{'字段'}")
    for r in sorted(ok, key=lambda r: r["name"]):
        fl = ", ".join(f"{f['base']}+{f['off']}" for f in r["fields"]) or "-"
        print(f"{r['name']:<20}{(r['fmt'] or ''):<28}{fl}")
    if nf:
        print(f"\n-- no sscanf fmt ({len(nf)}), e.g.:")
        for r in nf[:14]:
            print(f"   {r['name']:<20}{r['raw_dsts'][:4]}")

    if a.dump:
        jp = ROOT / "out_native_fields.json"
        jp.write_text(json.dumps(out, indent=1))
        cp = ROOT / "out_native_fields.csv"
        with cp.open("w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["table", "name", "handler", "fmt", "nfields", "fields"])
            for r in out:
                w.writerow([r["table"], r["name"], r["handler"], r["fmt"] or "",
                            len(r["fields"]),
                            " ".join(f"{f['base']}+{f['off']}" for f in r["fields"])])
        print(f"\nwrote {jp.name} ({jp.stat().st_size:,} B), {cp.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
