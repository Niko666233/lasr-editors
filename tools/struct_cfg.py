"""
Structure the control flow of non-linear methods into indented pseudo-code.

Input side (all already established):

  * `stack_depth.py --export` -> `out_stack_heights.json`: per-method, per-offset
    operand stack height (98.83% of methods fully consistent, underflow 0).
  * `lasr_cfg.py`: instruction boundaries, jump-target base, block leaders.
  * `lift_expr.py`: straight-line expression lifting, per basic block.

Branch semantics, calibrated from the corpus rather than assumed (see
docs/15_CONTROL_FLOW.md):

  * `0x17 JMP`      - unconditional, EXCEPT right after SHORTCUT_AND/OR, where it
                      fires only when the shortcut fires (else fall through).
  * `0x18 JMP_NE`   - pops 1; jumps when the popped value is 0 (false).  Proof:
                      in all 545 loops the head's exit branch is `0x18` (539 of
                      them) right after a comparison, and the 17 cases whose
                      condition is `BOOL LITERAL 1` are `while (true)`.
  * `0x19 JMP_EQ`   - the opposite sense: jumps when the popped value is non-zero.
  * `0x1a JMP_EQ2`  - pops the just-pushed constant and keeps the value below it;
                      jumps when they are equal.  Chains of them are `switch`.

Shapes the emitter recognises: sequence, if-then, if-then-else, while, do-while,
`break`/`continue`, `switch` and `&&`/`||` (rendered as nested ifs, which is what
the short circuit means).  Anything else degrades to an explicit `goto Lnn`, and
the degradation is counted instead of hidden.

Usage:
  python tools/struct_cfg.py --method 42
  python tools/struct_cfg.py --class extracted/java/classes/game/Bet.class
  python tools/struct_cfg.py --dump            # whole corpus -> out_pseudo/
  python tools/struct_cfg.py --report          # structuring statistics
"""
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

from lasr_cfg import disasm, JUMPS, jump_target, name_of     # noqa: E402
from lasr_named import load_methods_meta, class_name         # noqa: E402
import lift_expr as LX                                       # noqa: E402
import stack_depth as SD                                     # noqa: E402

UNCOND, RET = 0x17, 0x16
COND = {0x18: "ne", 0x19: "eq"}          # jump-if-false / jump-if-true
SWITCH = 0x1A
SHORTCUTS = {0x3E, 0x3F}
MAX_ITER = 12


# ---------------------------------------------------------------------------
# blocks
class Block:
    __slots__ = ("start", "ins", "end", "last", "kind", "succ", "peek", "short_jump")

    def __init__(self, start, ins, end):
        self.start, self.ins, self.end = start, ins, end
        self.last = ins[-1]
        self.kind, self.succ, self.short_jump = "fall", [], None
        k = self.last.op
        if k == RET:
            self.kind = "ret"
        elif k in COND:
            self.kind = "cond"
        elif k == SWITCH:
            self.kind = "switch"
        elif k == UNCOND:
            self.kind = "uncond"
        self.peek = (len(ins) > 1 and ins[-2].op in SHORTCUTS)

    def __repr__(self):
        return f"B{self.start}[{self.kind}]{len(self.ins)}i"


def build_blocks(ins):
    byoff = {i.off: i for i in ins}
    leaders = {0}
    for i in ins:
        if i.op in JUMPS:
            leaders.add(i.off + i.w)
            t = jump_target(i, "op0")
            if 0 <= t <= ins[-1].off + ins[-1].w:
                leaders.add(t)
        elif i.op == RET:
            leaders.add(i.off + i.w)
    leaders = sorted(o for o in leaders if 0 <= o <= ins[-1].off + ins[-1].w)
    blocks, idx = [], {}
    for n, s in enumerate(leaders):
        e = leaders[n + 1] if n + 1 < len(leaders) else ins[-1].off + ins[-1].w
        part = [i for i in ins if s <= i.off < e]
        if not part:
            continue
        b = Block(s, part, e)
        blocks.append(b)
        idx[s] = b
    # successors
    for b in blocks:
        last = b.last
        if b.kind == "ret":
            continue
        if last.op in JUMPS:
            t = jump_target(last, "op0")
            if last.op == UNCOND:
                if b.peek:
                    # `SHORTCUT_AND/OR; JMP T`: the jump and the fallthrough both
                    # land where the combined boolean is consumed, with the same
                    # stack (the value is peeked, not popped), so the block is
                    # transparent - keep the edge for verification only.
                    b.short_jump = t
                    b.kind = "fall"
                    b.succ = [b.end]
                else:
                    b.succ = [t]
                    b.kind = "uncond"
            else:
                b.succ = [t, b.end]              # taken, fallthrough
        elif b.kind == "fall":
            b.succ = [b.end]
    return blocks, idx, byoff


