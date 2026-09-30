"""Full-key diff of configureType lines across styling part variants (all 45 keys)."""
import csv, re, collections
from pathlib import Path

HERE = Path(r"C:\Users\niko6\Desktop\Work\LASR_Reverse_Engineering")
rows = collections.defaultdict(list)
with (HERE / "out_config_dump.csv").open(encoding="utf-8", newline="") as f:
    for r in csv.DictReader(f):
        rows[r["file"]].append((r["key"], r["raw"].replace("\r", "").strip()))

pat = re.compile(r"^(.*)_(stock|style_(?:I|II|III|IV|WB)|stage_(?:I|II|III|IV|WB)|track|custom)$")
fam = collections.defaultdict(dict)
for f, kv in rows.items():
    p = f.split("/")
    car, body = (p[1], p[2]) if len(p) > 2 else ("?", "?")
    stem = Path(f).stem
    m = pat.match(stem)
    key = (car, body, m.group(1) if m else stem, "" if m else "single")
    var = m.group(2) if m else "single"
    fam[key][var] = sorted(set(l for k, l in kv))

STYLE = ("F_Bumper", "R_Bumper", "Hood", "R_wing", "sideskirt", "Trunk", "Door",
         "SteeringWheel", "Sticker", "Interior", "Lightbar", "Wing")
print("=== styling families: keys that differ from _stock ===")
for key, variants in sorted(fam.items()):
    if key[3] == "single" or not any(w in key[2] for w in STYLE):
        continue
    base = variants.get("stock", [])
    for v, lines in sorted(variants.items()):
        if v == "stock":
            continue
        sb, sv = set(base), set(lines)
        if sb == sv:
            continue
        print("%-52s %-9s +%s -%s" % ("/".join(key[:3]), v,
                                      sorted(sv - sb), sorted(sb - sv)))
