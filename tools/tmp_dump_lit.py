"""Throwaway: dump methods + literals (+ labels) for chosen part classes."""
import sys, re, struct
from pathlib import Path

HERE = Path(r"C:\Users\niko6\Desktop\Work\LASR_Reverse_Engineering")
sys.path.insert(0, str(HERE / "editors"))
from lasr_core import tufa, labels


def dump(path, show_ops=False, want=None):
    data = Path(path).read_bytes()
    t = tufa.Tufa(data)
    cls = None
    for tag, off, blob in [(c[0], c[1], c[2]) for c in tufa.chunks(data)]:
        if tag == "CLSS":
            cls = blob
    print("=" * 90)
    print("FILE", Path(path).name, " methods:", len(t.methods))
    for m in t.methods:
        if want and m.name not in want:
            continue
        lits = t.literals(m)
        print("  --- %s %s  (%d lits, linear=%s, nlocals=%s)"
              % (m.name, m.desc, len(lits), m.linear, m.n_locals))
        for idx, off, kind, val in lits:
            lab = labels.label_for(Path(path).stem, m.name, idx)
            print("      [%2d] %-6s %-22r  %s" % (idx, kind, val, lab or ""))
    return t


if __name__ == "__main__":
    for p in sys.argv[1:]:
        dump(p)
