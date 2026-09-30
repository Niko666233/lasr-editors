"""Recover the native property tables in LASR.exe.

The engine keeps `<const char* name><handler*>` 8-byte records in .data.  Each
handler is the setter for that property, so disassembling it yields the struct
offset and type of the member it writes - i.e. the layout of the native car
physics structure, straight from the code that owns it.

    python tools/native_props.py --dump                # all tables -> json
    python tools/native_props.py --table 0x742b50      # one table, human
    python tools/native_props.py --handlers <name>     # disasm a setter
"""
import argparse
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pe_scan import PE

ROOT = Path(__file__).resolve().parent.parent


def is_name_ptr(pe, va):
    off = pe.va2off(va)
    if off is None or not (0x6E7000 <= va < 0x742000):
        return False
    n = 0
    while pe.d[off + n:off + n + 1] not in (b"", b"\0"):
        c = pe.d[off + n]
        if not (0x20 <= c < 0x7F):
            return False
        n += 1
        if n > 64:
            return False
    return 2 <= n <= 63


def is_code_ptr(pe, va):
    off = pe.va2off(va)
    return off is not None and 0x401000 <= va < 0x6E7000


def table_at(pe, seed):
    """Grow a record table outwards from a known-good record address."""
    start = seed
    while is_name_ptr(pe, struct.unpack_from("<I", pe.d, pe.va2off(start - 8))[0]) \
            and is_code_ptr(pe, struct.unpack_from("<I", pe.d, pe.va2off(start - 4))[0]):
        start -= 8
    end = seed
    while True:
        off = pe.va2off(end)
        if off is None or off + 8 > len(pe.d):
            break
        nm, h = struct.unpack_from("<II", pe.d, off)
        if not (is_name_ptr(pe, nm) and is_code_ptr(pe, h)):
            break
        end += 8
    out = []
    off = pe.va2off(start)
    for k in range((end - start) // 8):
        nm, h = struct.unpack_from("<II", pe.d, off + 8 * k)
        out.append((start + 8 * k, pe.cstr(nm), nm, h))
    return out


def find_tables(pe):
    """Every maximal run of valid records in .data."""
    _, _, _, ra, rsize = [s for s in pe.sections if s[0] == ".data"][0]
    d = pe.d
    tables = []
    va = pe.image_base + 0x742000 - pe.image_base  # placeholder, replaced below
    va = next(s[1] for s in pe.sections if s[0] == ".data") + pe.image_base
    end = va + rsize
    runs = []
    k = ra
    cur_start = None
    cur_n = 0
    while k + 8 <= ra + rsize:
        nm, h = struct.unpack_from("<II", d, k)
        ok = is_name_ptr(pe, nm) and is_code_ptr(pe, h)
        if ok:
            if cur_start is None:
                cur_start = pe.off2va(k)
                cur_n = 0
            cur_n += 1
        else:
            if cur_start is not None and cur_n >= 2:
                runs.append(cur_start)
            cur_start = None
            cur_n = 0
        k += 8  # records are 8-byte aligned: <name*><handler*>
    if cur_start is not None and cur_n >= 2:
        runs.append(cur_start)
    # dedupe overlapping runs -> use table_at
    seen = set()
    for seed in runs:
        t = table_at(pe, seed)
        if len(t) < 3:
            continue
        key = t[0][0]
        if key in seen:
            continue
        seen.add(key)
        tables.append(t)
    return tables


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", action="store_true")
    ap.add_argument("--table")
    ap.add_argument("--handlers")
    a = ap.parse_args()
    pe = PE()

    if a.handlers:
        from capstone import Cs, CS_ARCH_X86, CS_MODE_32
        tables = find_tables(pe)
        for t in tables:
            for addr, name, nmva, hvain in t:
                if name == a.handlers:
                    print(f"=== {name} @ table 0x{addr:08x} handler 0x{hvain:08x}")
                    off = pe.va2off(hvain)
                    md = Cs(CS_ARCH_X86, CS_MODE_32)
                    for ins in md.disasm(pe.d[off:off + 200], hvain):
                        print(f"  0x{ins.address:08x}  {ins.mnemonic:<7} {ins.op_str}")
                        if ins.mnemonic == "ret":
                            break
        return 0

    if a.table:
        t = table_at(pe, int(a.table, 16))
        print(f"table @0x{t[0][0]:08x}: {len(t)} entries")
        for addr, name, nmva, hvain in t:
            print(f"   0x{addr:08x}  {name:<24} handler 0x{hva:08x}")
        return 0

    tables = find_tables(pe)
    print(f"{len(tables)} property tables")
    data = {}
    for i, t in enumerate(tables):
        print(f"  [{i}] @0x{t[0][0]:08x}  {len(t)} entries")
        data[f"table_{i}_{t[0][0]:08x}"] = [
            {"addr": f"0x{addr:08x}", "name": name,
             "name_va": f"0x{nmva:08x}", "handler": f"0x{hvain:08x}"}
            for addr, name, nmva, hvain in t]
    if a.dump:
        p = ROOT / "out_native_props.json"
        p.write_text(json.dumps(data, indent=1))
        print(f"\nwrote {p.name} ({p.stat().st_size:,} B)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
