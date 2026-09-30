"""
Dump printable strings out of every extracted TUFA class and index them, so we
can locate the game's own loader code for a given format by the names it uses
(field names, method names, signatures and error messages are all stored as
plain ASCII inside the class).

Usage:
  python tools/class_strings.py --grep rpk
  python tools/class_strings.py --class java/util/resource/Package.class
"""
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EX = ROOT / "extracted"
STR = re.compile(rb"[\x20-\x7e]{3,120}")

cache = {}


def strings_of(path):
    d = path.read_bytes()
    return [m.group().decode() for m in STR.finditer(d)]


def load_index():
    idx = defaultdict(list)
    for p in sorted(EX.rglob("*.class")):
        for s in strings_of(p):
            idx[s].append(p)
    return idx


def main():
    if "--class" in sys.argv:
        target = sys.argv[sys.argv.index("--class") + 1].replace("\\", "/")
        hits = [p for p in EX.rglob("*.class") if target.lower() in str(p).replace("\\", "/").lower()]
        for p in hits[:3]:
            print(f"=== {p.relative_to(EX)} ===")
            for s in strings_of(p):
                print("   ", s)
            print()
        return

    needle = sys.argv[sys.argv.index("--grep") + 1].lower() if "--grep" in sys.argv else ""
    if not needle:
        print("need --grep TERM or --class PATH")
        return

    idx = load_index()
    matches = {s: ps for s, ps in idx.items() if needle in s.lower()}
    # rank classes by how many distinct matches they contain
    score = defaultdict(set)
    for s, ps in matches.items():
        for p in ps:
            score[p].add(s)
    top = sorted(score.items(), key=lambda kv: -len(kv[1]))[:15]
    print(f"term {needle!r}: {len(matches)} distinct strings, "
          f"{len(score)} classes\n")
    for p, ss in top:
        print(f"--- {p.relative_to(EX)}  ({len(ss)} hits)")
        for s in sorted(ss)[:40]:
            print("      ", s)
        print()


if __name__ == "__main__":
    main()
