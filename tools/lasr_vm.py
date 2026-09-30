"""
Disassemble TUFA TREE method records and classify the opcodes.

Two things are now known and are re-derived here rather than hard-coded:

  * the opcode name table: 85 NUL-terminated strings packed in ascending
    address order in .rdata at VA 0x723ca4 (FLE, FLT, FGE ... CAST, N/A)
  * the instruction shape: `<u8 opcode> <4-byte payload>` for most opcodes,
    `<u8 opcode>` with no payload for a minority

The payload width of each opcode is recovered by hill-climbing on payload
sanity (misaligned parses consume bytes from neighbouring instructions, and
such garbage windows are almost never a plausible index or float), with the
constraint that an opcode byte can never exceed 0x54 - the size of the name
table.

What is NOT yet known is the mapping between the numeric opcode and its name
in that table, so this tool classifies each opcode by what its payloads look
like instead of guessing a name:

  FLOAT-LIT   payloads almost always decode as ordinary floats
  INDEX       payloads are small non-negative integers
  OFFSET      payloads are small signed integers that point at other
              instruction boundaries inside the same record
  NONE        no payload at all
  RAW         anything else

Usage:
  python tools/lasr_vm.py --class java.game.Bet --method 1
  python tools/lasr_vm.py --survey
"""
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from opcode_table import chunks, tree_records, load_names, sections   # noqa: E402

EXE = r"C:\Games\LASR\LASR.exe"
MAX_OP = 0x54
LIM_INT = 1 << 24
LIM_FLT = 1e6

# ---------------------------------------------------------------- width solve
SEEDS = {0x00: 1, 0x03: 1, 0x0C: 1, 0x0E: 1, 0x16: 1, 0x1B: 1, 0x1E: 1,
         0x23: 1, 0x26: 1, 0x29: 1, 0x2A: 1, 0x2C: 1, 0x2D: 1, 0x2E: 1,
         0x2F: 1, 0x30: 1, 0x31: 1, 0x32: 1, 0x33: 1, 0x34: 1, 0x35: 1,
         0x36: 1, 0x37: 1, 0x38: 1, 0x3D: 1, 0x3F: 1, 0x40: 1, 0x41: 1,
         0x42: 1, 0x43: 1, 0x46: 1, 0x47: 1, 0x48: 1, 0x4A: 1, 0x4B: 1,
         0x4C: 1, 0x4D: 1, 0x4E: 1, 0x4F: 1, 0x50: 1, 0x51: 1, 0x52: 1,
         0x54: 1}


def sane(payload):
    if payload < LIM_INT:
        return 1
    v, = struct.unpack("<f", struct.pack("<I", payload))
    return 1 if (v == v and abs(v) < LIM_FLT) else 0


def walk(body, W):
    """[(offset, opcode, width, payload)] or None if it does not land."""
    pos, out, n = 0, [], len(body)
    while pos < n:
        op = body[pos]
        if op > MAX_OP:
            return None
        w = W.get(op, 5)
        if pos + w > n:
            return None
        pay = struct.unpack_from("<I", body, pos + 1)[0] if w == 5 else None
        out.append((pos, op, w, pay))
        pos += w
    return out if pos == n else None


def load_records():
    recs = []
    for f in sorted(Path("extracted").rglob("*.class")):
        try:
            ck = chunks(f.read_bytes())
        except Exception:
            continue
        if "TREE" in ck:
            try:
                for i, r in enumerate(tree_records(ck["TREE"][0])):
                    if r and r[-1] == 0x16:
                        recs.append((f.stem, i, r[:-1]))
            except Exception:
                pass
    return recs


def solve_widths(recs):
    W = {k: 5 for k in range(256)}

    def total(Wt):
        s = 0
        for _, _, b in recs:
            p = walk(b, Wt)
            if p is None:
                continue
            s += sum(sane(v) for _, _, w, v in p if w == 5)
        return s

    W.update(SEEDS)
    best = total(W)
    for _ in range(20):
        improved = False
        for op in range(MAX_OP + 1):
            trial = dict(W)
            trial[op] = 5 if W[op] == 1 else 1
            s = total(trial)
            if s > best:
                best, W, improved = s, trial, True
        if not improved:
            break
    exact = sum(1 for _, _, b in recs if walk(b, W) is not None)
    return W, exact, len(recs)


