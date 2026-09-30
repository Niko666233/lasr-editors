"""Compare physics-ish configureType keys across styling part families.

Groups classes by <Car>/<body>/<family>_<variant>, and reports which variant
differs from *_stock for each physics key (body/wing/flexible/inertia/damage/flags).
"""
import sys, re, json, collections
from pathlib import Path

HERE = Path(r"C:\Users\niko6\Desktop\Work\LASR_Reverse_Engineering")
sys.path.insert(0, str(HERE / "editors"))
from lasr_core import tufa
from lasr_core.tufa import Pool

# native property names (docs/17 table 1..4) that could carry numbers
PHYS_KEYS = {"body", "wing", "flexible", "inertia", "damage", "intdamage", "flags",
             "mass", "drag", "center", "slope", "bounds", "power", "damping",
             "collision", "nocollision", "slottype", "deform", "linked", "joint"}


def strings_of(path):
    data = Path(path).read_bytes()
    t = tufa.Tufa(data)
    return t, [t.pool.utf8(i) for i in range(len(t.pool.raw) if hasattr(t.pool, "raw") else 0)]


def raw_strings(path):
    """all pool utf8 entries"""
    data = Path(path).read_bytes()
    t = tufa.Tufa(data)
    out = []
    pool = t.pool
    for i in range(len(_entries(pool))):
        s = pool.utf8(i)
        if s:
            out.append(s)
    return t, out


def _entries(pool):
    # count entries by scanning CONS payload
    return [None] * 0


def cfg_lines(path):
    data = Path(path).read_bytes()
    t = tufa.Tufa(data)
    lines = []
    for i in range(4000):
        s = t.pool.utf8(i)
        if not s:
            continue
        head = s.split("\t")[0].split()[0] if s.strip() else ""
        if head in PHYS_KEYS:
            lines.append(s.replace("\r", "").strip())
    return sorted(set(lines))


if __name__ == "__main__":
    roots = sys.argv[1:] or [str(HERE / "editors/data/classes")]
    fam = collections.defaultdict(dict)   # (car,body,fam) -> {variant: lines}
    for root in roots:
        for p in sorted(Path(root).rglob("*.tufa")):
            car = p.parts[-3]
            body = p.parts[-2]
            name = p.stem
            m = re.match(r"^(.*)_(stock|style_I+|style_IV|style_III|style_II|style_WB|stage_II+|track|custom)$", name)
            if not m:
                fam[(car, body, name)]["__only__"] = cfg_lines(p)
                continue
            fam[(car, body, m.group(1))][m.group(2)] = cfg_lines(p)
    for key, variants in sorted(fam.items()):
        base = variants.get("stock")
        if base is None:
            continue
        diffs = []
        for v, lines in sorted(variants.items()):
            if v == "stock":
                continue
            if lines != base:
                diffs.append(v)
        if diffs:
            print("DIFF", "/".join(key), "variants differing:", diffs)
            for v in diffs:
                sb = set(base); sv = set(variants[v])
                print("   ", v, "extra:", sorted(sv - sb))
                print("   ", v, "missing:", sorted(sb - sv))