# ---------------------------------------------------------------------------
# per-block lifting + stack dataflow
def lift_block(instrs, entry, pool, by_owner, meta, by_name, desc, flags):
    """Run the lifter over one block from a given entry stack.

    Returns (statements, exit_stack).  The entry stack is consumed, so pass a copy.
    """
    lf = LX.Lifter(pool, by_owner, meta, by_name)
    lf.setup(desc, flags)
    lf.stack = list(entry)
    stmts = lf.run_ins(instrs)
    return stmts, lf.stack, lf


def align(stack, want):
    """Snap a symbolic stack to the height the abstract interpreter reports.

    `out_stack_heights.json` is the authoritative height per instruction, so a
    surplus (my model pushed something the VM did not) is dropped from the top
    and a shortfall is padded at the bottom.  Without this, joining a taller
    incoming stack with a shorter one grows the stack block after block and the
    expressions at joins come out wrong.
    """
    if want is None:
        return list(stack)
    if len(stack) > want:
        return list(stack[:want])
    if len(stack) < want:
        return [LX.E("<?>")] * (want - len(stack)) + list(stack)
    return list(stack)


def merge(a, b):
    """Join two entry stacks of equal height: first-seen wins, count the rest.

    Heights come from the height map, so they agree except at the handful of
    known compiler-dead slots; aligning from the bottom (the older values) is
    what keeps the shared part of the expression stable.
    """
    if len(a) != len(b):
        n = max(len(a), len(b))
        pad = lambda xs: [LX.E("<?>")] * (n - len(xs)) + list(xs)   # noqa: E731
        a, b = pad(a), pad(b)
    out, diff = [], 0
    for x, y in zip(a, b):
        if x is None:
            out.append(y)
        elif y is None or (x.txt == y.txt and x.ty == y.ty):
            out.append(x)
        else:
            diff += 1
            out.append(x)
    return out, diff


class Method:
    def __init__(self, path, k, rec, pool, ar, nl, heights):
        self.path, self.k, self.rec, self.pool = path, k, rec, pool
        self.ar, self.nl = SD.ret_arity(pool.utf8(_meta_of(path)[k][2])
                                        if k in _meta_of(path) else "()V"), nl
        self.ins = disasm(rec)
        self.blocks, self.idx, self.byoff = build_blocks(self.ins)
        self.heights = {int(o): h for o, h in heights.items()}
        self.meta = _meta_of(path)
        m = self.meta.get(k)
        self.desc = pool.utf8(m[2]) if m else "()V"
        self.ar = SD.ret_arity(self.desc)
        self.flags = m[0] if m else 0
        self.name = pool.utf8(m[1]) if m else "?"
        global FIELDS
        if FIELDS is None:
            FIELDS = LX.fields_index()
        self.by_owner, self.by_name = FIELDS
        self.entry = {}
        self.stats = Counter()
        self.conflicts = 0

    # -- dataflow -----------------------------------------------------------
    def run_dataflow(self):
        start = 0
        self.entry[start] = []
        work = [start]
        seen_iter = Counter()
        while work:
            s = work.pop(0)
            seen_iter[s] += 1
            if seen_iter[s] > MAX_ITER:
                self.stats["no_fixpoint"] += 1
                continue
            b = self.idx.get(s)
            if b is None:
                continue
            stmts, exit_stack, _ = lift_block(
                b.ins, self.entry[s], self.pool, self.by_owner, self.meta,
                self.by_name, self.desc, self.flags)
            for t in b.succ:
                if t not in self.idx:
                    continue
                exit_stack = align(exit_stack,
                                   self.heights.get(self.idx[t].ins[0].off))
                if t not in self.entry:
                    self.entry[t] = list(exit_stack)
                    work.append(t)
                else:
                    merged, diff = merge(self.entry[t], exit_stack)
                    self.conflicts += diff
                    if diff:
                        self.stats["merge_conflicts"] += 1
                        self.entry[t] = merged
                        work.append(t)
        # Independent check, only after the fixpoint: the structurer's own stack
        # model against the abstract interpreter's height map (out_stack_heights).
        for b in self.blocks:
            want = self.heights.get(b.ins[0].off)
            if want is None:
                continue
            got = len(self.entry.get(b.start, []))
            if want != got:
                self.stats["height_disagreement"] += 1


