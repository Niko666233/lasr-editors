"""
Re-solve the per-opcode instruction width, now that the opcode enumeration is
certain (see docs/08_VM_OPCODES.md).

What changed versus opcode_align.py:

1. HARD legality constraint read off the dispatcher at 0x6538f0:
       movsx eax, byte ptr [edi] ; dec eax ; cmp eax, 0x54 ; ja illegal
   so the table index is `opcode - 1` and the legal opcodes are
   0x01..0x55 (1-based, 85 values).  0x00 and >0x55 cannot start an
   instruction.  The old solver allowed 0x00..0x54, which is why 9,950
   phantom `0x00` instructions survived into the parse.

2. We now KNOW the opcode names, so the table can be seeded from the name
   semantics instead of 8 hand-read seeds, and every disagreement between the
   names and the solved widths can be reported with its evidence.

3. The objective keeps "sum of sane 4-byte payloads, gated on landing exactly
   on the record end" (a misaligned parse eats neighbouring instruction bytes
   and random 4-byte windows are insane), but the search adds plateau moves
   and random restarts, because plain single-flip greedy gets stuck.

Usage:
    python tools/opcode_align2.py [--rounds 30] [--restarts 8] [--plateau 6]
"""
import random
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from opcode_table import chunks, tree_records, load_names, sections   # noqa: E402

LIM_INT = 1 << 24
LIM_FLT = 1e6
OP_MIN, OP_MAX = 0x01, 0x55          # dispatcher: opcode-1 <= 0x54
EXE = r"C:\Games\LASR\LASR.exe"


# ---------------------------------------------------------------- name mapping
def opcode_name(names, op):
    """opcode -> name, with the reserved hole at 0x0a (docs/08 #5.3)."""
    if op == 0x0A:
        return None
    if 0x01 <= op <= 0x09:
        i = 84 - op
    elif 0x0B <= op <= 0x55:
        i = 85 - op
    else:
        return None
    return names[i] if 0 <= i < len(names) else None


# Names that must carry a 4-byte operand, and names that must not.  Kept as two
# explicit sets rather than one so that anything unlisted is simply "unknown"
# and left to the data.  Derived from the JavaMachine handler semantics in
# docs/08 #5.2 plus the standard bytecode meaning of each name.
OPERAND = {
    "CAST", "INSTANCEOF", "NULL LITERAL", "BOOL LITERAL", "INT LITERAL",
    "FLOAT LITERAL", "CHAR LITERAL", "STRING LITERAL", "RID LITERAL",
    "LOCAL_LOAD", "LOCAL_CREATE", "LOCAL_STORE", "LOCAL_CLEAR", "LOCAL_CLEARN",
    "INVOKE", "INVOKESPECIAL", "INVOKESTATIC",
    "FIELD_REF_INSTANCE", "FIELD_REF_STATIC", "FIELD_REF_QUICK",
    "PUTFIELD_INSTANCE", "PUTFIELD_STATIC", "PUTFIELD_QUICK",
    "JMP", "JMP_NE", "JMP_EQ", "JMP_EQ2",
    "NEWARRAY", "ARRAY_INIT", "ARRAY_ACCESS", "NEW", "DELETE",
    "IINC", "FINC", "IDEC", "FDEC", "N/A",
}
NO_OPERAND = {
    "POP", "DUP", "DUP_X1", "DUP_X2", "DUP2", "RETURN",
    "SADD", "IADD", "FADD", "ISUB", "FSUB", "IDIV", "FDIV", "IMUL", "FMUL",
    "INEG", "FNEG", "MOD", "AND", "OR", "XOR", "NOT", "EXCLAMATION",
    "ANDAND", "OROR", "SHORTCUT_AND", "SHORTCUT_OR",
    "ASR", "ASL", "LSR",
    "IEQ", "INE", "IGT", "IGE", "ILT", "ILE",
    "FEQ", "FNE", "FGT", "FGE", "FLT", "FLE",
    "F2I", "I2F", "I2S", "F2S", "ARRAY_STORE", "EMPTYDIMS",
}


def sane(payload):
    if payload < LIM_INT:
        return 1
    v, = struct.unpack("<f", struct.pack("<I", payload))
    if v == v and abs(v) < LIM_FLT:
        return 1
    return 0


def lands(body, W):
    """True iff the width table decomposes the body exactly to its end."""
    pos, n = 0, len(body)
    while pos < n:
        op = body[pos]
        if op < OP_MIN or op > OP_MAX:
            return False
        w = W.get(op)
        if w is None or pos + w > n:
            return False
        pos += w
    return True


def score_body(body, W):
    """Sane-payload count, or -1 when the table cannot decompose the body.

    NOTE: a body made only of 1-byte opcodes legitimately scores 0, so callers
    must test with `score_body(...) >= 0` (not `> 0`) - using `> 0` silently
    undercounts the parse rate.  Use `lands()` when only the boolean matters.
    """
    pos, n, tot = 0, len(body), 0
    while pos < n:
        op = body[pos]
        if op < OP_MIN or op > OP_MAX:
            return -1
        w = W.get(op)
        if w is None or pos + w > n:
            return -1
        if w == 5:
            tot += sane(struct.unpack_from("<I", body, pos + 1)[0])
        pos += w
    return tot if pos == n else -1


