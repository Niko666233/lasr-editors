"""
Disassembler for the JavaMachine bytecode, on top of the final width table.

`out_w_final.json` (tools/reconcile_widths.py) gives the instruction width for
every opcode 0x01..0x55: 55 opcodes are 1 byte, 30 are 5 bytes (`<u8 op><u32>`).
With that table all 14,796 method records decompose exactly, so instruction
boundaries are no longer a guess.

This module adds the two things a CFG needs on top of boundaries:

  * opcode -> name (85-entry .rdata table, see docs/08_VM_OPCODES.md),
  * jump-target resolution: which base register/offset the relative jump family
    (0x17 JMP, 0x18 JMP_NE, 0x19 JMP_EQ, 0x1a JMP_EQ2) is relative to.

The base question is answered from the corpus, not from taste: a correct base
makes ~100% of jump payloads land exactly on another instruction's start (a
wrong base lands mid-instruction almost always), and the payload of a jump is
*signed*, so forward and backward targets must both work.

Usage:
  python tools/lasr_cfg.py --jumpbases      # decide the relative-jump base
  python tools/lasr_cfg.py --stats          # per-method CFG statistics
  python tools/lasr_cfg.py --disasm 42      # disassemble method #42
"""
import json
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

from lasr_vm import load_records                            # noqa: E402
from opcode_table import load_names, sections               # noqa: E402

EXE = r"C:\Games\LASR\LASR.exe"
OP_MIN, OP_MAX = 0x01, 0x55

# jump family, from the dispatch-handler grouping (slot 22 is the only handler
# doing a relative add; 23-25 are its conditional siblings in the same group)
JUMPS = {0x17: "JMP", 0x18: "JMP_NE", 0x19: "JMP_EQ", 0x1A: "JMP_EQ2"}
# call-ish opcodes do not branch inside the method
TERMINATORS = {0x16}          # RETURN
SHORTCUTS = {0x3E, 0x3F}      # SHORTCUT_AND / SHORTCUT_OR (modify the JMP after them)

_TABLE = None
_NAMES = None


def table():
    global _TABLE
    if _TABLE is None:
        raw = json.loads((ROOT / "out_w_final.json").read_text())
        _TABLE = {int(k, 16): v for k, v in raw.items()}
        assert set(_TABLE) == set(range(OP_MIN, OP_MAX + 1))
    return _TABLE


def names():
    global _NAMES
    if _NAMES is None:
        d = Path(EXE).read_bytes()
        _NAMES = load_names(d, sections(d))
    return _NAMES


def name_of(op):
    if op == 0x0A:
        return "(reserved)"
    nm = names()
    return nm[84 - op] if 1 <= op <= 0x09 else nm[85 - op]


def load_methods():
    """Load every method as its FULL code: `record blob`, terminator included.

    `lasr_vm.load_records()` requires each record to end with 0x16 and then
    slices it off (`r[:-1]`), which drops the trailing RETURN of *every* method.
    0x16 is a real opcode (RETURN), the container already length-prefixes each
    record, and all 14,796 records end with it - so that byte is the method's
    own trailing RETURN, not a delimiter.  Work on the full blob here.
    """
    out = []
    for cls, idx, body in load_records():
        out.append((cls, idx, body + b"\x16"))
    return out


class Instr:
    __slots__ = ("off", "op", "w", "pay", "name")

    def __init__(self, off, op, w, pay):
        self.off, self.op, self.w, self.pay = off, op, w, pay
        self.name = name_of(op)

    @property
    def signed(self):
        """Payload as a signed 32-bit offset (jump payloads are signed)."""
        if self.pay is None:
            return None
        return self.pay - (1 << 32) if self.pay & 0x80000000 else self.pay

    def __repr__(self):
        extra = "" if self.w == 1 else f" {self.pay:#x} ({self.signed})"
        return f"{self.off:5d}: {self.op:02x} {self.name}{extra}"


