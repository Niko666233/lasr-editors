"""
INVO mesh probe + OBJ export.

Header model derived from cross-comparison of 6 standalone .scx files:

    0x00  "INVO"
    0x04  u32 version = 4
    0x08  u32 N                     number of (u32, u32) descriptor pairs
    0x0C  N x ( u32 offset , u32 kind )

`offset` is relative to the start of the file; `kind` is small (0,1,3,4,5).
The region each descriptor covers runs to the next descriptor's offset.

This tool classifies every region by what its contents look like (float3
positions, float3 normals, float2 UVs, u16 index lists, RGBA material colours)
and can emit an OBJ from the best guess.

Usage:
  python tools/invo_probe.py FILE [FILE...]
  python tools/invo_probe.py FILE --obj OUT.obj
"""
import struct
import sys
from pathlib import Path

KIND_NAMES = {0: "zero", 1: "one", 3: "three", 4: "four", 5: "five"}


def header(d):
    if d[:4] != b"INVO":
        return None
    ver, n = struct.unpack_from("<2I", d, 4)
    pairs = []
    for i in range(n):
        k, o = struct.unpack_from("<2I", d, 0x0C + 8 * i)
        pairs.append((k, o))
    return ver, n, pairs


def classify(d, lo, hi):
    n = hi - lo
    out = []
    if n < 4:
        return ["empty"]
    # float32 triples / pairs
    for comp, name in ((3, "float3"), (2, "float2")):
        if n % (4 * comp) == 0:
            vals = struct.unpack_from("<%df" % (n // 4), d, lo)
            if all(abs(v) < 1e6 for v in vals):
                triples = [vals[i:i + comp] for i in range(0, len(vals), comp)]
                mx = max(abs(v) for v in vals)
                avg = sum(abs(v) for v in vals) / len(vals)
                out.append(f"{name} x{len(triples)} max|v|={mx:.3f} "
                           f"avg|v|={avg:.3f}")
    # u16 lists
    if n % 2 == 0:
        vals = struct.unpack_from("<%dH" % (n // 2), d, lo)
        out.append(f"u16 x{len(vals)} max={max(vals)}")
    if n % 4 == 0:
        vals = struct.unpack_from("<%dI" % (n // 4), d, lo)
        out.append(f"u32 x{len(vals)} max={max(vals)}")
    out.append(f"raw {d[lo:lo+16].hex(' ')}")
    return out


def main():
    path = Path(sys.argv[1])
    d = path.read_bytes()
    h = header(d)
    print(f"=== {path.name}  {len(d):,} B")
    if not h:
        print("   not INVO")
        return
    ver, n, pairs = h
    print(f"   version={ver}  N={n}  header_end={0x0C + 8 * n:#x}")
    print(f"   invariant offset[0] == header_end: "
          f"{pairs[0][1] == 0x0C + 8 * n} ({pairs[0][1]:#x})")
    offsets = sorted({o for _, o in pairs if 0 < o < len(d)} | {len(d)})
    for i, (kind, off) in enumerate(pairs):
        nxt = next((b for b in offsets if b > off), len(d))
        print(f"   [{i:2d}] kind={kind} off={off:#x}..{nxt:#x} ({nxt-off:,} B)")
        for line in classify(d, off, min(nxt, len(d))):
            print(f"         {line}")
    # tail fields after the descriptor table
    p = 0x0C + 8 * n
    tail = struct.unpack_from("<6I", d, p)
    print(f"   post-table u32s @ {p:#x}: {[f'{v}({v:#x})' for v in tail]}")
    print(f"   tail bytes: {d[p:p+0x20].hex(' ')}")


if __name__ == "__main__":
    main()