_CHUNK_CACHE = {}
_META_CACHE = {}
FIELDS = None


def _chunks_of(path):
    if path not in _CHUNK_CACHE:
        from lasr_vm import chunks
        _CHUNK_CACHE[path] = chunks(Path(path).read_bytes())
    return _CHUNK_CACHE[path]


def _meta_of(path):
    if path not in _META_CACHE:
        _META_CACHE[path] = load_methods_meta(_chunks_of(path))
    return _META_CACHE[path]


# ---------------------------------------------------------------------------
# emission
class Emitter:
    def __init__(self, m):
        self.m = m
        self.lines = []
        self.visited = set()
        self.emitted_edges = Counter()
        self.fallbacks = 0
        self.err = None
        self.indent = 0
        self.max_indent = 0
        self.overrides = {}          # block start -> entry stack with a folded value

    def line(self, text, ind=None):
        i = self.indent if ind is None else ind
        self.lines.append("    " * i + text)

    def goto(self, target):
        self.fallbacks += 1
        self.line(f"goto L{target};")

    def end_of(self, off):
        b = self.m.idx.get(off)
        return b.end if b else None

    def last_block_before(self, off):
        """The block whose instruction range ends exactly at `off`."""
        for b in self.m.blocks:
            if b.end == off:
                return b
        return None

    def entry_of(self, b):
        return self.overrides.get(b.start, self.m.entry.get(b.start, []))

    def dry_value(self, start, stop, join_ok=None):
        """Walk a straight region and report (n_statements, top-of-stack).

        A value diamond (ternary) is a region that only *pushes* a value: no
        statements at all on either arm.  Anything else returns n > 0 and the
        caller falls back to the ordinary if/else rendering.
        """
        stmts_n, stack, b = 0, None, self.m.idx.get(start)
        guard = 0
        while b is not None and b.start != stop and guard < 64:
            guard += 1
            body = b.ins[:-1] if b.kind != "fall" else b.ins
            st, stack, _ = lift_block(body, self.entry_of(b), self.m.pool,
                                      self.m.by_owner, self.m.meta, self.m.by_name,
                                      self.m.desc, self.m.flags)
            stmts_n += len([x for x in st if x.get("target") not in (None, "return")])
            if b.kind == "fall":
                b = self.m.idx.get(b.succ[0]) if b.succ else None
                continue
            if b.kind == "uncond" and b.succ and b.succ[0] == stop:
                return stmts_n, (stack[-1] if stack else None)
            if b.kind == "uncond" and join_ok is not None and b.succ and b.succ[0] == join_ok:
                return stmts_n, (stack[-1] if stack else None)
            return stmts_n + 1, None
        if b is not None and b.start == stop:
            return stmts_n, (stack[-1] if stack else None)
        return stmts_n + 1, None

    def emit(self):
        try:
            self.region(0, None, None)
        except Exception:                              # noqa: BLE001
            import traceback
            self.err = traceback.format_exc(limit=4).strip().splitlines()[-1]
            self.trace = traceback.format_exc(limit=40)
        if self.indent != 0:
            self.err = (self.err or "") + f" unbalanced indent {self.indent}"
        # Safety net: never drop code silently.  Anything the structuring walk did
        # not reach is listed with its raw instructions so a reader can see it.
        left = [b for b in self.m.blocks if b.start not in self.visited]
        if left:
            self.line("")
            self.line(f"// ---- {len(left)} block(s) not reached by the structuring "
                      f"walk (compiler-dead or unreachable) ----")
            for b in left:
                txt = " | ".join(
                    f"{i.op:02x}:{name_of(i.op)}" + (f"({i.pay})" if i.pay is not None else "")
                    for i in b.ins)
                self.line(f"// B{b.start} [{b.kind}] {txt}")
        return self.lines

    # -- one region ---------------------------------------------------------
    def region(self, start, stop, loop, cont=None):
        b = self.m.idx.get(start)
        while b is not None:
            if stop is not None and b.start == stop:
                if b.start not in self.visited:
                    pass
                self.emitted_edges[(start, stop)] += 1
                return
            if b.start in self.visited:
                self.stats_double(b)
                return
            self.visited.add(b.start)
            nxt = self.block(b, stop, loop, cont)
            if nxt is None:
                return
            b = self.m.idx.get(nxt)

    def stats_double(self, b):
        self.m.stats["block_revisited"] += 1

    def block(self, b, stop, loop, cont=None):
        """Emit one block; return the offset to continue from, or None.

        `cont` is the continuation a region exits to: a jump landing there ends
        the region silently instead of degrading to a `goto`.
        """
        body = b.ins[:-1] if (b.kind != "fall" and len(b.ins) > 1) else b.ins
        if b.kind == "ret":
            body = b.ins[:-1]
        stmts, _, lf = lift_block(body, self.entry_of(b),
                                  self.m.pool, self.m.by_owner, self.m.meta,
                                  self.m.by_name, self.m.desc, self.m.flags)
        self.emit_stmts(stmts)
        if b.kind == "ret":
            top = lf.stack[-1].txt if (lf.stack and hasattr(lf.stack[-1], "txt")) else ""
            if self.m.ar and top:
                self.line(f"return {top};")
            else:
                self.line("return;")
            return None
        if b.kind == "fall":
            return b.succ[0] if b.succ else None
        if b.kind == "uncond":
            t = b.succ[0]
            if t == stop or t == cont:
                return None
            if loop and t == loop["head"] and self.next_after(b.start) == loop["exit"]:
                return None                     # the latch of the loop, implicit
            if loop and t == loop["head"]:
                self.line("continue;")
                return None
            if loop and t == loop["exit"]:
                self.line("break;")
                return None
            if t < b.start:                     # backward jump, not a loop latch
                self.goto(t)
                return None
            self.goto(t)
            return None
        if b.kind == "cond":
            return self.emit_cond(b, stop, loop, cont)
        if b.kind == "switch":
            return self.emit_switch(b, stop, loop, cont)
        return None

    # -- conditionals -------------------------------------------------------
    def cond_text(self, b, lf):
        """The value this branch tests, plus whether the branch pops it."""
        if not lf.stack or not hasattr(lf.stack[-1], "txt"):
            return "<stack-empty>"
        return lf.stack[-1].txt

    def emit_cond(self, b, stop, loop, cont=None):
        taken, fall = b.succ[0], b.succ[1]
        stmts, _, lf = lift_block(b.ins[:-1], self.entry_of(b),
                                  self.m.pool, self.m.by_owner, self.m.meta,
                                  self.m.by_name, self.m.desc, self.m.flags)
        cond = self.cond_text(b, lf)
        taken_is_false = (b.last.op == 0x18) and not b.peek
        self.emitted_edges[(b.start, taken)] += 1

        # ---- loop header (a back edge lands here) ---------------------------
        if b.start in self.loop_headers():
            target = taken if taken > fall else fall
            if taken > fall:
                # `while (cond) { body }` with the exit taken on false
                kw = "while" if taken_is_false else "while (!"
                txt = f"{kw} ({cond})" if taken_is_false else f"while (!({cond}))"
                self.line(f"{txt} {{")
                self.indent += 1
                self.max_indent = max(self.max_indent, self.indent)
                self.region(fall, taken, {"head": b.start, "exit": taken}, cont)
                self.indent -= 1
                self.line("}")
                return taken
            # `do { body } while (cond)` - the latch is a conditional backward jump
            self.line("do {")
            self.indent += 1
            self.max_indent = max(self.max_indent, self.indent)
            self.region(fall, b.start, {"head": b.start, "exit": taken}, cont)
            self.indent -= 1
            self.line(f"}} while ({cond if taken_is_false else '!(' + cond + ')'});")
            return taken

        # ---- plain conditional ---------------------------------------------
        then_join = taken
        else_start = None
        join = taken
        if taken > b.start and fall < taken:
            # the then-region [fall, taken); if it ends with JMP J > taken it is an else
            lb = self.last_block_before(taken)
            if lb is not None and lb.kind == "uncond" and lb.succ:
                j = lb.succ[0]
                if j > taken and (stop is None or j <= stop or j > stop):
                    else_start, join = taken, j
        if b.peek:
            self.m.stats["shortcut_block"] += 1
            # A shortcut block is transparent (see build_blocks): its jump and its
            # fallthrough meet where the combined boolean is consumed with the same
            # stack, so there is nothing to branch on here.
            return b.succ[0]
        if else_start is not None:
            # Value diamond -> ternary: both arms only push a value.
            n_then, v_then = self.dry_value(fall, else_start, join_ok=join)
            n_else, v_else = self.dry_value(else_start, join, join_ok=join)
            if (n_then == 0 and n_else == 0 and v_then is not None
                    and v_else is not None and join is not None):
                # The branch pops its condition and each arm pushes exactly one
                # value, so the join's stack is `exit-stack-minus-condition` plus
                # the ternary - and every later block is re-lifted from that.
                entry = list(lf.stack[:-1]) if lf.stack else []
                entry.append(LX.E(
                    f"(({cond}) ? ({v_then.txt}) : ({v_else.txt}))",
                    v_then.ty if v_then.ty == v_else.ty else "?"))
                self.overrides[join] = entry
                self.visited.add(fall)
                self.visited.add(else_start)
                self.m.stats["ternary"] += 1
                return join
        if then_join == stop:
            self.line(f"if ({cond}) {{")
            self.indent += 1
            self.max_indent = max(self.max_indent, self.indent)
            self.region(fall, then_join, loop, cont)
            self.indent -= 1
            self.line("}")
        elif else_start is not None:
            self.line(f"if ({cond if taken_is_false else '!(' + cond + ')'}) {{")
            self.indent += 1
            self.max_indent = max(self.max_indent, self.indent)
            self.region(fall, else_start, loop, join)
            self.indent -= 1
            self.line("} else {")
            self.indent += 1
            self.max_indent = max(self.max_indent, self.indent)
            self.region(else_start, join, loop, cont)
            self.indent -= 1
            self.line("}")
        else:
            self.line(f"if ({cond if taken_is_false else '!(' + cond + ')'}) {{")
            self.indent += 1
            self.max_indent = max(self.max_indent, self.indent)
            self.region(fall, then_join, loop, cont)
            self.indent -= 1
            self.line("}")
        return join

    # -- switch -------------------------------------------------------------
    def emit_switch(self, b, stop, loop, cont=None):
        cases, cur, subj = [], b, "?"
        while cur is not None and cur.kind == "switch":
            st, stack, _ = lift_block(cur.ins[:-1], self.entry_of(cur),
                                      self.m.pool, self.m.by_owner, self.m.meta,
                                      self.m.by_name, self.m.desc, self.m.flags)
            const = stack[-1].txt if (stack and hasattr(stack[-1], "txt")) else "?"
            if not cases:
                # JMP_EQ2 keeps the value below the constant, so the switch
                # subject is the second slot after the chain's first block is
                # lifted - it may have been pushed inside that very block.
                if len(stack) >= 2 and hasattr(stack[-2], "txt"):
                    subj = stack[-2].txt
            cases.append((const, cur.succ[0]))
            self.visited.add(cur.start)
            cur = self.m.idx.get(cur.succ[1])
        default_start = cur.start if cur is not None else None
        bodies = [t for _, t in cases]
        if default_start is not None:
            bodies.append(default_start)
        joins = Counter()
        for t in bodies:
            lb = self.last_block_before(self.next_after(t))
            if lb is not None and lb.kind == "uncond":
                joins[lb.succ[0]] += 1
        join = None
        inner_stops = {t2 for _, t2 in cases}
        for t, n in joins.most_common(1):
            if t in inner_stops:
                continue
            if n >= 2 or (n == len(bodies) and len(bodies) >= 1):
                join = t
        end = join if join is not None else stop
        one_case = len(cases) == 1
        if one_case:
            self.line(f"if ({subj} == {cases[0][0]}) {{")
        else:
            self.line(f"switch ({subj}) {{")
        self.indent += 1
        self.max_indent = max(self.max_indent, self.indent)
        for const, t in cases:
            if not one_case:
                self.line(f"case {const}:")
                self.indent += 1
            self.region(t, end, loop, cont)
            if one_case:
                pass
            elif not self.terminated():
                self.line("break;")
            if not one_case:
                self.indent -= 1
        if default_start is not None:
            if one_case:
                self.indent -= 1
                self.line("} else {")
                self.indent += 1
            else:
                self.line("default:")
                self.indent += 1
            self.region(default_start, end, loop, cont)
            if not one_case:
                self.indent -= 1
        self.indent -= 1
        self.line("}")
        return join if join is not None else stop

    def terminated(self):
        """Did the last emitted line end the current region with a hard exit?"""
        for l in reversed(self.lines):
            s = l.strip()
            if not s:
                continue
            return s.startswith("return") or s.startswith("break") or s.startswith("continue")
        return False

    def next_after(self, off):
        for b in self.m.blocks:
            if b.start > off:
                return b.start
        return None

    _lh = None

    def loop_headers(self):
        if self._lh is None:
            lh = set()
            for b in self.m.blocks:
                for t in b.succ:
                    if t <= b.start:
                        lh.add(t)
            self._lh = lh
        return self._lh

    def emit_stmts(self, stmts):
        for s in stmts:
            t = s.get("target")
            e = s.get("expr") or ""
            if t is None:
                # A discarded value is only interesting when it is a call: those
                # have side effects (`System.log(...)`).  Plain literals would
                # just be noise, so keep only call-shaped expressions.
                if "(" in e and e.rstrip().endswith(")"):
                    self.line(f"{e};")
                continue
            if t == "return":
                continue
            self.line(f"{t} = {e};")


