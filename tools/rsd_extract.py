"""
Extract the plain-text `RSD` blocks from the coastline map stream.

A block is
    b"RSD\\x00" ; u32 size ; size bytes of ASCII
and the payload reads

    gametype 0x00030050\\r\\nparams -37.749,75.271,-294.362,0.363,0.000,0.000\\r\\n

i.e. a race-event type id plus a position and rotation.  These are the game's
route/event definitions sitting inside an otherwise opaque geometry blob.

Usage: python tools/rsd_extract.py [--blob coastline|all]
"""
import struct
import sys
from collections import Counter
from pathlib import Path

RPK = Path(r"C:\Games\LASR\maps")
MAGIC = b"RSD\x00"


def blocks(buf, lo=0, hi=None):
    hi = len(buf) if hi is None else hi
    out = []
    p = lo
    while True:
        i = buf.find(MAGIC, p, hi)
        if i < 0:
            break
        p = i + 1
        if i + 8 > hi:
            continue
        size, = struct.unpack_from("<I", buf, i + 4)
        if not 0 < size <= 4096 or i + 8 + size > hi:
            continue
        pay = buf[i + 8:i + 8 + size]
        if any(c > 0x7E and c != 0x0A for c in pay) or b"\r\n" not in pay:
            continue
        out.append((i, size, pay))
    return out


def parse(pay):
    lines = [l for l in pay.split(b"\r\n") if l]
    d = {}
    for l in lines:
        t = l.decode("latin1")
        if t.startswith("gametype"):
            d["gametype"] = t.split(None, 1)[1]
        elif t.startswith("params"):
            raw = t.split(None, 1)[1]
            try:
                d["params"] = [float(x) for x in raw.split(",")]
            except ValueError:
                d["params_raw"] = raw
        else:
            d.setdefault("other", []).append(t)
    return d


def main():
    maps = sorted(RPK.glob("*.rpk"))
    if "--blob" in sys.argv and sys.argv[sys.argv.index("--blob") + 1] == "coastline":
        maps = [RPK / "coastline.rpk"]

    csvrows = []
    grand = Counter()
    total = 0
    for rpk in maps:
        buf = rpk.read_bytes()
        bl = blocks(buf)
        if not bl:
            continue
        seen = Counter()
        rows = []
        for off, size, pay in bl:
            d = parse(pay)
            if "gametype" not in d:
                continue
            seen[d["gametype"]] += 1
            rows.append((off, d))
            p = d.get("params") or []
            csvrows.append([rpk.stem, f"0x{off:07x}", d["gametype"]]
                           + ([f"{v:g}" for v in p] + [""] * 6)[:6]
                           + [d.get("params_raw", "")])
        if not rows:
            continue
        total += len(rows)
        grand.update(seen)
        print(f"\n{rpk.name}: {len(rows)} gametype blocks")
        for g, c in seen.most_common(12):
            ex = next(r for r in rows if r[1]["gametype"] == g)
            p = ex[1].get("params", [])
            print(f"   {g:<12} x{c:<4} e.g. @0x{ex[0]:07x}  "
                  f"params {','.join(f'{v:g}' for v in p)}")

    print(f"\n=== total {total} gametype blocks across {len(maps)} archives ===")
    for g, c in grand.most_common(40):
        print(f"   {g:<12} {c:>6}")

    if "--csv" in sys.argv:
        import csv
        out = sys.argv[sys.argv.index("--csv") + 1]
        with open(out, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["map", "offset", "gametype",
                        "px", "py", "pz", "rx", "ry", "rz", "params_raw"])
            w.writerows(csvrows)
        print(f"\nwrote {out} ({len(csvrows)} rows)")


if __name__ == "__main__":
    main()