def disasm(body):
    """Decompose one method record into instructions.

    The table is exact for all 14,796 records, but stay defensive: on a bad
    opcode or an overrun, stop and report where, rather than emitting garbage.
    """
    W, out, pos, n = table(), [], 0, len(body)
    while pos < n:
        op = body[pos]
        if op < OP_MIN or op > OP_MAX:
            raise ValueError(f"illegal opcode {op:#04x} at {pos}")
        w = W[op]
        if pos + w > n:
            raise ValueError(f"instruction at {pos} runs past end ({w} > {n-pos})")
        pay = struct.unpack_from("<I", body, pos + 1)[0] if w == 5 else None
        out.append(Instr(pos, op, w, pay))
        pos += w
    return out


def jump_target(instr, base):
    """Resolve a jump payload under a named base convention.

    bases: op1 = offset_of_opcode + 1 + payload   (payload relative to operand)
           op0 = offset_of_opcode + payload
           next = offset_of_operand + payload     (same as op1 for our layout)
           abs = payload
    """
    if instr.pay is None:
        return None
    o, p = instr.off, instr.signed
    return {"op1": o + 1 + p, "op0": o + p, "abs": p,
            "op5": o + 5 + p}[base]


def analyse_jump_bases():
    """Score every candidate base by how often targets land on an instruction."""
    recs = load_methods()
    starts, fam = [], defaultdict(list)
    for _, _, body in recs:
        ins = disasm(body)
        st = {i.off for i in ins}
        starts.append(len(ins))
        for i in ins:
            if i.op in JUMPS:
                fam[i.op].append((i, st, len(body)))

    print(f"{len(recs)} methods, {sum(starts):,} instructions\n")
    bases = ("op1", "op0", "abs", "op5")
    print(f"{'opcode':>8} {'n':>6} " + "".join(f"{b:>18}" for b in bases))
    total = Counter()
    for op in sorted(JUMPS):
        row = fam[op]
        cells = []
        for b in bases:
            hit = 0
            for i, st, n in row:
                t = jump_target(i, b)
                if t in st or t == n:          # to instruction start, or method end
                    hit += 1
            cells.append(f"{hit}/{len(row)} ({100*hit/len(row):5.1f}%)")
            total[b] += hit
        print(f"0x{op:02x} {JUMPS[op]:>5} {len(row):>6} " + "".join(f"{c:>18}" for c in cells))
    n_all = sum(len(fam[o]) for o in JUMPS)
    print(f"\n{'ALL':>14} {n_all:>6} "
          + "".join(f"{total[b]}/{n_all} ({100*total[b]/n_all:5.1f}%)".rjust(18)
                    for b in bases))

    # direction breakdown under the winner
    best = max(bases, key=lambda b: total[b])
    fwd = back = oob = 0
    for op in JUMPS:
        for i, st, n in fam[op]:
            t = jump_target(i, best)
            if t < 0 or t > n:
                oob += 1
            elif t <= i.off:
                back += 1
            else:
                fwd += 1
    print(f"\nbest base = {best}: forward {fwd}, backward {back}, out of range {oob}")
    return best


def annotate(body):
    """Disassemble with block labels and resolved jump targets."""
    ins = disasm(body)
    byoff = {i.off: i for i in ins}
    leaders = {0}
    for i in ins:
        if i.op in JUMPS:
            leaders.add(i.off + i.w)
            t = jump_target(i, "op0")
            if t in byoff:
                leaders.add(t)
        elif i.op in TERMINATORS:
            leaders.add(i.off + i.w)

    lines, labels = [], {}
    for k, o in enumerate(sorted(leaders)):
        labels[o] = f"L{k}"
    print(f"method: {len(ins)} instructions, {len(body)} bytes, "
          f"{len(leaders)} blocks")
    for i in ins:
        pre = f"{labels[i.off]:>4}: " if i.off in labels else "      "
        pay = ""
        if i.w == 5:
            if i.op in JUMPS:
                pay = f"  -> {labels.get(jump_target(i, 'op0'), jump_target(i,'op0'))}"
            elif i.op == 0x06:
                f = struct.unpack("<f", struct.pack("<I", i.pay))[0]
                pay = f"  ({i.pay:#x} = {f!r})"
            else:
                pay = f"  ({i.pay})"
        lines.append(f"{pre}{i.off:6d}  {i.op:02x} {i.name:<20}{pay}")
    print("\n".join(lines))