# ------------------------------------------------------------- classification
def classify(recs, W):
    stats = defaultdict(lambda: {"n": 0, "tiny": 0, "neg": 0, "flt": 0,
                                 "idx": 0, "jmp_good": 0, "jmp_tot": 0,
                                 "first": 0, "last": 0, "vals": Counter()})
    for _, _, b in recs:
        prog = walk(b, W)
        if prog is None:
            continue
        starts = {o for o, _, _, _ in prog}
        for k, (o, op, w, pay) in enumerate(prog):
            s = stats[op]
            s["n"] += 1
            if k == 0:
                s["first"] += 1
            if k == len(prog) - 1:
                s["last"] += 1
            if w == 1:
                continue
            s["vals"][pay] += 1
            if pay < 256:
                s["tiny"] += 1
            if pay < LIM_INT:
                s["idx"] += 1
            if pay >= 0xFFFF0000:
                s["neg"] += 1
            v, = struct.unpack("<f", struct.pack("<I", pay))
            # a float *literal* is a normal-magnitude non-integral value; the
            # bit pattern of a small integer decodes to a denormal like 7e-45,
            # so require a sane exponent range too
            if v == v and 1e-3 < abs(v) < 1e4 and abs(v - int(v)) > 1e-4:
                s["flt"] += 1
            # does the payload point at another instruction boundary?
            off = o + 1 + pay
            if pay < 0x80000000 and off in starts:
                s["jmp_good"] += 1
            if pay < 0x80000000 and pay > 0:
                s["jmp_tot"] += 1
    return stats


def kind(s):
    if s["n"] == 0:
        return "unused"
    if s["idx"] == 0 and s["n"] > 0:
        return "NONE"
    if s["jmp_tot"] and s["jmp_good"] / max(s["jmp_tot"], 1) > 0.9:
        return "OFFSET"
    if s["flt"] / max(s["n"], 1) > 0.3:
        return "FLOAT-LIT"
    if s["tiny"] / max(s["n"], 1) > 0.5:
        return "INDEX"
    return "RAW"


def survey(recs, W, names):
    st = classify(recs, W)
    tot = sum(s["n"] for s in st.values())
    print(f"{len(recs)} methods, {tot:,} instructions\n")
    print(f"{'op':>4} {'table[op]':<18} {'count':>7} {'kind':<10} "
          f"{'tiny%':>6} {'idx%':>5} {'flt%':>5} {'first%':>7} {'last%':>6}")
    rows = []
    for op in range(MAX_OP + 1):
        s = st.get(op)
        if not s or s["n"] == 0:
            print(f"{op:>4} {names[op] if op < len(names) else '?':<18} "
                  f"{'-':>7} unused")
            continue
        k = kind(s)
        n = s["n"]
        rows.append((n, op, k))
        print(f"{op:>4} {names[op] if op < len(names) else '?':<18} {n:>7} "
              f"{k:<10} {100*s['tiny']//n:>5}% {100*s['idx']//n:>4}% "
              f"{100*s['flt']//n:>4}% {100*s['first']//n:>6}% "
              f"{100*s['last']//n:>5}%")
    print("\nby frequency:")
    for n, op, k in sorted(rows, reverse=True)[:20]:
        print(f"   {op:3d} 0x{op:02x} {names[op] if op < len(names) else '?':<18}"
              f" {n:>7}  {k}")


def disasm(recs, W, names, cls, idx, limit=80):
    hits = [(n, i, b) for n, i, b in recs if n == cls]
    if not hits:
        print(f"no records for class {cls!r}")
        return
    if idx >= len(hits):
        idx = 0
    name, i, b = hits[idx]
    prog = walk(b, W)
    print(f"{name} record[{i}]  body {len(b)} bytes, "
          f"{len(prog) if prog else '?'} instructions")
    if not prog:
        print("  does not parse")
        return
    for o, op, w, pay in prog[:limit]:
        nm = names[op] if op < len(names) else "?"
        if w == 1:
            print(f"  {o:05x}  {op:02x}        {nm}")
        else:
            v, = struct.unpack("<f", struct.pack("<I", pay))
            extra = f"  ; f32 {v:g}" if abs(v) < 1e6 and v == v else ""
            print(f"  {o:05x}  {op:02x} {pay:08x}  {nm:<18}{extra}")
    if len(prog) > limit:
        print(f"  ... {len(prog)-limit} more")


def main():
    d = open(EXE, "rb").read()
    names = load_names(d, sections(d))
    recs = load_records()
    print(f"loaded {len(recs)} TREE method records")
    W, exact, tot = solve_widths(recs)
    print(f"width solve: {exact}/{tot} records parse exactly "
          f"({100*exact/tot:.1f}%)")
    w1 = sorted(k for k in range(MAX_OP + 1) if W[k] == 1)
    print(f"opcodes with no payload ({len(w1)}): "
          f"{' '.join(f'{v:02x}' for v in w1)}\n")

    if "--survey" in sys.argv:
        survey(recs, W, names)
        return
    cls = "java.game.Bet"
    if "--class" in sys.argv:
        cls = sys.argv[sys.argv.index("--class") + 1]
    idx = 1
    if "--method" in sys.argv:
        idx = int(sys.argv[sys.argv.index("--method") + 1])
    disasm(recs, W, names, cls, idx)
    print()
    survey(recs, W, names) if "--also-survey" in sys.argv else None


if __name__ == "__main__":
    main()
