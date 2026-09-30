"""Diff physics-ish config lines across styling part variants, using out_config_dump.csv."""
import csv, re, collections, sys
from pathlib import Path

HERE = Path(r"C:\Users\niko6\Desktop\Work\LASR_Reverse_Engineering")
CSV = HERE / "out_config_dump.csv"

PHYS = {"body", "wing", "flexible", "inertia", "damage", "intdamage", "flags", "mass",
        "drag", "center", "bounds", "power", "damping", "nocollision", "slottype",
        "deform", "linked", "joint", "slope"}

rows = collections.defaultdict(list)
with CSV.open(encoding="utf-8", newline="") as f:
    for r in csv.DictReader(f):
        rows[r["file"]].append((r["key"], r["raw"].replace("\r", "").strip()))

fam = collections.defaultdict(dict)
pat = re.compile(r"^(.*)_(stock|style_(?:I|II|III|IV|WB)|stage_(?:I|II|III|IV|WB)|track|custom)$")
for f, kv in rows.items():
    stem = Path(f).stem
    car = f.split("/")[1] if f.count("/") >= 2 else "?"
    body = f.split("/")[2] if f.count("/") >= 3 else "?"
    m = pat.match(stem)
    key = (car, body, m.group(1)) if m else (car, body, stem, "__single__")
    var = m.group(2) if m else "__single__"
    fam[key][var] = sorted(set(l for k, l in kv if k in PHYS))

ndiff = 0
for key, variants in sorted(fam.items()):
    base = variants.get("stock")
    if base is None:
        continue
    for v, lines in sorted(variants.items()):
        if v == "stock" or lines == base:
            continue
        ndiff += 1
        sb, sv = set(base), set(lines)
        print("DIFF %s  variant=%s" % ("/".join(key), v))
        for l in sorted(sv - sb):
            print("   + ", l)
        for l in sorted(sb - sv):
            print("   - ", l)
print("total differing (family,variant) pairs:", ndiff)

# also: which families carry a `body` mass factor that differs from the car model's?
print("\n--- per-family body mass factors (1st numeric col after rot) ---")
agg = collections.defaultdict(set)
for f, kv in rows.items():
    stem = Path(f).stem
    for k, raw in kv:
        if k != "body":
            continue
        g = raw.split("\t")
        vals = [x for x in g if x.strip()]
        # find 'sphere'/'box' index, mass factor is the token before it
        for i, tok in enumerate(vals):
            if tok.strip() in ("sphere", "box", "cyl", "cylinder"):
                agg[stem].add(vals[i - 1].strip())
                break
for stem in sorted(agg):
    if any(w in stem for w in ("Bumper", "Hood", "wing", "sideskirt", "Trunk", "Door",
                               "SteeringWheel", "Sticker", "Model_", "Spoiler")):
        print("%-46s %s" % (stem, sorted(agg[stem])))
