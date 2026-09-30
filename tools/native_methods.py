"""Enumerate every native method registered with the JavaMachine.

Registration sites in LASR.exe look like:

    mov  ecx, [0x771154]          ; the VM
    push <fn>                     ; native function address (in .text)
    push <sig>                    ; Java signature string, e.g. (I[F)V
    push <name>                   ; method name
    push <class>                  ; dotted Java class name
    call 0x652910                 ; registerNative

So the binary carries its own complete native API listing: class, name,
signature and function address.  Scanning for relative calls to 0x652910 and
reading the four contiguous pushes before each gives the whole surface.

    python tools/native_methods.py --dump
    python tools/native_methods.py --class java.game.parts.Chassis
    python tools/native_methods.py --grep pacejka
"""
import argparse
import collections
import csv
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pe_scan import PE

ROOT = Path(__file__).resolve().parent.parent
REGISTER_NATIVE = 0x652910


def scan(pe):
    out = []
    d = pe.d
    for off, src, kind in pe.callers(REGISTER_NATIVE):
        if kind != "call":
            continue
        # The four arguments are contiguous `push imm32` (0x68) instructions
        # right before the call.  Read them as bytes rather than re-disassembling
        # from an arbitrary start, which is not instruction-aligned.
        coff = pe.va2off(src)
        p = coff - 5
        vals = []
        while p >= 0 and d[p] == 0x68 and len(vals) < 4:
            vals.append(struct.unpack_from("<I", d, p + 1)[0])
            p -= 5
        if len(vals) < 4:
            continue
        # Walking backwards from the call already yields class, name, sig, fn
        # (the last push is the first argument, cdecl order).
        cls, name, sig, fn = vals
        rec = {"site": f"0x{src:08x}"}
        for key, va in (("class", cls), ("name", name), ("sig", sig)):
            rec[key] = pe.cstr(va) if pe.va2off(va) else None
        rec["fn"] = f"0x{fn:08x}"
        out.append(rec)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", action="store_true")
    ap.add_argument("--class")
    ap.add_argument("--grep")
    a = ap.parse_args()
    pe = PE()
    recs = scan(pe)
    good = [r for r in recs if r.get("class") and r.get("name") and r.get("sig")]
    print(f"registration sites {len(recs)}   with resolvable strings {len(good)}")
    per = collections.Counter(r["class"] for r in good)
    print(f"distinct classes {len(per)}")

    if a.grep:
        q = a.grep.lower()
        for r in good:
            if q in (r["name"] or "").lower() or q in (r["class"] or "").lower():
                print(f"   {r['class']:<34} {r['name']:<28} {r['sig']:<28} {r['fn']}")
        return 0
    if a.__dict__.get("class"):
        want = a.__dict__["class"]
        for r in good:
            if r["class"] == want:
                print(f"   {r['name']:<30} {r['sig']:<30} {r['fn']}")
        return 0

    for c, n in per.most_common(30):
        print(f"   {c:<40} {n} 个 native 方法")
    if a.dump:
        jp = ROOT / "out_native_methods.json"
        jp.write_text(json.dumps(recs, indent=1))
        cp = ROOT / "out_native_methods.csv"
        with cp.open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=["class", "name", "sig", "fn", "site"])
            w.writeheader()
            for r in recs:
                w.writerow({k: r.get(k, "") for k in w.fieldnames})
        print(f"\nwrote {jp.name} ({jp.stat().st_size:,} B), {cp.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