# ---------------------------------------------------------------------------
def one_method(m, verbose=False):
    m.run_dataflow()
    em = Emitter(m)
    lines = em.emit()
    return em, lines


EXTRACTED = ROOT / "extracted"


def height_key(f, k):
    """Heights are exported keyed relative to extracted/ (see stack_depth.export)."""
    return f"{f.relative_to(EXTRACTED).as_posix()}#{k}"


def load_heights():
    return json.loads((ROOT / "out_stack_heights.json").read_text())


def method_for(path, k, H=None):
    f = Path(path)
    if not f.is_absolute():
        f = ROOT / f
    ck = _chunks_of(f)
    from lasr_vm import tree_records
    from resolve_pool import Pool
    pool = Pool(ck["CONS"][0])
    recs = [r for r in tree_records(ck["TREE"][0]) if r and r[-1] == 0x16]
    rec = recs[k]
    h = (H if H is not None else load_heights()).get(height_key(f, k), {}).get("h", {})
    return Method(f, k, rec, pool, 0, 0, h)


def show_method(path, k):
    m = method_for(path, k)
    # header
    cls = class_name(m.pool, 0)
    print(f"// {cls}.{m.name}{m.desc}")
    em, lines = one_method(m)
    for l in lines:
        print(l)
    if em.err:
        print(f"// !! {em.err}")
    print(f"// blocks {len(m.blocks)} visited {len(em.visited)} "
          f"fallbacks {em.fallbacks} conflicts {m.conflicts} "
          f"edges {sum(em.emitted_edges.values())}")


