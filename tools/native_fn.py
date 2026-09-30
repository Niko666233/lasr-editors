"""Disassemble a native function in LASR.exe in a form you can actually read maths from.

MSVC x86 float code is unreadable raw: constants arrive as `mov dword ptr
[esp+4], 0x3F800000` (a float bit pattern) or `movss xmm0, [0x6e7668]`, and calls
go to anonymous addresses.  This annotates all three:

  * immediates that look like IEEE-754 floats are decoded in a comment;
  * `movss`/`movsd`/`fld` referencing .rdata print the float stored there;
  * `call <va>` prints the registered native method name from
    out_native_methods.json, so the call graph reads like an API listing.

    python tools/native_fn.py --fn 0x483f50            # disassemble
    python tools/native_fn.py --floats 0x483f50        # only the float constants
    python tools/native_fn.py --struct 0x483f50        # field offsets touched
"""
import argparse
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pe_scan import PE

ROOT = Path(__file__).resolve().parent.parent


def f32(u):
    return struct.unpack("<f", struct.pack("<I", u & 0xFFFFFFFF))[0]


def look_like_float(u):
    f = f32(u)
    if f != f or f in (float("inf"), float("-inf")):
        return False
    if u in (0, 0xFFFFFFFF, 0x7FFFFFFF, 0x80000000):
        return False
    return abs(f) > 1e-6 and abs(f) < 1e7


def load_natives():
    p = ROOT / "out_native_methods.json"
    if not p.exists():
        return {}
    out = {}
    for r in json.loads(p.read_text()):
        try:
            out[int(r["fn"], 16)] = f"{r['class']}.{r['name']}{r['sig']}"
        except (KeyError, TypeError, ValueError):
            pass
    return out


def render(pe, md, va, n, natives, show_floats=True, show_struct=True):
    off = pe.va2off(va)
    if off is None:
        print(f"0x{va:08x} not mapped")
        return 0
    ins = list(md.disasm(pe.d[off:off + n * 8], va))
    floats = []
    structs = []
    for i in ins[:n]:
        line = f"0x{i.address:08x}  {i.mnemonic:<7} {i.op_str}"
        note = []
        # float immediate (push/mov with an imm32 operand)
        for tok in i.op_str.replace(",", " ").split():
            if tok.startswith("0x") and len(tok) >= 5:
                try:
                    u = int(tok, 16)
                except ValueError:
                    continue
                if 0x400000 <= u < 0x520000 and pe.va2off(u) is not None and pe.section_of(u) == ".rdata":
                    s = pe.cstr(u)
                    if s and s.isprintable() and len(s) > 1:
                        note.append(f"str {s!r}")
                elif look_like_float(u) and show_floats:
                    note.append(f"float {f32(u):.6g}")
                    floats.append((i.address, f32(u)))
        # memory operand referencing .rdata
        for tok in i.op_str.replace(",", " ").split():
            tok2 = tok.strip("[]")
            if tok2.startswith("0x") and len(tok2) >= 8:
                try:
                    u = int(tok2, 16)
                except ValueError:
                    continue
                if pe.va2off(u) is not None:
                    raw = pe.d[pe.va2off(u):pe.va2off(u) + 4]
                    if len(raw) == 4:
                        v = struct.unpack("<f", raw)[0]
                        if abs(v) > 1e-9 and abs(v) < 1e7:
                            note.append(f"[{raw.hex()}] = {v:.6g}")
        if i.mnemonic == "call":
            try:
                t = int(i.op_str, 16)
            except ValueError:
                t = None
            if t in natives:
                note.append(f"-> {natives[t]}")
        # struct field offsets: [reg + 0xNN] with small displacement
        if show_struct:
            for tok in i.op_str.replace(",", " ").split():
                if tok.startswith("+"):
                    try:
                        d = int(tok[1:], 16)
                    except ValueError:
                        continue
                    if 0x10 <= d <= 0x8000:
                        structs.append((i.address, d))
                        note.append(f"off +0x{d:x}")
                    break
        if note:
            line += "   ; " + " | ".join(dict.fromkeys(note))
        print(line)
    if floats:
        print(f"\n-- float immediates: {sorted(set(round(f,6) for _, f in floats))}")
    if structs:
        offs = sorted({d for _, d in structs})
        print(f"-- field offsets touched: {[hex(d) for d in offs]}")
    return len(ins)


def walk(pe, md, va, limit=2000):
    """Linear walk of one function until ret / int3 padding."""
    off = pe.va2off(va)
    if off is None:
        return [], []
    floats, fields, calls, ins = [], [], [], []
    for i in md.disasm(pe.d[off:off + limit * 8], va):
        ins.append(i)
        if i.mnemonic == "ret":
            break
        if len(ins) > limit:
            break
    for i in ins:
        for tok in i.op_str.replace(",", " ").replace("[", " [").split():
            t = tok.strip("[]")
            if t.startswith("0x"):
                try:
                    u = int(t, 16)
                except ValueError:
                    continue
                if look_like_float(u):
                    floats.append(f32(u))
                if pe.va2off(u) is None:
                    continue
                if tok.startswith("["):
                    # a real memory read: decode the stored float
                    raw = pe.d[pe.va2off(u):pe.va2off(u) + 4]
                    if len(raw) == 4:
                        v = struct.unpack("<f", raw)[0]
                        if 1e-9 < abs(v) < 1e7:
                            floats.append(v)
                elif pe.section_of(u) == ".rdata":
                    # a bare .rdata address is a string / table reference
                    s = pe.cstr(u)
                    if s and s.isprintable() and len(s) > 1:
                        calls.append(f"str:{s}")
        if i.mnemonic == "call":
            try:
                calls.append(int(i.op_str, 16))
            except ValueError:
                pass
        if "+" in i.op_str:
            for tok in i.op_str.replace(",", " ").split():
                if tok.startswith("+"):
                    try:
                        d = int(tok[1:], 16)
                    except ValueError:
                        continue
                    if 0x10 <= d <= 0x20000:
                        fields.append(d)
    return ins, floats, fields, calls


