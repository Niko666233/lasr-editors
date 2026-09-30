"""Extract every `configureType("key<TAB>values")` config line from the game's
TUFA classes, validated against the native property-name table.

Why this is trustworthy: the key set is not guessed.  It comes from the
`<name*,handler*>` tables found in LASR.exe .data (tools/native_props.py), and
each native handler's sscanf format string independently states the value
arity (e.g. maxsteer -> '%f %f %f').  So a line is accepted only if its key is
a real native property, and its arity can be cross-checked against the handler.

    python tools/config_dump.py --dump          # csv + json
    python tools/config_dump.py --key maxsteer  # show every car's value
    python tools/config_dump.py --keys          # key inventory with arities
"""
import argparse
import collections
import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXTRACTED = ROOT / "extracted"
PROPS = ROOT / "out_native_props.json"
TTAB = 0x09
PRINTABLE = re.compile(rb"[\t -~]{4,400}")


def native_keys():
    data = json.loads(PROPS.read_text())
    keys = {}
    for tbl, entries in data.items():
        for e in entries:
            keys.setdefault(e["name"], []).append((tbl, e["handler"]))
    return keys


def class_strings(path):
    d = path.read_bytes()
    for m in PRINTABLE.finditer(d):
        s = m.group().decode("latin1")
        if "\t" in s or (len(s) > 3 and s.split(" ")[0] in ("nocollision",)):
            yield s


def parse_line(s, keys):
    """Return (key, fields, raw) or None.  The key is whatever precedes the
    first TAB; a line with no TAB is a value-less flag (e.g. `wheelbones`)."""
    head = s.split("\t")[0].strip()
    if head not in keys:
        return None
    fields = [g.strip() for g in s.split("\t")[1:]]
    return head, fields, s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", action="store_true")
    ap.add_argument("--key")
    ap.add_argument("--keys", action="store_true")
    a = ap.parse_args()
    keys = native_keys()
    print(f"native property keys: {len(keys)}")

    rows = []
    for p in sorted(EXTRACTED.rglob("*.class")):
        rel = p.relative_to(EXTRACTED).as_posix()
        for s in class_strings(p):
            r = parse_line(s, keys)
            if not r:
                continue
            key, fields, raw = r
            rows.append({"file": rel, "key": key, "raw": raw,
                         "groups": len(fields),
                         "nums": " ".join(fields).split()})
    print(f"config lines: {len(rows)}  across {len({r['file'] for r in rows})} classes")

    per_key = collections.defaultdict(list)
    for r in rows:
        per_key[r["key"]].append(r)

    if a.key:
        v = per_key.get(a.key, [])
        print(f"\n=== {a.key}: {len(v)} 条")
        for r in v:
            print(f"   {r['file'].split('/')[-1][:40]:<42} {r['raw'][:90]!r}")
        return 0

    print(f"\n{'key':<20}{'条数':>5}{'类数':>5}  值组数分布            样例")
    for k, v in sorted(per_key.items(), key=lambda kv: -len(kv[1])):
        gs = collections.Counter(r["groups"] for r in v)
        cls = len({r["file"] for r in v})
        gs_s = " ".join(f"{g}组×{n}" for g, n in sorted(gs.items()))
        print(f"{k:<20}{len(v):>5}{cls:>5}  {gs_s:<22} {v[0]['raw'][:52]!r}")

    if a.dump:
        cp = ROOT / "out_config_dump.csv"
        with cp.open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=["file", "key", "raw", "groups", "nums"])
            w.writeheader()
            for r in rows:
                w.writerow(r)
        jp = ROOT / "out_config_dump.json"
        jp.write_text(json.dumps(
            {k: [{"file": r["file"], "raw": r["raw"]} for r in v]
             for k, v in per_key.items()}, indent=1))
        print(f"\nwrote {cp.name} ({cp.stat().st_size:,} B), "
              f"{jp.name} ({jp.stat().st_size:,} B)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