def dump(outdir="out_pseudo", only=None):
    """Write every method's structured pseudo-code under out_pseudo/."""
    out = ROOT / outdir
    H = load_heights()
    per_class = defaultdict(list)
    tally = Counter()
    for f, k, rec, pool, ar, nl in SD.corpus():
        if only and only not in f.as_posix():
            continue
        info = H.get(height_key(f, k))
        if info is None:
            continue
        try:
            m = Method(f, k, rec, pool, ar, nl, info["h"])
            em, lines = one_method(m)
        except Exception as exc:                        # noqa: BLE001
            tally["exception"] += 1
            continue
        cls = class_name(pool, 0)
        hdr = [f"    // {cls}.{m.name}{m.desc}"
               + ("" if info["ok"] else "   [stack analysis failed: "
                  + str(info.get("fail")) + "]")]
        per_class[f.relative_to(EXTRACTED).with_suffix(".java")] += hdr + lines + [""]
        tally["methods"] += 1
        tally["lines"] += len(lines)
        if em.err:
            tally["errors"] += 1
    for rel, lines in per_class.items():
        p = out / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("\n".join(lines), encoding="utf-8")
    print(f"classes written : {len(per_class):,}  -> {outdir}/")
    for k, v in tally.most_common():
        print(f"   {k:<14} {v:,}")
    tot = sum(p.stat().st_size for p in out.rglob("*.java"))
    print(f"total           : {tot/1e6:.1f} MB")