def main():
    argv = sys.argv[1:]

    def opt(flag, dflt):
        return int(argv[argv.index(flag) + 1]) if flag in argv else dflt

    rounds, restarts, plateau = opt("--rounds", 30), opt("--restarts", 8), opt("--plateau", 6)

    data = Path(EXE).read_bytes()
    names = load_names(data, sections(data))

    recs = []
    for f in sorted(Path("extracted").rglob("*.class")):
        try:
            ck = chunks(f.read_bytes())
        except Exception:
            continue
        if "TREE" in ck:
            try:
                recs += [r[:-1] for r in tree_records(ck["TREE"][0])
                         if r and r[-1] == 0x16]
            except Exception:
                pass
    print(f"{len(recs)} terminated TREE records")
    print(f"legal opcode range: 0x{OP_MIN:02x}..0x{OP_MAX:02x}  (dispatcher @0x6538f0)")

    def total(W):
        s = 0
        for b in recs:
            t = score_body(b, W)
            if t > 0:
                s += t
        return s

    def exact(W):
        return sum(1 for b in recs if lands(b, W))

    # ---- seed from the (now certain) opcode names -------------------------
    sem = {k: 5 for k in range(256)}
    unknown = []
    for op in range(OP_MIN, OP_MAX + 1):
        nm = opcode_name(names, op)
        if nm in OPERAND:
            sem[op] = 5
        elif nm in NO_OPERAND:
            sem[op] = 1
        else:
            unknown.append(op)
    print(f"semantic seed from names; {len(unknown)} opcodes unknown -> left at width 5: "
          + " ".join(f"{o:02x}" for o in unknown))
    print(f"  semantic: sane = {total(sem):,}   exact = {exact(sem)}/{len(recs)} "
          f"({100*exact(sem)/len(recs):.2f}%)")

    best_W, best = dict(sem), total(sem)
    W = dict(sem)

    # ---- baseline: the old solver's table, under the SAME scoring ---------
    try:
        from lasr_vm import load_records, solve_widths
        old_recs = load_records()
        OW, oex, otot = solve_widths(old_recs)
        bodies = [r[2] for r in old_recs]
        osane = sum(t for t in (score_body(b, OW) for b in bodies) if t >= 0)
        oexact = sum(1 for b in bodies if lands(b, OW))
        print(f"  OLD table (lasr_vm.solve_widths) under the legality constraint: "
              f"sane = {osane:,}   exact = {oexact}/{len(bodies)} "
              f"({100*oexact/len(bodies):.2f}%)")
        w1o = " ".join(f"{k:02x}" for k in range(OP_MIN, OP_MAX + 1) if OW.get(k) == 1)
        print(f"    old width-1 set: {w1o}")
    except Exception as e:
        print(f"  (old table unavailable: {e})")

    def climb(W0, tag):
        W0, s0 = dict(W0), total(W0)
        for r in range(rounds):
            moved = False
            for op in range(OP_MIN, OP_MAX + 1):
                if op == 0x0A:
                    continue
                trial = dict(W0)
                trial[op] = 5 if W0[op] == 1 else 1
                s = total(trial)
                if s > s0:
                    W0, s0, moved = trial, s, True
            if not moved:
                return W0, s0, r
        return W0, s0, rounds

    W, best, used = climb(W, "seed")
    print(f"greedy from seed: sane = {best:,}  exact = {exact(W)}/{len(recs)} "
          f"({100*exact(W)/len(recs):.2f}%)  [{used} rounds]")

    # ---- plateau + random restarts ---------------------------------------
    rng = random.Random(20260927)
    for it in range(restarts):
        cand = dict(W)
        for _ in range(rng.randint(1, plateau)):
            op = rng.randrange(OP_MIN, OP_MAX + 1)
            if op != 0x0A:
                cand[op] = 5 if cand[op] == 1 else 1
        cand, s, _ = climb(cand, f"restart{it}")
        if s > best:
            best, W = s, cand
            print(f"  restart {it}: improved -> sane = {s:,}  exact = {exact(W)}")
    print(f"\nFINAL: sane = {best:,}   exact = {exact(W)}/{len(recs)} "
          f"({100*exact(W)/len(recs):.2f}%)")

    # ---- report every disagreement with the name semantics ---------------
    print("\n=== disagreements between solved widths and name semantics ===")
    print(f"{'op':>4} {'name':>20} {'sem':>4} {'data':>5} {'count':>8}")
    import collections
    cnt = collections.Counter()
    for b in recs:
        p = 0
        while p < len(b):
            op = b[p]
            cnt[op] += 1
            p += W.get(op, 5)
    diffs = 0
    for op in range(OP_MIN, OP_MAX + 1):
        nm = opcode_name(names, op)
        if nm is None:
            continue
        s = 5 if nm in OPERAND else (1 if nm in NO_OPERAND else None)
        if s is None or s == W[op]:
            continue
        diffs += 1
        print(f"0x{op:02x} {nm:>20} {s:>4} {W[op]:>5} {cnt.get(op,0):>8}")
    print(f"({diffs} disagreements)")

    bad = [b for b in recs if not lands(b, W)]
    print(f"\nrecords still not landing: {len(bad)}")
    for b in bad[:3]:
        print(f"   len={len(b)} {b.hex(' ')}")

    w1 = " ".join(f"{k:02x}" for k in range(OP_MIN, OP_MAX + 1) if W.get(k) == 1)
    print(f"\nwidth 1 opcodes ({len(w1.split())}): {w1}")

    import json
    Path("out_w.json").write_text(json.dumps(
        {f"{k:02x}": W[k] for k in range(OP_MIN, OP_MAX + 1)}, indent=0))
    print("solved table written to out_w.json")


if __name__ == "__main__":
    main()