def summary(pe, md, vas, natives):
    for va in vas:
        ins, floats, fields, calls = walk(pe, md, va)
        name = natives.get(va, "")
        named = [natives.get(c, "") for c in calls if c in natives]
        other = [f"0x{c:08x}" for c in calls if c not in natives and isinstance(c, int)]
        strs = [c[4:] for c in calls if isinstance(c, str)]
        fl = sorted({round(f, 7) for f in floats})
        print(f"\n### 0x{va:08x} {name}   [{len(ins)} ins]")
        if fl:
            print(f"    浮点常量: {fl}")
        if fields:
            print(f"    字段偏移: {sorted(hex(d) for d in set(fields))}")
        if named:
            print(f"    调用(native): {named}")
        if other:
            print(f"    调用(内部): {other}")
        if strs:
            print(f"    引用字符串: {strs}")


def resolve(reg, env):
    """Follow `mov reg, [parent + off]` chains to a symbolic field path."""
    path = ""
    seen = 0
    while reg in env and seen < 8:
        parent, off = env[reg]
        if parent == reg:          # self-referential (eax = [eax+0x64]) - stop
            break
        if off:
            path = f"+0x{off:x}" + path
        reg = parent
        seen += 1
    return f"[{reg}]{path}"


def writes(pe, md, vas, natives):
    """Report the memory stores each function performs, as symbolic field paths.

    Setters are thin: resolve the receiver, then `mov reg, [obj + 0xNNN]` a few
    times and store into the final struct.  Tracking `mov/lea reg, [parent+off]`
    turns `movss [ecx+0xf8], xmm0` into `[this]+0x24d4+0xf8`.
    """
    import re
    pat_off = re.compile(r"\[(\w+) \+ (0x[0-9a-f]+)\]")
    pat_reg = re.compile(r"\[(\w+)\]")
    for va in vas:
        ins, _, _, _ = walk(pe, md, va)
        if not ins:
            continue
        env = {}
        out = []
        for i in ins:
            ops = [o.strip() for o in i.op_str.split(",")] if i.op_str else []
            if i.mnemonic in ("mov", "movss", "movaps", "movd", "movq") and len(ops) == 2:
                dst, src = ops
                m = pat_off.search(src) or pat_reg.search(src)
                if m and dst in ("eax", "ebx", "ecx", "edx", "esi", "edi", "ebp"):
                    off = int(m.group(2), 16) if m.lastindex and m.lastindex > 1 else 0
                    env[dst] = (m.group(1), off)
                    continue
                m2 = pat_off.search(dst) or pat_reg.search(dst)
                if m2:
                    off = int(m2.group(2), 16) if m2.lastindex and m2.lastindex > 1 else 0
                    out.append((i.address, f"{resolve(m2.group(1), env)}+0x{off:x}", i.mnemonic, src))
            elif i.mnemonic == "lea" and len(ops) == 2:
                m = pat_off.search(ops[1])
                if m:
                    env[ops[0]] = (m.group(1), int(m.group(2), 16))
        if out:
            print(f"\n### 0x{va:08x} {natives.get(va, '')}")
            for addr, path, mn, val in out:
                print(f"    0x{addr:08x}  {path:<28} <- {val}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fn", nargs="+", default=[])
    ap.add_argument("--summary", nargs="+", default=[])
    ap.add_argument("--writes", nargs="+", default=[])
    ap.add_argument("--props", action="store_true",
                    help="run --writes over every handler in out_native_props.json")
    ap.add_argument("--floats", nargs="+", default=[])
    ap.add_argument("--struct", nargs="+", default=[])
    ap.add_argument("-n", type=int, default=60)
    a = ap.parse_args()
    from capstone import Cs, CS_ARCH_X86, CS_MODE_32
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    pe = PE()
    natives = load_natives()
    if a.summary:
        summary(pe, md, [int(s, 16) for s in a.summary], natives)
        return 0
    if a.props:
        proptab = json.loads((ROOT / "out_native_props.json").read_text())
        vas, seen, pmap = [], set(), {}
        for tname, entries in proptab.items():
            for e in entries:
                h = e.get("handler") if isinstance(e, dict) else None
                if h:
                    v = int(h, 16)
                    pmap.setdefault(v, f"{e.get('name', '?')} <{tname}>")
                    if v not in seen:
                        seen.add(v)
                        vas.append(v)
        print(f"唯一 handler 数: {len(vas)}")
        names = dict(pmap)
        names.update(natives)
        writes(pe, md, vas, names)
        return 0
    if a.writes:
        writes(pe, md, [int(s, 16) for s in a.writes], natives)
        return 0
    for va_s in a.fn:
        va = int(va_s, 16)
        print(f"\n===== 0x{va:08x} =====")
        render(pe, md, va, a.n, natives, True, True)
    for va_s in a.floats + a.struct:
        va = int(va_s, 16)
        print(f"\n===== 0x{va:08x} =====")
        render(pe, md, va, a.n, natives, va_s in a.floats, va_s in a.struct)
    return 0


if __name__ == "__main__":
    sys.exit(main())
