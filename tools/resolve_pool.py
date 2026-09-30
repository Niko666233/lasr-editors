"""
Resolve method operands through the TUFA `CONS` constant pool.

Pool layout, solved in tools/pool_shape.py (unique solution for Bet.class, then
verified byte-exact on all 2,224 classes with ZERO failures):

    CONS blob = <u32 count>
    entry     = <u8 tag> <payload>
        tag 0 : NUL-terminated UTF8 string
        tag 4 : 4 bytes   - a single index (Class -> its name)
        tag 5 : 8 bytes   - two indices (a reference / name+type pair)
        tag 7 : 8 bytes   - two indices (the other reference kind)

Those are the ONLY tags used anywhere in the game.  Numeric literals are not in
the pool at all: they are inline operands of `INT LITERAL` / `FLOAT LITERAL`.

Index base: 0-based, entry 0 is the class's own name (entry 1 is `tag4 -> 0`).

Usage:
  python tools/resolve_pool.py --dump <class>
  python tools/resolve_pool.py --class <class>
  python tools/resolve_pool.py --names             # global name table
"""
import json
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

from lasr_vm import chunks, tree_records                    # noqa: E402
from lasr_cfg import disasm, name_of                        # noqa: E402

SIZES = {4: 4, 5: 8, 7: 8}          # solved + verified on all 2,224 classes
TAG_UTF8 = 0


class Pool:
    def __init__(self, blob):
        self.blob = blob
        self.count = struct.unpack_from("<I", blob, 0)[0]
        self.entries = {}           # index -> (tag, values_tuple, offset)
        self.parse()

    def parse(self):
        pos, i, n = 4, 0, len(self.blob)
        while pos < n:
            tag = self.blob[pos]
            if tag == TAG_UTF8:
                end = self.blob.find(b"\x00", pos + 1)
                self.entries[i] = (tag, self.blob[pos + 1:end]
                                   .decode("latin-1"), pos)
                pos = end + 1
            else:
                s = SIZES.get(tag)
                if s is None:
                    raise ValueError(f"unknown tag {tag} at {pos}")
                vals = tuple(struct.unpack_from(f"<{s//4}I", self.blob, pos + 1))
                self.entries[i] = (tag, vals, pos)
                pos += 1 + s
            i += 1
        self.exact = (pos == n and i == self.count)
        self.n = i

    # ---- accessors --------------------------------------------------------
    def tag(self, idx):
        e = self.entries.get(idx)
        return e[0] if e else None

    def vals(self, idx):
        e = self.entries.get(idx)
        return e[1] if e else None

    def utf8(self, idx):
        e = self.entries.get(idx)
        return e[1] if e and e[0] == TAG_UTF8 else None

    def text(self, idx):
        """Human-readable content of an entry, following one hop of indices."""
        e = self.entries.get(idx)
        if e is None:
            return f"<none {idx}>"
        tag, val, _ = e
        if tag == TAG_UTF8:
            return val
        if tag == 4:
            # val is a 1-tuple: unpack it, or the index lookup silently fails
            s = self.utf8(val[0])
            return s if s is not None else f"tag4->{val[0]}?"
        # tag 5 / 7 : two indices
        a, b = val
        return f"[{self._brief(a)}|{self._brief(b)}]"

    def _brief(self, idx):
        e = self.entries.get(idx)
        if e is None:
            return str(idx)
        if e[0] == TAG_UTF8:
            return e[1]
        return f"{idx}(tag{e[0]})"

    def ref(self, idx):
        """Resolve an entry to (class, name, descriptor, kind).

        tag 7 is a NameAndType: payload is (name_utf8_idx, desc_utf8_idx), both
        pointing directly at strings.  tag 5 is a reference: (class_idx, nt_idx)
        where class_idx is a tag4 entry and nt_idx is a tag7 entry.  Which of
        field/method it is comes from the *opcode*, not the entry - the pool has
        no separate field-ref tag.
        """
        e = self.entries.get(idx)
        if e is None:
            return None
        tag, val, _ = e
        if tag == 4:
            s = self.utf8(val[0])
            return (s, None, None, "class") if s is not None else None
        if tag == 7:
            n2, d2 = val
            return (None, self.utf8(n2), self.utf8(d2), "nametype")
        if tag == 5:
            a, b = val
            owner = self.utf8(self.vals(a)[0]) if self.tag(a) == 4 else None
            nm = de = None
            if self.tag(b) == 7:
                n2, d2 = self.vals(b)
                nm, de = self.utf8(n2), self.utf8(d2)
            elif self.tag(b) == TAG_UTF8:
                nm = self.utf8(b)
            return (owner, nm, de, "ref")
        return None


def dump(path):
    blob = chunks(Path(path).read_bytes())["CONS"][0]
    p = Pool(blob)
    print(f"=== {path} ===")
    print(f"count={p.count} parsed={p.n} exact={p.exact} blob={len(blob)}B")
    hist = Counter(e[0] for e in p.entries.values())
    print(f"tags: {dict(sorted(hist.items()))}\n")
    for i in sorted(p.entries):
        tag, val, off = p.entries[i]
        raw = repr(val) if tag == TAG_UTF8 else \
            "(" + ", ".join(str(v) for v in val) + ")"
        print(f"  [{i:>4}] @{off:<6} tag{tag} {raw:<30} :: {p.text(i)}")
    return p


def resolve_class(path):
    ck = chunks(Path(path).read_bytes())
    p = Pool(ck["CONS"][0])
    out = defaultdict(Counter)
    for r in tree_records(ck["TREE"][0]):
        if not r or r[-1] != 0x16:
            continue
        for ins in disasm(r):
            if ins.pay is None:
                continue
            out[ins.op][ins.pay] += 1
    return p, out


def main():
    args = sys.argv[1:]
    if "--names" in args:
        raws, methods, fields, classes, counts = set(), set(), set(), set(), 0
        for f in sorted(ROOT.glob("extracted/**/*.class")):
            try:
                ck = chunks(f.read_bytes())
                p = Pool(ck["CONS"][0])
            except Exception:
                continue
            if not p.exact:
                continue
            counts += 1
            for i in p.entries:
                r = p.ref(i)
                if not r:
                    continue
                owner, nm, de, kind = r
                if kind == "class":
                    classes.add(owner)
                elif nm:
                    methods.add((owner, nm, de))
        print(f"classes with exact pool : {counts}")
        print(f"distinct class names    : {len(classes):,}")
        print(f"distinct member refs    : {len(methods):,}")
        print("\nsample class names:")
        for c in sorted(x for x in classes if x)[:20]:
            print(f"   {c}")
        print("\nsample member refs:")
        for o, n, d in sorted(methods)[:20]:
            print(f"   {o}.{n}{d}")
        return

    if "--dump" in args:
        dump(args[args.index("--dump") + 1])
        return

    path = args[args.index("--class") + 1] if "--class" in args else args[0]
    p, used = resolve_class(path)
    print(f"=== {path}  count={p.count} exact={p.exact} ===")
    hist = Counter(e[0] for e in p.entries.values())
    print(f"tags: {dict(sorted(hist.items()))}\n")
    for op in sorted(used):
        c = used[op]
        print(f"  0x{op:02x} {name_of(op):<20} {sum(c.values()):>5} uses, "
              f"{len(c):>3} distinct")
        for pay, cnt in c.most_common(14):
            t = p.tag(pay)
            r = p.text(pay) if t is not None else f"<no entry {pay}>"
            print(f"        {pay:>5} x{cnt:<4} tag{t} {r}")


if __name__ == "__main__":
    main()
