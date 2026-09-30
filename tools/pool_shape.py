"""
Solve the TUFA `CONS` entry layout by search instead of by eye.

The pool is `<u32 count>` followed by `count` entries, each `<u8 tag><payload>`.
Tag 0 is a NUL-terminated string.  What is *not* obvious is the payload size of
the other tags - JVM-style pools mix 4-byte indices (Class, String, Integer),
8-byte pairs (Field/Method refs, NameAndType) and 8-byte literals (Long, Double).

Guessing one wrong size desynchronises the walk, which is why reading the bytes
by eye fails: the walk still lands near the end but yields the wrong number of
entries.  Two hard constraints turn this into a searchable problem:

  * the walk must end EXACTLY at the end of the blob, and
  * it must yield EXACTLY `count` entries.

DFS over the walk, assigning a payload size to each tag on first sight, with
candidate sizes {4, 8} (plus "string" for tag 0).  The solution is then verified
against every class in the game, which is the real test.

Usage:
  python tools/pool_shape.py extracted/java/classes/game/Bet.class
  python tools/pool_shape.py --verify <sizes-json>
"""
import json
import struct
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

from lasr_vm import chunks                                # noqa: E402

STRING = -1
CANDIDATE_SIZES = (4, 8, 16)


def walk(blob, sizes):
    """Walk with a fixed size map. Returns (ok, n_entries, pos) or None on bad tag."""
    pos, i, n = 4, 0, len(blob)
    while pos < n:
        tag = blob[pos]
        if tag == 0:
            end = blob.find(b"\x00", pos + 1)
            if end < 0:
                return None
            pos = end + 1
        else:
            s = sizes.get(tag)
            if s is None:
                return None
            pos += 1 + s
            if pos > n:
                return None
        i += 1
    return (True, i, pos)


def solve(blob, count, max_tag=32, limit=8):
    """DFS the walk, assigning sizes to tags on first sight."""
    n = len(blob)
    results = []

    def rec(pos, idx, sizes):
        if len(results) >= limit:
            return
        if pos == n:
            if idx == count:
                results.append(dict(sizes))
            return
        if idx >= count or pos > n:
            return
        tag = blob[pos]
        if tag == 0:
            end = blob.find(b"\x00", pos + 1)
            if end < 0:
                return
            rec(end + 1, idx + 1, sizes)
            return
        if tag > max_tag:
            return
        if tag in sizes:
            s = sizes[tag]
            if pos + 1 + s <= n:
                rec(pos + 1 + s, idx + 1, sizes)
            return
        for s in CANDIDATE_SIZES:
            if pos + 1 + s > n:
                continue
            sizes[tag] = s
            rec(pos + 1 + s, idx + 1, sizes)
            del sizes[tag]

    rec(4, 0, {})
    return results


def main():
    if "--verify" in sys.argv:
        sizes = {int(k): v for k, v in
                 json.loads(Path(sys.argv[sys.argv.index("--verify") + 1])
                            .read_text()).items()}
        ok = bad = 0
        tags = Counter()
        for f in sorted(ROOT.glob("extracted/**/*.class")):
            try:
                blob = chunks(f.read_bytes())["CONS"][0]
            except Exception:
                continue
            count = struct.unpack_from("<I", blob, 0)[0]
            r = walk(blob, sizes)
            if r and r[1] == count:
                ok += 1
                for b in blob[4:]:
                    pass
            else:
                bad += 1
                if bad <= 8:
                    got = r[1] if r else "desync"
                    print(f"  FAIL {f.name}: count={count} got={got}")
        print(f"\nverified: {ok} exact, {bad} failures out of {ok+bad}")
        return

    for arg in sys.argv[1:]:
        if arg.startswith("--"):
            continue
        p = Path(arg)
        blob = chunks(p.read_bytes())["CONS"][0]
        count = struct.unpack_from("<I", blob, 0)[0]
        print(f"=== {p.name}  blob={len(blob)} count={count} ===")
        sols = solve(blob, count)
        print(f"  solutions found: {len(sols)}")
        for s in sols[:6]:
            print("   " + json.dumps({str(k): v for k, v in sorted(s.items())}))
        if sols:
            tags = Counter()
            pos, i = 4, 0
            while pos < len(blob):
                t = blob[pos]
                tags[t] += 1
                if t == 0:
                    pos = blob.find(b"\x00", pos + 1) + 1
                else:
                    pos += 1 + sols[0][t]
                i += 1
            print(f"  entry tag histogram (first solution): "
                  f"{dict(sorted(tags.items()))}")


if __name__ == "__main__":
    main()
