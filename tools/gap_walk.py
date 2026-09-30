"""
Walk the name-bearing record table inside a map-archive "gap" blob.

Hypothesis (from the hexdump of maps/boulevard):
    u32 a ; u32 b ; u16 c ; u8 d ; f32 e ; u32 f ; u32 g   (23 bytes fixed)
    u8 nameLen ; char name[nameLen]        (nameLen includes the NUL)

The walker only keeps a record if the name is printable ASCII, NUL-terminated,
and nameLen agrees with the string's actual length.  A long unbroken run of
successful records is the proof; the reported break offset says where the
table ends and the next sub-block starts.
"""
import struct
import sys
from pathlib import Path

FIXED = 23


def name_ok(d, i):
    """Return the name at stream offset i (which points at the length byte)."""
    if i >= len(d):
        return None
    n = d[i]
    if not 2 <= n <= 64:
        return None
    s = d[i + 1:i + 1 + n]
    if len(s) != n or s[-1] != 0:
        return None
    body = s[:-1]
    if not body or any(not (0x20 <= b < 0x7F) for b in body):
        return None
    return body.decode()


def walk(d, start=0, fixed=FIXED):
    off = start
    recs = []
    while off + fixed + 1 <= len(d):
        nm = name_ok(d, off + fixed)
        if nm is None:
            break
        a, b, c, dd = struct.unpack_from("<IIHB", d, off)
        e, = struct.unpack_from("<f", d, off + 11)
        f, g = struct.unpack_from("<II", d, off + 15)
        recs.append((off, a, b, c, dd, e, f, g, nm))
        off += fixed + 1 + len(nm) + 1
    return recs, off


def autofit(d, max_fixed=32):
    """Find the (start, fixed) pair that carries the longest unbroken walk."""
    best = (0, 0, [], -1)
    for fixed in range(16, max_fixed + 1):
        for start in range(0, 6):
            recs, end = walk(d, start, fixed)
            if len(recs) > len(best[2]) and len(recs) > 3:
                best = (start, fixed, recs, end)
    return best


def main():
    p = Path(sys.argv[1])
    d = p.read_bytes()
    start, fixed, recs, end = autofit(d)
    print(f"{p.name}  {len(d):,} B")
    print(f"  AUTOFIT        : start={start}  fixed={fixed}")
    print(f"  records walked : {len(recs):,}")
    print(f"  sync lost at   : {end:#x} ({end:,} B)  "
          f"{'END OF BLOB' if end + FIXED + 1 > len(d) else 'next sub-block'}")
    if end < len(d):
        print(f"  bytes after    : {d[end:end+48].hex(' ')}")
        print(f"                   |{''.join(chr(x) if 32<=x<127 else '.' for x in d[end:end+48])}|")
    print(f"\n  first 8 records:")
    for r in recs[:8]:
        print(f"    {r[0]:>10,}  a={r[1]:<10} b={r[2]:<10} c={r[3]:<6} d={r[4]:<4} "
              f"e={r[5]:<8.3f} f={r[6]:<12} g={r[7]:<6} {r[8]!r}")

    # value statistics over the whole walk
    import collections
    print(f"\n  e (the f32) distinct: "
          f"{collections.Counter(round(r[5],4) for r in recs).most_common(6)}")
    print(f"  d distinct          : "
          f"{collections.Counter(r[4] for r in recs).most_common(6)}")
    print(f"  c distinct          : "
          f"{collections.Counter(r[3] for r in recs).most_common(6)}")
    print(f"  g distinct          : "
          f"{collections.Counter(r[7] for r in recs).most_common(6)}")
    print(f"  names (last 25)     : {[r[8] for r in recs[-25:]]}")


if __name__ == "__main__":
    main()
