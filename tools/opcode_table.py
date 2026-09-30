"""
Decode TREE method records with the .rdata opcode name table.

The table at VA 0x723ca4 is 84 NUL-terminated strings packed in ascending
address order:

    [0] FLE [1] FLT [2] FGE ... [62] RETURN ... [83] N/A

If that is the opcode enum, then a disassembly of a method record using it
should read like real code: locals created, literals pushed, fields read,
calls made, and a RETURN at the end.  Verify by decoding and by scoring how
many records end on RETURN.

Usage: python tools/opcode_table.py [--class java.game.Bet] [--n 12]
"""
import struct
import sys
from collections import Counter
from pathlib import Path

EXE = r"C:\Games\LASR\LASR.exe"
IB = 0x400000
TBL = 0x723CA4                      # VA of "FLE"
NREC_END = 0x723F98                 # VA of "N/A"
EXTRACT = Path(__file__).resolve().parent.parent / "extracted"


def sections(d):
    pe = struct.unpack_from("<I", d, 0x3C)[0]
    nsec = struct.unpack_from("<H", d, pe + 6)[0]
    optsz = struct.unpack_from("<H", d, pe + 20)[0]
    base = pe + 24 + optsz
    out = []
    for i in range(nsec):
        o = base + 40 * i
        nm = d[o:o + 8].rstrip(b"\0").decode("latin1")
        vsz, va, rsz, raw = struct.unpack_from("<IIII", d, o + 8)
        out.append((nm, va, vsz, raw, rsz))
    return out


def va2off(secs, va):
    va -= IB
    for nm, sva, vsz, raw, rsz in secs:
        if sva <= va < sva + max(vsz, rsz):
            return raw + (va - sva)
    return None


def load_names(d, secs, with_meta=False):
    """The opcode name blob.

    The entries are NUL-terminated strings but each record is PADDED to a
    4-byte boundary, so splitting on NUL loses one-character names (this
    silently dropped 'OR' and shifted every index after XOR by one, which is
    what made the numeric->name mapping look unsolvable). Walk the blob at
    4-byte-aligned record starts instead.
    """
    off = va2off(secs, TBL)
    end = va2off(secs, NREC_END)
    blob = d[off:end + 4]
    names, offs = [], []
    o = 0
    while o < len(blob):
        e = blob.find(b"\0", o)
        if e < 0:
            break
        s = blob[o:e]
        if s and all(0x20 <= b < 0x7F for b in s):
            names.append(s.decode("latin1"))
            offs.append(o)
        o = e + 1
        o = (o + 3) & ~3 if o % 4 else o
    if with_meta:
        return names, offs
    return names


def opcode_name(names, op):
    """`opcode = 84 - name_table_index` (verified in docs/08_VM_OPCODES.md).

    Every semantic group of the name table appears in opcode space as a
    contiguous run in reverse order; and the opcode whose payloads are 99%
    valid f32 lands on FLOAT LITERAL under exactly this mapping.
    """
    i = 84 - op
    return names[i] if 0 <= i < len(names) else "?"


# ---------------------------------------------------------------- TUFA parser
def chunks(buf):
    """TUFA v4: <4cc> <u32 total> then payload; chunk = u32 count + count items."""
    out = {}
    p = 0
    while p + 8 <= len(buf):
        tag = buf[p:p + 4]
        if not tag.isalpha() and tag not in (b"TREE", b"CONS", b"FILD",
                                             b"MTHD", b"CLSS"):
            break
        size, = struct.unpack_from("<I", buf, p + 4)
        body = buf[p + 8:p + 8 + size]
        out.setdefault(tag.decode("latin1"), []).append(body)
        p += 8 + size
    return out


def tree_records(tree_body):
    n, = struct.unpack_from("<I", tree_body, 0)
    recs = []
    p = 4
    for _ in range(n):
        if p + 4 > len(tree_body):
            break
        sz, = struct.unpack_from("<I", tree_body, p)
        p += 4
        recs.append(tree_body[p:p + sz])
        p += sz
    return recs


def find_class(name):
    for p in sorted(EXTRACT.rglob(name + ".class")):
        return p
    for p in sorted(EXTRACT.rglob("*.class")):
        if p.stem == name.split(".")[-1]:
            return p
    return None


def main():
    d = open(EXE, "rb").read()
    secs = sections(d)
    names = load_names(d, secs)
    print(f"opcode table: {len(names)} names  {names[:6]} ... {names[-2:]}")

    cls = "java.game.Bet"
    if "--class" in sys.argv:
        cls = sys.argv[sys.argv.index("--class") + 1]
    nshow = 12
    if "--n" in sys.argv:
        nshow = int(sys.argv[sys.argv.index("--n") + 1])

    path = find_class(cls)
    print(f"class file: {path}")
    if not path:
        return
    ck = chunks(path.read_bytes())
    print("chunks:", {k: len(v) for k, v in ck.items()})
    if "TREE" not in ck:
        print("no TREE chunk")
        return
    recs = tree_records(ck["TREE"][0])
    print(f"TREE records: {len(recs)}\n")

    # how many records END on each byte, using the table for the name
    ends = Counter()
    for r in recs:
        if r:
            ends[r[-1]] += 1
    print("most common LAST byte of a record (opcode index -> name):")
    for b, c in ends.most_common(10):
        nm = names[b] if b < len(names) else "?"
        print(f"   0x{b:02x} ({b:3d})  {nm:<20} x{c}")
    print()

    # full byte histogram
    allb = Counter()
    for r in recs:
        allb.update(r)
    print("most common bytes across all records (opcode index -> name):")
    for b, c in allb.most_common(24):
        nm = names[b] if b < len(names) else "?"
        print(f"   0x{b:02x} ({b:3d})  {nm:<20} x{c}")

    print(f"\n--- raw bytes of the first {nshow} records ---")
    for i, r in enumerate(recs[:nshow]):
        print(f"  rec[{i}] len={len(r):<4} {r[:48].hex(' ')}"
              f"{' …' if len(r) > 48 else ''}")


if __name__ == "__main__":
    main()