def main():
    a = sys.argv[1:]
    if not a:
        print(__doc__)
        return
    LX.PARENTS = LX.load_parents()
    if "--dump" in a:
        only = a[a.index("--dump") + 1] if len(a) > a.index("--dump") + 1 else None
        return dump(only=only)
    if "--method" in a:
        return show_method_paths(a[a.index("--method") + 1])
    if "--class" in a:
        p = Path(a[a.index("--class") + 1])
        f = p if p.is_absolute() else ROOT / p
        H = load_heights()
        for k, rec in enumerate([r for r in _recs(f) if r and r[-1] == 0x16]):
            show_method(f, k)
            print()
        return
    if "--report" in a:
        return report()
    print(__doc__)


def _recs(f):
    from lasr_vm import tree_records
    return tree_records(_chunks_of(f)["TREE"][0])


def show_method_paths(spec):
    if "#" in spec:
        path, k = spec.rsplit("#", 1)
        return show_method(path, int(k))
    p = Path(spec)
    f = p if p.is_absolute() else ROOT / p
    for k in range(len([r for r in _recs(f) if r and r[-1] == 0x16])):
        show_method(f, k)
        print()


def report(limit=None):
    """Structure every method and report the honest success rate."""
    H = load_heights()
    tally = Counter()
    bad = []
    for n, (f, k, rec, pool, ar, nl) in enumerate(SD.corpus()):
        key = height_key(f, k)
        info = H.get(key)
        if info is None:
            tally["no height data"] += 1
            continue
        try:
            m = Method(f, k, rec, pool, ar, nl, info["h"])
            em, lines = one_method(m)
        except Exception as exc:                        # noqa: BLE001
            tally["exception"] += 1
            if len(bad) < 10:
                bad.append((key, f"{type(exc).__name__}: {exc}"))
            continue
        tally["methods"] += 1
        if em.err:
            tally["emitter error"] += 1
            if len(bad) < 10:
                bad.append((key, em.err))
            continue
        if not any("goto L" in l for l in lines):
            tally["clean (no goto)"] += 1
        else:
            tally["with goto fallback"] += 1
        if info["ok"]:
            tally["height-consistent"] += 1
        if m.conflicts:
            tally["merge conflicts"] += 1
        if m.stats.get("height_disagreement") and info["ok"]:
            tally["height disagreements (consistent methods)"] += 1
        unvis = [b.start for b in m.blocks if b.start not in em.visited]
        if unvis:
            tally["unvisited blocks"] += len(unvis)
        if limit and n >= limit:
            break
    tally["blocks emitted"] = 0
    for k, v in tally.most_common():
        print(f"  {k:<26} {v:>8,}")
    if bad:
        print("\n示例失败:")
        for key, e in bad:
            print(f"   {key}: {e}")


if __name__ == "__main__":
    main()