def idiom_census():
    """Count the recognisable control-flow idioms - proof the CFG is usable."""
    recs = load_methods()
    c = Counter()
    wrapper_kinds = Counter()
    for _, _, body in recs:
        ins = disasm(body)
        ops = [i.op for i in ins]
        n = len(ops)
        # trivial accessors: 1-3 instructions
        c["methods total"] += 1
        if n <= 2:
            wrapper_kinds["<=2 instr"] += 1
        elif n <= 4:
            wrapper_kinds["3-4 instr"] += 1
        elif n <= 10:
            wrapper_kinds["5-10 instr"] += 1
        else:
            wrapper_kinds[">10 instr"] += 1
        for a, b in zip(ops, ops[1:]):
            if b == 0x18 and a == 0x46:
                c["if (!cond)  [EXCLAMATION + JMP_NE]"] += 1
            elif b == 0x18:
                c["if (cond)   [JMP_NE]"] += 1
            elif b == 0x1A:
                c["if (cond)   [JMP_EQ2]"] += 1
            elif b == 0x19:
                c["if (cond)   [JMP_EQ]"] += 1
            elif a == 0x3E and b == 0x17:
                c["short-circuit &&  [SHORTCUT_AND + JMP]"] += 1
            elif a == 0x3F and b == 0x17:
                c["short-circuit ||  [SHORTCUT_OR + JMP]"] += 1
            elif a == 0x03 and b in (0x4A, 0x4B):
                c["null compare [NULL LITERAL + IEQ/INE]"] += 1
        for a, b, d in zip(ops, ops[1:], ops[2:]):
            if a == 0x27 and b == 0x2A:
                c["object allocation [NEW + DUP]"] += 1
            if a == 0x0B and b == 0x0B:
                c["chained arg load [LOCAL_LOAD x2]"] += 1
            if a == 0x2A and b == 0x21:
                c["field write on new object [DUP + PUTFIELD]"] += 1
            if b == 0x06 and a == 0x05:
                c["int then float literal (mixed call args)"] += 1
        # early returns
        c["early RETURN (not the last instruction)"] += sum(
            1 for i in ins[:-1] if i.op == 0x16)
    print("=== control-flow idioms ===")
    for k, v in c.most_common():
        print(f"  {k:<46} {v:>8,}")
    print("\n=== method size distribution ===")
    for k in ("<=2 instr", "3-4 instr", "5-10 instr", ">10 instr"):
        print(f"  {k:<46} {wrapper_kinds[k]:>8,}")


def main():
    args = sys.argv[1:]
    if not args or "--jumpbases" in args:
        analyse_jump_bases()
    elif "--stats" in args:
        cfg_stats()
    elif "--idioms" in args:
        idiom_census()
    elif "--list" in args:
        recs = load_methods()
        rows = []
        for k, (cls, m, body) in enumerate(recs):
            ins = disasm(body)
            leaders = {0}
            for i in ins:
                if i.op in JUMPS:
                    leaders.add(i.off + i.w)
                    t = jump_target(i, "op0")
                    if 0 <= t < len(body):
                        leaders.add(t)
                elif i.op in TERMINATORS:
                    leaders.add(i.off + i.w)
            nj = sum(1 for i in ins if i.op in JUMPS)
            rows.append((len(leaders), len(ins), k, cls, m, nj))
        print("by block count (top 8):")
        for nb, ni, k, cls, m, nj in sorted(rows, reverse=True)[:8]:
            print(f"   #{k:<6} {cls}.{m:<6} {nb:>4} blocks {ni:>5} instr {nj:>4} jumps")
        print("\nby instruction count (top 8):")
        for nb, ni, k, cls, m, nj in sorted(rows, key=lambda r: -r[1])[:8]:
            print(f"   #{k:<6} {cls}.{m:<6} {nb:>4} blocks {ni:>5} instr {nj:>4} jumps")
        print("\nsmallest by instruction count (5):")
        for nb, ni, k, cls, m, nj in sorted(rows, key=lambda r: r[1])[:5]:
            print(f"   #{k:<6} {cls}.{m:<6} {nb:>4} blocks {ni:>5} instr {nj:>4} jumps")
    elif "--disasm" in args:
        idx = int(args[args.index("--disasm") + 1])
        cls, m, body = load_methods()[idx]
        print(f"index #{idx}: {cls}.{m}")
        annotate(body)
    else:
        print(__doc__)


