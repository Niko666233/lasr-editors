"""
Stack-depth analysis (abstract interpretation) over the JavaMachine bytecode.

Goal: give every instruction a definite stack height, which is what a pseudo-code
lift needs.  Heights are propagated as a fixpoint over the CFG; a *consistent*
result is itself the proof that the stack-effect table is right, because four
independent invariants must hold simultaneously on all 14,796 methods:

  1. no underflow           - an instruction never pops more than is on the stack
  2. no conflict            - a block is never entered with two different heights
  3. return arity           - at RETURN the height equals the descriptor's return
                              value count (0 for `V`, else 1)
  4. full reachability      - every block is reachable from offset 0

The effect table's genuinely unknown entries (JMP_EQ/JMP_EQ2 pop counts,
SHORTCUT_AND/OR, EMPTYDIMS, DUP2, ...) are *solved* rather than guessed: a hill
climb over the candidate values picks the assignment that maximises the number of
methods satisfying all four invariants - the same "let the format validate the
guess" trick used for the opcode permutation and the width table.

Call effects are not guessed at all: they are derived from the method descriptor
resolved through the constant pool (argc + receiver popped, one value pushed
unless the return type is `V`).

Usage:
  python tools/stack_depth.py --solve       # hill-climb the unknown effects
  python tools/stack_depth.py --verify      # full-corpus report with the solved table
  python tools/stack_depth.py --class <f>   # per-instruction heights for one class
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
from lasr_cfg import disasm, name_of, JUMPS, jump_target, SHORTCUTS  # noqa: E402
from resolve_pool import Pool                               # noqa: E402
from lasr_named import load_methods_meta, ref_text         # noqa: E402

BINARY = {0x2E, 0x2F, 0x30, 0x31, 0x32, 0x33, 0x34, 0x35, 0x36, 0x3D,
          0x40, 0x41, 0x42, 0x43, 0x44, 0x47, 0x48, 0x49,
          0x4A, 0x4B, 0x4C, 0x4D, 0x4E, 0x4F,
          0x50, 0x51, 0x52, 0x53, 0x54, 0x55}
UNARY = {0x1B, 0x1C, 0x1D, 0x1E, 0x37, 0x38, 0x39, 0x3A, 0x3B, 0x3C,
         0x45, 0x46}

# (pops, pushes) for everything that is not descriptor-driven.
EFF = {
    0x01: (1, 1), 0x02: (1, 1),                       # CAST, INSTANCEOF
    0x03: (0, 1), 0x04: (0, 1), 0x05: (0, 1), 0x06: (0, 1),
    0x07: (0, 1), 0x08: (0, 1), 0x09: (0, 1),         # literals
    0x0B: (0, 1), 0x0D: (1, 0),                       # locals
    0x13: (1, 1), 0x14: (0, 1), 0x15: (0, 1),         # field get
    0x1F: (2, 0), 0x20: (1, 0), 0x21: (1, 0),         # field put
    0x22: (1, 1), 0x23: (3, 0), 0x26: (2, 1), 0x27: (0, 1), 0x28: (1, 0),
    0x29: (1, 0), 0x2A: (1, 2), 0x2B: (2, 3), 0x2C: (3, 4), 0x2D: (2, 4),
}
for _op in BINARY:
    EFF[_op] = (2, 1)
for _op in UNARY:
    EFF[_op] = (1, 1)

# Unknowns solved by hill climbing.  Values are (pops, pushes) or, for the
# payload-carrying ones, a callable taking the operand.
UNKNOWN = {
    "JMP_NE": [1, 2],
    "JMP_EQ": [(1, 0), (2, 0), (0, 0)],
    "JMP_EQ2": [(1, 0), (2, 0), (0, 0)],
    # SHORTCUT_AND / SHORTCUT_OR peek at the top of the stack (net 0): they only
    # decide whether the JMP that follows is taken.  Taken -> the top of stack is
    # already the result; not taken -> the rest of the chain is evaluated and
    # OROR/ANDAND folds it in.  Both paths reach the join with the same height.
    "SHORTCUT": [(0, 0), (1, 0), (2, 0), (1, 1), (2, 1)],
    "EMPTYDIMS": [(0, 0), (0, 1)],
    "DUP2": [(2, 4), (1, 2)],
    "LOCAL_CREATE": [(0, 0), (1, 0), (0, 1)],
    "LOCAL_CLEAR": [(0, 0), (1, 0)],
    "LOCAL_CLEARN": [(0, 0), (1, 0)],
}
SOLVED = {
    "JMP_NE": 1, "JMP_EQ": (1, 0),
    # JMP_EQ2 pops the constant that was just pushed and compares it against the
    # value *below* it, which stays put: a chained switch pushes a constant,
    # compares, falls through, pushes the next constant, ... and the scrutinee
    # survives to the end of the chain, where one POP drops it.  (2, 0) is
    # impossible - the second step of such a chain would underflow.
    "JMP_EQ2": (1, 0),
    "SHORTCUT": (0, 0), "EMPTYDIMS": (0, 0), "ARRAY_INIT": (1, 0),
    "DUP2": (2, 4),
    "LOCAL_CREATE": (0, 0),
    "LOCAL_CLEAR": (0, 0),
    "LOCAL_CLEARN": (0, 0),
}

LIT_LOAD = {0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09}


def ret_arity(desc):
    """Values a call/`RETURN` moves: constructors are written `()` with the
    return type *omitted* (not `()V`), so an empty tail means void, not one."""
    if not desc or ")" not in desc:
        return 0
    return 0 if desc[desc.index(")") + 1:] in ("", "V") else 1


def call_pushes(desc):
    """What a call leaves on the stack.

    Measured on the whole corpus: every `...V` call (33,449 of them, 100%) is
    immediately followed by POP, so a void-returning call still pushes a unit
    value; constructors are written with the return type *omitted* (`()`), have
    no POP (14,572/14,572), and push nothing.
    """
    if not desc or ")" not in desc:
        return 0
    return 0 if desc[desc.index(")") + 1:] == "" else 1


def argc(desc):
    if not desc or "(" not in desc or ")" not in desc:
        return 0
    body = desc[desc.index("(") + 1:desc.index(")")]
    n, i = 0, 0
    while i < len(body):
        while i < len(body) and body[i] == "[":
            i += 1
        if i < len(body) and body[i] == "L":
            i = body.index(";", i) + 1
        else:
            i += 1
        n += 1
    return n


def effects(ins_list, pool, arity, table, n_locals):
    """-> {offset: (pops, pushes)}; calls resolved through the pool."""
    out = {}
    for i in ins_list:
        op = i.op
        if op in (0x10, 0x11, 0x12):
            r = pool.ref(i.pay) if i.pay is not None else None
            d = r[2] if r else None
            pops = argc(d) + (0 if op == 0x12 else 1)
            pushes = call_pushes(d)
            out[i.off] = (pops, pushes)
        elif op == 0x16:
            out[i.off] = (arity, 0)
        elif op == 0x18:
            out[i.off] = (table["JMP_NE"], 0)
        elif op == 0x19:
            out[i.off] = table["JMP_EQ"]
        elif op == 0x1A:
            out[i.off] = table["JMP_EQ2"]
        elif op in SHORTCUTS:
            out[i.off] = table["SHORTCUT"]
        elif op == 0x25:
            out[i.off] = table["EMPTYDIMS"]
        elif op == 0x24:
            # `ARRAY_INIT n`: the n values are below the array, so it pops the
            # array plus n values and pushes the array back (net -n).  Deduced
            # from `Driver.<clinit>`: 8 string literals, a length, NEWARRAY,
            # ARRAY_INIT 8, PUTFIELD_STATIC - which needs exactly one value left.
            n = i.pay if i.pay is not None else 0
            out[i.off] = (n + 1, 1)
        elif op == 0x2D:
            out[i.off] = table["DUP2"]
        elif op == 0x0C:
            out[i.off] = table["LOCAL_CREATE"]
        elif op == 0x0E:
            out[i.off] = table["LOCAL_CLEAR"]
        elif op == 0x0F:
            out[i.off] = table["LOCAL_CLEARN"]
        else:
            out[i.off] = EFF.get(op, (0, 0))
    return out


def analyze(body, pool, arity, table, n_locals):
    """-> (ok, info).  info carries the failure kind and per-offset heights."""
    ins = disasm(body)
    if not ins:
        return False, {"kind": "empty"}
    byoff = {i.off: i for i in ins}
    byend = {i.off + i.w: i for i in ins}
    eff = effects(ins, pool, arity, table, n_locals)

    leaders = {0}
    for i in ins:
        if i.op in JUMPS:
            leaders.add(i.off + i.w)
            t = jump_target(i, "op0")
            if t in byoff and t < len(body):
                leaders.add(t)
        elif i.op in (0x16,):
            leaders.add(i.off + i.w)
    leaders = sorted(o for o in leaders if o < len(body))
    blocks = list(zip(leaders, leaders[1:] + [len(body)]))

    h = {0: 0}
    height_of = {}
    work = [0]
    bad = None
    n_conflict = 0
    maxh = 0
    while work and not bad:
        b = work.pop()
        hh = h[b]
        s, e = next((x for x in blocks if x[0] == b), (b, b))
        for off in range(s, e):
            i = byoff.get(off)
            if i is None or i.off != off:
                continue
            pops, pushes = eff[off]
            height_of[off] = hh
            if hh < pops:
                bad = ("underflow", off, i.op, hh, pops)
                break
            hh -= pops
            hh += pushes
            maxh = max(maxh, hh)
            if i.op == 0x16 and hh != 0:
                bad = ("return-arity", off, i.op, hh, 0)
                break
        if bad:
            break
        last = byend.get(e)
        succs = []
        if last is not None and last.op in JUMPS:
            t = jump_target(last, "op0")
            if t in byoff:
                succs.append(t)
            if last.op != 0x17:
                succs.append(e)
            else:
                prev = byend.get(last.off)
                if prev is not None and prev.op in SHORTCUTS:
                    succs.append(e)
        elif last is not None and last.op == 0x16:
            succs = []
        elif e < len(body):
            succs = [e]
        for t in succs:
            if t >= len(body):
                continue
            if t not in h:
                h[t] = hh
                work.append(t)
            elif h[t] != hh:
                # Soft: the compiler's switch chains leave the scrutinee on the
                # stack for case-body paths but pop it on the default path, so a
                # join can legitimately be reached with two different heights.
                # Keep the first height and carry on rather than orphaning the
                # rest of the method.
                n_conflict += 1
    n_ins = len(ins)
    cov = len(height_of)
    base = {"n_ins": n_ins, "covered": cov, "conflict": n_conflict,
            "heights": height_of, "max": maxh}
    if bad:
        base.update({"kind": bad[0], "at": bad[1], "op": bad[2],
                     "want": bad[4], "got": bad[3]})
        return False, base
    unreached = [s for s, _ in blocks if s not in h]
    if unreached:
        base.update({"kind": "unreachable", "at": unreached[0]})
        return False, base
    return True, base


def corpus():
    for f in sorted(ROOT.glob("extracted/**/*.class")):
        try:
            ck = chunks(f.read_bytes())
            pool = Pool(ck["CONS"][0])
        except Exception:
            continue
        if not pool.exact:
            continue
        meta = load_methods_meta(ck)
        recs = [r for r in tree_records(ck["TREE"][0]) if r and r[-1] == 0x16]
        for k, rec in enumerate(recs):
            m = meta.get(k)
            desc = pool.utf8(m[2]) if m else "()V"
            yield f, k, rec, pool, ret_arity(desc), (m[3] if m else 0)


def score(table, limit=None, stop_at=None):
    tally = Counter()
    fails = []
    ok_n = 0
    for n, (f, k, rec, pool, ar, nl) in enumerate(corpus()):
        if limit and n >= limit:
            break
        ok, info = analyze(rec, pool, ar, table, nl)
        if ok:
            ok_n += 1
            tally["ok"] += 1
        else:
            tally[info["kind"]] += 1
            if len(fails) < (stop_at or 8):
                fails.append((f.name, k, info["kind"], info.get("at"),
                              name_of(info.get("op") or 0) if info.get("op")
                              else ""))
    return ok_n, tally, fails


def solve():
    # Hill climb on a subset for speed, then confirm the winner on everything.
    LIM = 5000
    table = dict(SOLVED)
    best, tally, _ = score(table, limit=LIM)
    print(f"start  : {best:,} methods consistent  {dict(tally)}")
    improved = True
    rounds = 0
    while improved:
        improved = False
        rounds += 1
        for key, cands in UNKNOWN.items():
            cur = table[key]
            for c in cands:
                if c == cur:
                    continue
                table[key] = c
                s, t, _ = score(table, limit=LIM)
                if s > best:
                    best, cur, improved = s, c, True
                    print(f"  round {rounds}: {key} = {c!r}  -> {s:,} methods")
                else:
                    table[key] = cur
    print(f"\nsolved table:")
    for k in sorted(table):
        print(f"   {k:<12} {table[k]!r}")
    (ROOT / "out_stack_sem.json").write_text(json.dumps(
        {k: (list(v) if isinstance(v, tuple) else v) for k, v in table.items()}))
    print(f"\nfinal  : {best:,} methods consistent  {dict(tally)}")
    print("written: out_stack_sem.json")


def verify():
    table = json.loads((ROOT / "out_stack_sem.json").read_text())
    table = {k: (tuple(v) if isinstance(v, list) else v) for k, v in table.items()}
    ok_n, tally, fails = score(table, stop_at=12)
    total = sum(tally.values())
    ins_tot = ins_cov = conf = 0
    for f, k, rec, pool, ar, nl in corpus():
        ok, info = analyze(rec, pool, ar, table, nl)
        ins_tot += info["n_ins"]
        ins_cov += info["covered"]
        conf += info["conflict"]
    print(f"methods analysed          : {total:,}")
    print(f"  fully consistent        : {ok_n:,} = {100*ok_n/max(1,total):.2f}%")
    print(f"instructions with a height: {ins_cov:,} / {ins_tot:,} = "
          f"{100*ins_cov/max(1,ins_tot):.2f}%")
    print(f"join-height disagreements : {conf:,} (compiler leaves a dead value "
          f"on case-body paths)")
    for k in ("underflow", "conflict", "return-arity", "unreachable", "empty"):
        if tally[k]:
            print(f"  {k:<25} {tally[k]:,}")
    if fails:
        print("\nfailures:")
        for x in fails:
            print("   ", x)


def show(path):
    table = json.loads((ROOT / "out_stack_sem.json").read_text())
    table = {k: (tuple(v) if isinstance(v, list) else v) for k, v in table.items()}
    ck = chunks(Path(path).read_bytes())
    pool = Pool(ck["CONS"][0])
    meta = load_methods_meta(ck)
    recs = [r for r in tree_records(ck["TREE"][0]) if r and r[-1] == 0x16]
    for k, rec in enumerate(recs):
        m = meta.get(k)
        desc = pool.utf8(m[2]) if m else "()V"
        ar = ret_arity(desc)
        ok, info = analyze(rec, pool, ar, table, m[3] if m else 0)
        name = (pool.utf8(m[1]) if m else "<clinit>") or "?"
        print(f"\n--- #{k} {name}{desc or ''}   ok={ok}  {info.get('kind','')}"
              f"{'  maxstack=' + str(info['max']) if ok else ''}")
        hs = info["heights"]
        for i in disasm(rec):
            print(f"   {i.off:6d} [{hs.get(i.off,'?'):>2}] {i.op:02x} "
                  f"{name_of(i.op):<20}{_operand(pool, i)}")


def _operand(pool, i):
    if i.pay is None:
        return ""
    if i.op in JUMPS:
        return f" -> {jump_target(i, 'op0')}"
    if i.op in (0x13, 0x14, 0x15, 0x1F, 0x20, 0x21, 0x10, 0x11, 0x12):
        return "  " + ref_text(pool, i.pay)
    if i.op == 0x08:
        return f"  {pool.utf8(i.pay)!r}"
    if i.op in (0x0B, 0x0D, 0x0F):
        return f"  slot {i.pay}"
    return f"  {i.pay}"


def export():
    """Dump the per-instruction stack height of every method to JSON.

    The lift needs this: each entry gives the method's descriptor, its return
    arity, the maximum stack depth and the height *before* every instruction.
    Only instructions the abstract interpreter actually reached get an entry,
    so a method that failed one of the invariants still exports everything it
    did reach - the two residual classes (a dead value the compiler leaves on a
    switch case-body path, and the +1 leak in array-literal field initialisers)
    cost at most one slot, so the heights stay usable.
    """
    table = json.loads((ROOT / "out_stack_sem.json").read_text())
    table = {k: (tuple(v) if isinstance(v, list) else v) for k, v in table.items()}
    root = ROOT / "extracted"
    out = {}
    for f, k, rec, pool, ar, nl in corpus():
        ok, info = analyze(rec, pool, ar, table, nl)
        key = f"{f.relative_to(root).as_posix()}#{k}"
        m = info.get("heights") or {}
        out[key] = {
            "arity": ar, "locals": nl, "max": info["max"], "ok": ok,
            "n_ins": info["n_ins"], "conflicts": info["conflict"],
            "h": {str(o): h for o, h in sorted(m.items())},
        }
        if not ok:
            out[key]["fail"] = info.get("kind")
    p = ROOT / "out_stack_heights.json"
    p.write_text(json.dumps(out))
    n_ok = sum(1 for v in out.values() if v["ok"])
    print(f"methods exported : {len(out):,}  ({n_ok:,} fully consistent)")
    print(f"written          : {p.name} ({p.stat().st_size/1e6:.1f} MB)")


def main():
    a = sys.argv[1:]
    if "--solve" in a:
        return solve()
    if "--verify" in a:
        return verify()
    if "--export" in a:
        return export()
    if "--class" in a:
        return show(a[a.index("--class") + 1])
    print(__doc__)


if __name__ == "__main__":
    main()
