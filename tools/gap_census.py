"""
Census of the unclaimed regions ("gap" blobs) of the map archives.

Two distinct payload kinds are visible:
  * a name-bearing record table (`track_other`, `track_phys`, `track_adds`, ...)
  * large float blocks with `ff ff ff ff` separators (terrain geometry)

This prints the name vocabulary and classifies each gap.
"""
import collections
import glob
import os
import re
import struct

STR = re.compile(rb"[\x20-\x7e]{3,80}")


def classify(d):
    n = len(d)
    notes = []
    # float density: fraction of 4-byte windows that are finite and small
    if n >= 16:
        vals = struct.unpack_from("<%df" % (n // 4), d, 0)
        good = sum(1 for v in vals if -1e6 < v < 1e6)
        frac = good / len(vals)
        notes.append(f"finite-float {frac*100:.0f}%")
        if frac > 0.9:
            notes.append("float-block")
    strings = [m.group().decode() for m in STR.finditer(d)]
    notes.append(f"{len(strings)} strings")
    if strings:
        notes.append("name-table")
    return notes


def main():
    gaps = sorted(glob.glob("extracted_rpak/**/gap*.bin", recursive=True),
                  key=os.path.getsize, reverse=True)
    vocab = collections.Counter()
    print(f"{len(gaps)} gap blobs\n")
    for g in gaps:
        d = open(g, "rb").read()
        if len(d) < 4096:
            continue
        print(f"{os.path.relpath(g, 'extracted_rpak'):46s} {len(d):>12,} B   "
              f"{', '.join(classify(d))}")
        if "name-table" in classify(d):
            for m in STR.finditer(d):
                s = m.group().decode()
                if s not in ("mesh", "texture"):
                    vocab[s] += 1

    print(f"\n=== name vocabulary from map gaps ({len(vocab)} distinct) ===")
    for s, c in vocab.most_common(60):
        print(f"   {c:6d}  {s}")


if __name__ == "__main__":
    main()
