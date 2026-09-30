"""
Locate the container that owns a map-archive gap blob and dump its header.

For most maps the first gap sits at 0x208 and is itself the scene directory.
maps/coastline is different: its 11 MB gap starts at 0x20282, so something
already claimed the first 128 KB - i.e. the vertex stream is nested inside a
tagged resource, and that resource's own header should describe it.

Usage: python tools/gap_owner.py maps/coastline gap00_00020282.bin
"""
import struct
import sys
from pathlib import Path

RPK = Path(r"C:\Games\LASR")
SAFE = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_")


def printable(b):
    return all(0x20 <= c < 0x7F for c in b)


def entry_at(d, off):
    if off + 8 > len(d):
        return None
    tag = d[off:off + 4]
    if not printable(tag) or tag.count(b" ") > 1:
        return None
    size, = struct.unpack_from("<I", d, off + 4)
    if not 0 < size <= len(d) - off - 8:
        return None
    return tag.decode(), size


def walk_entries(d, resync=True):
    """Walk `<tag><size>` entries; optionally resync after an unparseable gap."""
    out = []
    off = 0x208
    while off + 8 <= len(d):
        e = entry_at(d, off)
        if e:
            out.append((off, e[0], e[1]))
            off += 8 + e[1]
            continue
        if not resync:
            break
        nxt = None
        for step in range(4, 4096):
            if off + step + 8 > len(d):
                break
            if entry_at(d, off + step):
                nxt = off + step
                break
        if nxt is None:
            break
        out.append((off, "--gap--", nxt - off))
        off = nxt
    return out


def main():
    folder, gapname = sys.argv[1], sys.argv[2]
    rpk = RPK / f"{folder}.rpk"
    if not rpk.exists():
        rpk = RPK / "maps" / f"{folder}.rpk"
    d = rpk.read_bytes()
    gap = Path("extracted_rpak") / "maps" / folder / gapname
    goff = int(gapname.split("_")[1].split(".")[0], 16)
    gsize = gap.stat().st_size
    print(f"{rpk}  {len(d):,} B")
    print(f"gap {gapname}  at 0x{goff:x}  {gsize:,} B\n")

    ents = walk_entries(d)
    print(f"{len(ents)} top-level segments:")
    for o, t, s in ents[:40]:
        mark = ""
        if t != "--gap--" and o <= goff < o + 8 + s:
            mark = "   <== OWNS THE GAP"
        print(f"   0x{o:08x}  {t:<10} {s:>12,}{mark}")

    holder = [(o, t, s) for o, t, s in ents
              if t != "--gap--" and o < goff < o + 8 + s]
    if holder:
        o, t, s = holder[0]
        print(f"\n=== container {t} at 0x{o:x}, size {s:,}, "
              f"gap is at +{goff-o:,} inside it ===")
        blk = d[o:o + 256]
        for i in range(0, 256, 16):
            print(f"  +{i:04x}  {blk[i:i+16].hex(' ')}  "
                  f"|{''.join(chr(c) if 32 <= c < 127 else '.' for c in blk[i:i+16])}|")
        print("\n  as u32 :", struct.unpack_from("<16I", d, o))
        print("  as f32 :", [round(v, 4) for v in struct.unpack_from("<16f", d, o + 4)])
        print(f"\n  bytes just before the gap "
              f"(0x{goff-32:x}..0x{goff:x}):")
        print(f"    {d[goff-32:goff].hex(' ')}")
        print(f"    as u32: {struct.unpack_from('<8I', d, goff-32)}")
    else:
        print("\nno tagged container owns the gap (it sits in an unclaimed region)")


if __name__ == "__main__":
    main()