def cfg_stats():
    """Per-method CFG: basic blocks, edges, back edges, reachability."""
    recs = load_methods()
    tot_blk = tot_edge = tot_back = 0
    blk_sizes, n_unreach_methods, n_unreach_blk = [], 0, 0
    n_ret_last = n_nonret_last = 0
    loops_hist = Counter()
    op_count = Counter()

    for _, _, body in recs:
        ins = disasm(body)
        byoff = {i.off: i for i in ins}
        byend = {i.off + i.w: i for i in ins}      # end offset -> instruction
        assert ins[-1].op in TERMINATORS, \
            f"method does not end in RETURN: {ins[-1]!r}"
        if ins[-1].op == 0x16:
            n_ret_last += 1
        else:
            n_nonret_last += 1

        # ---- basic block leaders -----------------------------------------
        leaders = {0}
        for i in ins:
            if i.op in JUMPS:
                leaders.add(i.off + i.w)              # fallthrough target
                t = jump_target(i, "op0")
                if t in byoff and t < len(body):
                    leaders.add(t)
            elif i.op in TERMINATORS:
                leaders.add(i.off + i.w)
        leaders = sorted(o for o in leaders if o < len(body))
        blocks = list(zip(leaders, leaders[1:] + [len(body)]))
        tot_blk += len(blocks)
        blk_sizes.append(len(blocks))

        # ---- edges --------------------------------------------------------
        succ = defaultdict(list)
        for s, e in blocks:
            last = byend[e]
            if last.op in JUMPS:
                t = jump_target(last, "op0")
                if t in byoff:
                    succ[s].append(t)
                    tot_edge += 1
                    if t <= last.off:
                        tot_back += 1
                if last.op != 0x17 and e < len(body):   # conditional: fallthrough
                    succ[s].append(e)
                    tot_edge += 1
                elif last.op == 0x17 and e < len(body):
                    # 0x17 JMP is unconditional EXCEPT immediately after
                    # SHORTCUT_AND / SHORTCUT_OR: those peek at the expression
                    # accumulator and only take the jump when the shortcut
                    # fires, otherwise control falls through to the next
                    # instruction.  Treating it as unconditional orphans the
                    # rest of the expression (the source of "unreachable code").
                    prev = byend.get(last.off)
                    if prev is not None and prev.op in SHORTCUTS:
                        succ[s].append(e)
                        tot_edge += 1
            elif last.op in TERMINATORS:
                pass                                    # method exit
            elif e < len(body):
                succ[s].append(e)
                tot_edge += 1

        # ---- reachability --------------------------------------------------
        seen, stack = {0}, [0]
        while stack:
            b = stack.pop()
            for s in succ[b]:
                if s not in seen:
                    seen.add(s)
                    stack.append(s)
        unreach = [b for b in blocks if b[0] not in seen]
        if unreach:
            n_unreach_methods += 1
            n_unreach_blk += len(unreach)

        # ---- loop count from back edges ------------------------------------
        nloops = 0
        for s, e in blocks:
            last = byend[e]
            if last.op in JUMPS:
                t = jump_target(last, "op0")
                if t in byoff and t <= last.off:
                    nloops += 1
        loops_hist[nloops] += 1
        for i in ins:
            op_count[i.op] += 1

    n = len(recs)
    blk_sizes.sort()
    print(f"methods                  : {n:,}")
    print(f"methods ending in RETURN : {n_ret_last:,}  (other: {n_nonret_last})")
    print(f"basic blocks             : {tot_blk:,}  "
          f"(mean {tot_blk/n:.1f}/method, median {blk_sizes[n//2]}, "
          f"max {blk_sizes[-1]})")
    print(f"CFG edges                : {tot_edge:,}  (mean {tot_edge/n:.2f}/method)")
    print(f"back edges (loop latches): {tot_back:,}")
    print(f"methods with unreachable code: {n_unreach_methods:,} "
          f"({n_unreach_blk:,} blocks)")
    print("\nloops per method:")
    for k in sorted(loops_hist):
        if k <= 4:
            print(f"   {k} loops : {loops_hist[k]:>6,} methods")
    print(f"   >4 loops: {sum(v for k, v in loops_hist.items() if k > 4):>6,} methods")


if __name__ == "__main__":
    main()
