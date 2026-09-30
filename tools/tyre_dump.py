"""Export every tyre compound's Pacejka tables from the lifted Java corpus.

Ground truth chain (all independently verified):

  LASR.exe  setPacejka(I[I[F)V @0x4834e0
      checks idxs.len == vars.len  ("inconsistent Pacejka array sizes!")
      for i: idx = idxs[i]; v = vars[i]
             if (idx == 0x12) v *= 1e-4          # slot 18 has a unit scale
             tyre->coef[tyreIdx*36 + idx] = v    # f32[36] at tyre+0x20c
  Java side
      PacejkaGlobals.pacVarIdxs = {2,12,0,4,13,11,14,3,17,10,1,6,7,8,18,19}
      ..._v2 = ... {...,15,16}      ..._v3 = ... {...,15,16,34,35}
      Tyre_XX.Ref_pacVars[surface] = {coefficients in pacVarIdxs order}
      surfaces: Asphalt Grass Gravel Hard_Sand Snow Ice

So a compound's row is a *dense* list whose position maps through pacVarIdxs onto
the 36-slot coefficient array.

    python tools/tyre_dump.py --dump
    python tools/tyre_dump.py --compound SH
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PSEUDO = ROOT / "out_pseudo"
SURFACES = ["Asphalt", "Grass", "Gravel", "Hard_Sand", "Snow", "Ice"]

VARIANT_SETS = {
    "v1": [2, 12, 0, 4, 13, 11, 14, 3, 17, 10, 1, 6, 7, 8, 18, 19],
    "v2": [2, 12, 0, 4, 13, 11, 14, 3, 17, 10, 1, 6, 7, 8, 18, 19, 15, 16],
    "v3": [2, 12, 0, 4, 13, 11, 14, 3, 17, 10, 1, 6, 7, 8, 18, 19, 15, 16, 34, 35],
}

NAME_RE = re.compile(r"^\s*(?:local\d+|[A-Za-z_][\w.]*)\s*=\s*\{([^}]*)\}\s*;")
SURF_RE = re.compile(r"Ref_pacVars\[.*CONTACT_(\w+)\]\s*=")
SPRING_RE = re.compile(r"my_(Profile|SpringR)List\s*=\s*\{([^}]*)\}")


def nums(text):
    """Parse a Java float-literal list, handling `((F)1234)` casts.

    The cast is written `((F)1234)`, so stripping only `(F)` leaves a stray `)`.
    """
    clean = text.replace("(F)", "").replace("(", "").replace(")", "")
    out = []
    for tok in clean.split(","):
        tok = tok.strip()
        if not tok:
            continue
        try:
            out.append(float(tok))
        except ValueError:
            return None
    return out


def parse_compound(path):
    lines = path.read_text(errors="ignore").splitlines()
    rows = {}
    cur = None
    springs = {}
    for ln in lines:
        m = NAME_RE.match(ln)
        if m:
            v = nums(m.group(1))
            if v:
                cur = v
        ms = SURF_RE.search(ln)
        if ms and cur:
            rows[ms.group(1)] = list(cur)
        msp = SPRING_RE.search(ln)
        if msp:
            v = nums(msp.group(2))
            if v:
                springs[msp.group(1)] = v
    return rows, springs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", action="store_true")
    ap.add_argument("--compound")
    a = ap.parse_args()
    files = sorted((PSEUDO / "java/classes/game/parts").glob("Tyre_*.java"))
    files.append(PSEUDO / "java/classes/game/parts/Rim.java")
    result = {}
    for f in files:
        rows, springs = parse_compound(f)
        if not rows:
            continue
        n = max(len(v) for v in rows.values())
        variant = next((k for k, s in VARIANT_SETS.items() if len(s) == n), f"??{n}")
        # map dense row -> 36-slot coefficient array
        slots = {}
        if variant in VARIANT_SETS:
            for surf, row in rows.items():
                arr = [None] * 36
                for pos, val in zip(VARIANT_SETS[variant], row):
                    arr[pos] = val
                slots[surf] = arr
        result[f.stem] = {"variant": variant, "ncoefficients": n,
                          "rows": rows, "slots": slots, "springs": springs}
    print(f"轮胎配方 {len(result)} 个")
    for name, d in sorted(result.items()):
        diffuse = {s: r[0] for s, r in d["rows"].items() if r}
        print(f"  {name:<12} {d['variant']:<4} {d['ncoefficients']} 系数   首系数(摩擦µ): "
              + " ".join(f"{s[:3]}={v}" for s, v in diffuse.items()))
    if a.compound:
        for name, d in result.items():
            if a.compound.lower() in name.lower():
                print(json.dumps(d, indent=1, ensure_ascii=False))
    if a.dump:
        p = ROOT / "out_tyres.json"
        p.write_text(json.dumps(result, indent=1))
        print(f"\nwrote {p.name} ({p.stat().st_size:,} B)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
