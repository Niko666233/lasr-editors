"""
Hypothesis test: every TUFA chunk is  u32 count  followed by  count  records,
each record being  u32 size + size bytes.

Runs over every extracted class and reports how many parse exactly to the end
of the chunk. Exact closure == the structure is right.
"""
import collections
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EX = ROOT / "extracted"


def chunks(data):
    off = 12
    while off + 8 <= len(data):
        tag = data[off:off + 4].decode("latin1")
        size = struct.unpack_from("<I", data, off + 4)[0]
        yield tag, data[off + 8:off + 8 + size]
        off += 8 + size


def try_records(payload):
    """(count, (size, blob)*) -> list of blobs, or None if it does not close."""
    if len(payload) < 4:
        return None
    count = struct.unpack_from("<I", payload, 0)[0]
    off = 4
    out = []
    for _ in range(count):
        if off + 4 > len(payload):
            return None
        size = struct.unpack_from("<I", payload, off)[0]
        off += 4
        if off + size > len(payload):
            return None
        out.append(payload[off:off + size])
        off += size
    return out if off == len(payload) else None


def main():
    stats = collections.defaultdict(lambda: [0, 0])   # tag -> [ok, total]
    examples = collections.defaultdict(list)
    rec_sizes = collections.defaultdict(list)
    for p in sorted(EX.rglob("*.class")):
        d = p.read_bytes()
        if d[:4] != b"TUFA":
            continue
        for tag, payload in chunks(d):
            r = try_records(payload)
            stats[tag][1] += 1
            if r is not None:
                stats[tag][0] += 1
                rec_sizes[tag].append(len(r))
                if len(examples[tag]) < 6:
                    examples[tag].append((str(p.relative_to(EX)), len(r),
                                          [len(b) for b in r[:8]]))
    for tag, (ok, tot) in sorted(stats.items()):
        print(f"{tag}: {ok}/{tot} chunks parse as (count,(size,blob)*)")
        if examples[tag]:
            for e in examples[tag][:3]:
                print(f"      {e[0]}: {e[1]} records, sizes {e[2]}")
        if rec_sizes[tag]:
            n = rec_sizes[tag]
            print(f"      record counts: min={min(n)} max={max(n)} "
                  f"avg={sum(n)/len(n):.1f}")


if __name__ == "__main__":
    main()
