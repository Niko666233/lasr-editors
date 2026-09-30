"""
Recover the map object-instance records and join them to their `gametype`.

A record looks like

    58 00 00 00 | u8 nameLen | name[nameLen] 00 | f32 x 6

The `58 00 00 00` marker is specific enough to locate records reliably, and the
six floats are the object's position + rotation, so each record can be matched
to the `RSD` block holding the same transform.

Output: docs/gametype_map.csv  (gametype, name, count, sample positions)

Usage: python tools/gametype_map.py [--csv out.csv]
"""
import csv
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from rsd_extract import blocks as rsd_blocks, parse as rsd_parse

MAPS = Path(r"C:\Games\LASR\maps")
MARK = b"\x58\x00\x00\x00"


def records(buf):
    """Yield (offset_of_nameLen, name, floats)."""
    out = []
    p = 0
    while True:
        i = buf.find(MARK, p)
        if i < 0:
            break
        p = i + 1
        nl = i + 4
        if nl >= len(buf):
            continue
        n = buf[nl]
        if not 4 <= n <= 41:
            continue
        raw = buf[nl + 1:nl + 1 + n]
        # nameLen counts the trailing NUL, so the last byte must be 0
        if not raw or raw[-1] != 0:
            continue
        body = raw[:-1]
        if not all(0x20 <= c < 0x7F for c in body):
            continue
        name = body.decode("latin1")
        if len(name) < 3:
            continue
        fo = nl + 1 + n
        if fo + 24 > len(buf):
            continue
        f = struct.unpack_from("<6f", buf, fo)
        if any(v != v or abs(v) > 1e6 for v in f):
            continue
        out.append((nl, name, f))
    return out


def main():
    joins = defaultdict(Counter)      # gametype -> name counter
    named = []                        # (map, gametype, name, floats)
    pairs = Counter()
    for rpk in sorted(MAPS.glob("*.rpk")):
        buf = rpk.read_bytes()
        recs = records(buf)
        rsds = []
        for off, size, pay in rsd_blocks(buf):
            d = rsd_parse(pay)
            if "gametype" in d:
                rsds.append((off, d["gametype"], d.get("params")))
        if not recs or not rsds:
            continue
        # a record's floats should match some RSD params; join on the closest.
        # restrict candidates to RSDs near the record's offset - the stream is
        # positional, so the owning block is always within a few hundred bytes.
        import bisect
        offs = [r[0] for r in rsds]
        for nl, name, f in recs:
            rec_off = nl + 2 + len(name)
            lo = bisect.bisect_left(offs, rec_off - 4096)
            hi = bisect.bisect_left(offs, rec_off + 4096)
            best = None
            for k in range(lo, hi):
                off, g, p = rsds[k]
                if not p or len(p) < 6:
                    continue
                dist = sum((p[j] - f[j]) ** 2 for j in range(6))
                if best is None or dist < best[0]:
                    best = (dist, g, off, abs(off - rec_off))
            if best is None:
                continue
            pairs["joined"] += 1
            if best[0] < 1e3:
                pairs["close"] += 1
            joins[best[1]][name] += 1
            named.append([rpk.stem, best[1], name,
                          ",".join(f"{v:g}" for v in f), f"{best[0]:.3f}"])

    print(f"records joined: {pairs['joined']:,}  "
          f"(distance < 1000: {pairs['close']:,})")
    print(f"gametypes seen: {len(joins)}\n")

    rows = []
    for g, c in joins.items():
        tot = sum(c.values())
        rows.append((g, tot, c))
    # high-confidence first: a gametype whose records mostly share one name IS
    # that name; a gametype with hundreds of distinct names is a catch-all slot
    rows.sort(key=lambda r: (-(r[2].most_common(1)[0][1] / r[1]), -r[1]))

    print(f"{'gametype':<12} {'recs':>5} {'names':>6} {'purity':>7}  "
          f"-> best name")
    for g, tot, c in rows:
        nm, k = c.most_common(1)[0]
        pur = k / tot
        print(f"{g:<12} {tot:>5} {len(c):>6} {pur*100:>6.0f}%  {nm:<24} "
              f"{'' if pur >= 0.6 else '(catch-all: ' + ', '.join(n for n, _ in c.most_common(3)) + ')'}")

    if "--csv" in sys.argv:
        out = sys.argv[sys.argv.index("--csv") + 1]
        with open(out, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["gametype", "records", "distinct_names", "purity",
                        "best_name", "top_names"])
            for g, tot, c in rows:
                nm, k = c.most_common(1)[0]
                w.writerow([g, tot, len(c), f"{k/tot:.3f}", nm,
                            ", ".join(f"{n}({v})" for n, v in c.most_common(8))])
        print(f"\nwrote {out}")

    detail = Path("docs/gametype_names.csv")
    with open(detail, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["map", "gametype", "name", "pos_rot", "match_dist2"])
        w.writerows(named)
    print(f"wrote {detail} ({len(named):,} rows)")


if __name__ == "__main__":
    main()
