"""
Lift straight-line method bodies back into assignment statements.

The stack heights (tools/stack_depth.py) plus the constant pool (docs/10) are
enough to rebuild expressions: walk the instructions once keeping a symbolic
stack of expression nodes, and every store turns into an assignment.

Scope is deliberately the **straight-line** case - no branches - because that is
where the game's numbers live: all 1,199 field initialisers (`<clinit>` and the
compiler's `<i>`) are branch-free, and they are exactly the `static final`
constants and tuning tables a remake has to reproduce.

The lift is checked against the field declarations, which is an independent
second judgement that has nothing to do with the stack simulation: the type of
each reconstructed expression must match the declared type of the field it is
stored into (an `F` field must receive a float expression, a `[I` field an array
expression, and so on).  A mis-lifted expression shows up as a type clash.

Usage:
  python tools/lift_expr.py --class extracted/java/classes/game/Bet.class
  python tools/lift_expr.py --dump        # whole corpus -> out_init.json
  python tools/lift_expr.py --report      # readable initialiser listing
"""
import json
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

from lasr_vm import chunks                                    # noqa: E402
from lasr_cfg import disasm, name_of, JUMPS, jump_target      # noqa: E402
from resolve_pool import Pool                              # noqa: E402
from lasr_named import load_methods_meta, ref_text, class_name  # noqa: E402
import stack_depth as SD                                      # noqa: E402

# Integer constants at or above this are constant-pool indices with this bias:
# the compiler encodes an embedded class/field/string constant as
# `0x20000000 + pool_index`.  See docs/14_CAR_DATA.md.
HEAP_BASE = 0x20000000

# ---------------------------------------------------------------------------
# type helpers.  Types are kept as JVM descriptors throughout ('I', 'F',
# 'Ljava.lang.String;', '[I', '[Ljava.game.Bet;'); 'S' is the VM's unified
# numeric type (SADD/SMUL...), which may flow into either an I or an F field,
# and '?' means "not determined".
NUM = {"S"}
# {class: superclass}, filled from every class's CLSS block: field 3 is the
# parent reference (docs/11).  Used so that a subclass instance stored into a
# superclass-typed field counts as a match instead of a clash.
PARENTS = {}


def load_parents():
    """Build PARENTS from all class files' CLSS parent references."""
    import struct
    out = {}
    for f in (ROOT / "extracted").rglob("*.class"):
        try:
            ck = chunks(f.read_bytes())
            pool = Pool(ck["CONS"][0])
        except Exception:
            continue
        cls = pool.utf8(0)
        clss = ck.get("CLSS")
        if not (cls and clss and len(clss[0]) >= 16):
            continue
        sup = pool.ref(struct.unpack_from("<I", clss[0], 12)[0])
        if sup:
            out[cls] = sup[0]
    return out


def desc_ok(u, t):
    """Can an expression typed `u` be stored into a field typed `t`?"""
    if u == t:
        return True
    if u in ("?", "") or t in ("?", ""):
        return None                      # undecidable - not counted either way
    if u in NUM and t in ("I", "F", "C", "Z", "B", "S"):
        return True
    if u == "null" and (t.startswith("L") or t.startswith("[")):
        return True
    if u == "array" and t.startswith("["):
        return True
    if u == "I" and t in ("C", "Z", "B", "S"):
        return True                      # int flows into the narrow int types
    if u == "Z" and t in ("I", "S", "C", "B"):
        return True                      # this VM has one integer type: bool is int
    if PARENTS:                          # u may be a subclass of t
        if u.startswith("L") and t.startswith("L"):
            seen, cur = set(), u[1:-1]
            while cur in PARENTS and cur not in seen:
                if cur == t[1:-1]:
                    return True
                seen.add(cur)
                cur = PARENTS[cur]
    return False


BIN_SYM = {
    0x2E: "+", 0x2F: "+", 0x30: "+", 0x31: "-", 0x32: "-", 0x33: "/",
    0x34: "/", 0x35: "*", 0x36: "*", 0x3D: "%",
    0x40: "&&", 0x41: "||", 0x42: "&", 0x43: "|", 0x44: "^",
    0x47: ">>", 0x48: "<<", 0x49: ">>>",
    0x4A: "==", 0x4B: "!=", 0x4C: ">", 0x4D: ">=", 0x4E: "<", 0x4F: "<=",
    0x50: "==", 0x51: "!=", 0x52: ">", 0x53: ">=", 0x54: "<", 0x55: "<=",
}
CMP = {0x4A, 0x4B, 0x4C, 0x4D, 0x4E, 0x4F, 0x50, 0x51, 0x52, 0x53, 0x54, 0x55,
       0x40, 0x41, 0x42, 0x43, 0x44}
FLOATY = {0x30, 0x32, 0x34, 0x36, 0x38, 0x50, 0x51, 0x52, 0x53, 0x54, 0x55}
CONV = {0x1B: "I", 0x1C: "F", 0x1D: "S", 0x1E: "S"}          # F2I I2F I2S F2S
UN_SYM = {0x37: "-", 0x45: "~", 0x46: "!"}

# `NEWARRAY <pool index>` points at the *element class* in this class's own
# constant pool (not a global type code): resolved through `class_name`, the
# resulting array type matches the declared type of the field it is stored into
# in 550/550 cases, which is what makes this reading safe.


class E:
    """An expression node.  `txt` renders it, `ty` is its JVM descriptor."""
    __slots__ = ("txt", "ty", "array_of")

    def __init__(self, txt, ty="?", array_of=None):
        self.txt, self.ty, self.array_of = txt, ty, array_of

    def __repr__(self):
        return self.txt


def param_types(desc):
    """('(ILjava.lang.String;)V') -> ['I', 'Ljava.lang.String;']"""
    if not desc.startswith("("):
        return []
    end = desc.index(")")
    out, i = [], 1
    while i < end:
        c = desc[i]
        if c == "[":
            j = i + 1
            while j < end and desc[j] == "[":
                j += 1
            if j < end and desc[j] == "L":
                j = desc.index(";", j)
            out.append(desc[i:j + 1])
            i = j + 1
        elif c == "L":
            j = desc.index(";", i)
            out.append(desc[i:j + 1])
            i = j + 1
        else:
            out.append(c)
            i += 1
    return out


def split_ref(ref):
    """`java.game.Bet.betPart Ljava.game.item.IPart;` -> (owner, name, desc).

    Splitting on the last dot is wrong: descriptors contain dots
    (`Ljava.game.item.IPart;`), so `rsplit(".", 1)` mangles the name.
    """
    head, _, desc = ref.partition(" ")
    owner, _, name = head.rpartition(".")
    return owner, name, desc


def lit(kind, pay):
    if kind == 0x03:
        return E("null", "null")
    if kind == 0x04:
        return E("true" if pay else "false", "Z")
    if kind == 0x05:
        v = pay - (1 << 32) if pay & 0x80000000 else pay
        return E(str(v), "I")
    if kind == 0x06:
        return E(repr(round(struct.unpack("<f", struct.pack("<I", pay))[0], 6)), "F")
    if kind == 0x07:
        return E(repr(chr(pay & 0xFFFF)), "C")
    if kind == 0x09:
        return E(f"RID#{pay}", "?")      # never emitted in this corpus


class Lifter:
    def __init__(self, pool, fields, meta, fields_by_name=None):
        self.linear = True
        self.locals = {}
        self.underflow_sites = []
        self.pool, self.fields, self.meta = pool, fields, meta
        self.fields_by_name = fields_by_name or {}
        self.stack = []
        self.stmts = []
        self.stats = Counter()
        self.clashes = []

    # -- stack helpers ------------------------------------------------------
    def pop(self, what="value"):
        if not self.stack:
            self.stats["underflow"] += 1
            if len(self.underflow_sites) < 5:
                self.underflow_sites.append((self.cur_off, self.cur_name, what))
            return E(f"<{what}?>")
        return self.stack.pop()

    def push(self, e):
        self.stack.append(e)

    def field_ty(self, owner, name):
        t = self.fields.get((owner, name))
        if t is None:
            t = self.fields_by_name.get(name)
        return t or "?"

    def store(self, target, ty, value, owner=None, name=None):
        inferred = self.field_ty(owner, name) if name else ty or "?"
        ok = desc_ok(value.ty, inferred)
        self.stats["stores"] += 1
        if ok is True:
            self.stats["type_match"] += 1
        elif ok is False:
            self.stats["type_clash"] += 1
            self.clashes.append((target, value.txt, value.ty, inferred))
        else:
            self.stats["type_undecided"] += 1
        self.stmts.append({"target": target, "expr": value.txt,
                           "expr_type": value.ty, "field_type": inferred,
                           "match": ok})

    # -- one method ---------------------------------------------------------
    def setup(self, desc, flags=0):
        """Type the locals from the descriptor (the only source that names them)."""
        is_static = bool(flags & 8)
        slot = 0
        if not is_static:
            self.locals[0] = "L" + self.pool.utf8(0) + ";"
            slot = 1
        for ty in param_types(desc):
            self.locals[slot] = ty
            slot += 1
        self.cur_off, self.cur_name = None, None

    def run_ins(self, ins):
        """Lift one instruction list (a basic block) from the current stack."""
        for i in ins:
            self.cur_off, self.cur_name = i.off, name_of(i.op)
            self.step(i, ins)
        if self.stats["underflow"]:
            self.stats["leftover"] = len(self.stack)
        return self.stmts

    def run(self, rec, desc, flags=0, n_locals=0):
        ins = disasm(rec)
        self.linear = not any(i.op in JUMPS for i in ins)
        # The descriptor already types the locals: local0 is `this` for an
        # instance method, then the parameters in order.  Nothing else in the
        # class file names locals, so this is the only source of types for them.
        self.setup(desc, flags)
        return self.run_ins(ins)

    def step(self, i, ins):
        op, pay = i.op, i.pay
        P = self.pool
        if op in (0x03, 0x04, 0x05, 0x06, 0x07, 0x09):
            e = lit(op, pay)
            # Integer constants above HEAP_BASE (0x20000000) are pool indices
            # with that bias - a `paintjobIDs` element of 536870989 is pool
            # entry 77, the string "paintjobIDs".  Resolve them so the lifted
            # data is self-describing instead of a wall of magic numbers.
            if op in (0x05, 0x09) and pay and pay >= HEAP_BASE:
                t = ref_text(P, pay - HEAP_BASE)
                if t and not t.startswith("<bad"):
                    self.push(E(t, e.ty))
                else:
                    self.push(e)
            else:
                self.push(e)
        elif op == 0x08:
            self.push(E(json.dumps(P.utf8(pay), ensure_ascii=False),
                        "Ljava.lang.String;"))
        elif op == 0x0B:
            self.push(E(f"local{pay}", self.locals.get(pay, "?")))
        elif op == 0x0D:
            v = self.pop()
            if v.ty not in ("?",):
                self.locals[pay] = v.ty
            self.stmts.append({"target": f"local{pay}", "expr": v.txt,
                               "expr_type": v.ty, "match": None})
        elif op in (0x0C, 0x0E, 0x0F):
            self.stats[f"local_mgmt_{op:02x}"] += 1
        elif op == 0x13:
            o = self.pop("obj")
            owner, name, _d = split_ref(ref_text(P, pay))
            self.push(E(f"{o.txt}.{name}", self.field_ty(owner, name)))
        elif op == 0x14:
            owner, name, _d = split_ref(ref_text(P, pay))
            self.push(E(f"{owner}.{name}", self.field_ty(owner, name)))
        elif op == 0x15:
            owner, name, _d = split_ref(ref_text(P, pay))
            self.push(E(f"this.{name}", self.field_ty(owner, name)))
        elif op == 0x1F:
            v, o = self.pop(), self.pop("obj")
            owner, name, _d = split_ref(ref_text(P, pay))
            self.store(f"{o.txt}.{name}", None, v, owner, name)
        elif op == 0x20:
            v = self.pop()
            owner, name, _d = split_ref(ref_text(P, pay))
            self.store(f"{owner}.{name}", None, v, owner, name)
        elif op == 0x21:
            v = self.pop()
            owner, name, _d = split_ref(ref_text(P, pay))
            self.store(f"this.{name}", None, v, owner, name)
        elif op == 0x22:
            n = self.pop("length")
            elem = class_name(self.pool, pay) if pay is not None else None
            ty = ("[" + elem if elem and not elem.startswith("[")
                  else (elem or "array"))
            self.push(E(f"new {elem}[{n.txt}]", ty, array_of=ty))
            self.stats["newarray"] += 1
        elif op == 0x23:
            # Operand order in this VM is (index, array, value): the trace
            # `INT 0; LOCAL_LOAD 0; INT 0; I2F; ARRAY_STORE` proves the index is
            # pushed first and the array sits on top of it.
            v, arr, idx = self.pop(), self.pop("array"), self.pop("index")
            self.stmts.append({"target": f"{arr.txt}[{idx.txt}]", "expr": v.txt,
                               "expr_type": v.ty, "match": None})
        elif op == 0x24:
            n = pay or 0
            # The literal's elements are pushed first and NEWARRAY leaves the
            # array on TOP, so the elements are `stack[-n-1:-1]` - NOT
            # `stack[-n:]`, which would grab the array itself as the last
            # element.  Heights stay consistent either way, so only the
            # field-type cross-check catches this.
            vals = self.stack[-n - 1:-1] if n else []
            if n:
                del self.stack[-n - 1:-1]
            arr = self.pop("array")
            elems = ", ".join(v.txt for v in vals)
            arr.txt = f"{{{elems}}}"
            arr.ty = arr.array_of or "array"
            self.push(arr)
            self.stats["array_literals"] += 1
        elif op == 0x26:
            # Same convention as ARRAY_STORE: (index, array) with the array on
            # top, so the array is popped first.
            arr, idx = self.pop("array"), self.pop("index")
            self.push(E(f"{arr.txt}[{idx.txt}]", "?"))
        elif op == 0x27:
            cls = class_name(self.pool, pay) if pay is not None else "?"
            self.push(E(f"new {cls}", "L" + cls + ";", array_of=cls))
        elif op == 0x29:
            v = self.pop()
            self.stmts.append({"target": None, "expr": v.txt,
                               "expr_type": v.ty, "match": None,
                               "note": "discarded"})
        elif op == 0x2A:
            self.push(self.stack[-1] if self.stack else E("<?>"))
        elif op in (0x2B, 0x2C):
            if op == 0x2B and len(self.stack) >= 2:
                self.stack.insert(-1, self.stack[-1])
            elif op == 0x2C and len(self.stack) >= 3:
                self.stack.insert(-2, self.stack[-1])
            else:
                self.stats["underflow"] += 1
        elif op == 0x2D:                                   # DUP2
            if len(self.stack) >= 2:
                a, b = self.stack[-2], self.stack[-1]
                self.stack += [a, b]
            else:
                self.stats["underflow"] += 1
        elif op in BIN_SYM:
            b, a = self.pop(), self.pop()
            if op in (0x2E, 0x2F, 0x30) and "Ljava.lang.String;" in (a.ty, b.ty):
                ty = "Ljava.lang.String;"      # SADD doubles as string concat
            elif op in FLOATY:
                ty = "F"
            elif op in CMP:
                ty = "I"
            else:
                ty = "S"
            self.push(E(f"({a.txt} {BIN_SYM[op]} {b.txt})", ty))
        elif op in CONV:
            v = self.pop()
            self.push(E(f"(({CONV[op]}){v.txt})", CONV[op]))
        elif op in UN_SYM:
            v = self.pop()
            self.push(E(f"({UN_SYM[op]}{v.txt})", v.ty if op != 0x46 else "Z"))
        elif op in (0x37, 0x38):
            v = self.pop()
            self.push(E(f"(-{v.txt})", "F" if op == 0x38 else "I"))
        elif op == 0x39:
            v = self.pop()
            self.push(E(f"({v.txt} + 1)", v.ty))
        elif op == 0x3B:
            v = self.pop()
            self.push(E(f"({v.txt} - 1)", v.ty))
        elif op in (0x3A, 0x3C):
            v = self.pop()
            self.push(E(f"({v.txt} + 1.0)", "F"))
        elif op == 0x01:
            v = self.pop()
            t = class_name(P, pay) if pay is not None else None
            t = t or "?"
            self.push(E(f"(({t}){v.txt})", t if t.startswith("[") else "L" + t + ";"))
        elif op == 0x02:
            v = self.pop()
            t = class_name(P, pay) if pay is not None else None
            self.push(E(f"({v.txt} instanceof {t or '?'})", "Z"))
        elif op in (0x10, 0x11, 0x12):
            ref = ref_text(P, pay)
            name, d = parse_ref(ref)
            argc = n_args(d)
            args = [self.pop().txt for _ in range(argc)][::-1]
            owner = split_ref(ref)[0]
            if op == 0x12:
                call = f"{owner}.{name}({', '.join(args)})"
                recv = None
            else:
                recv = self.pop("recv")
                call = f"{recv.txt}.{name}({', '.join(args)})"
            ret = ret_desc(d)
            if name in ("<init>", "<i>") and recv is not None:
                # `NEW x` + `DUP` + args + INVOKESPECIAL <init> => `new x(args)`.
                # Mutate the node in place so the DUP'd copy stays the same object.
                recv.txt = call
                if recv.ty in ("?", ""):
                    recv.ty = "L" + split_ref(ref)[0] + ";"
                self.stats["ctor_calls"] += 1
            else:
                self.push(E(call, ret))
        elif op in JUMPS or op in (0x18, 0x19, 0x1A):
            self.stats["branch"] += 1
        elif op == 0x16:
            if self.stack:
                self.stmts.append({"target": "return", "expr": self.stack[-1].txt,
                                   "expr_type": self.stack[-1].ty,
                                   "match": None})
                self.stack.pop()
        elif op in (0x3E, 0x3F):
            self.stats["shortcut"] += 1
        elif op == 0x25:
            n = pay or 0
            for _ in range(n):
                self.pop("dim")
            self.push(E("new <?>[]...", "array"))
        elif op == 0x28:
            self.pop()
        else:
            self.stats[f"unhandled_{op:02x}"] += 1


def parse_ref(ref):
    """`java.game.Bet.getBetType ()I` -> ('getBetType', '()I')."""
    if " " in ref:
        head, d = ref.rsplit(" ", 1)
        return head.rsplit(".", 1)[-1], d
    return ref.rsplit(".", 1)[-1], "?"


def n_args(d):
    if not d.startswith("("):
        return 0
    depth, n = 0, 0
    i = 1
    while i < len(d) and d[i] != ")":
        c = d[i]
        if c == "[":
            i += 1
            continue
        if c == "L":
            i = d.index(";", i)
        elif c == "(":
            depth += 1
        i += 1
        n += 1
    return n


def ret_desc(d):
    if ")" not in d:
        return "?"
    return d[d.index(")") + 1:] or "V"


def ret_class(d):
    r = ret_desc(d)
    return "?" if r in ("V", "?") else r


def fields_index():
    """{(owner, name): type} plus a by-name fallback for quick lookups."""
    raw = json.loads((ROOT / "out_fields.json").read_text())
    by_owner, by_name = {}, {}
    for owner, name, ty, _kind, _flags in raw:
        by_owner[(owner, name)] = ty
        by_name.setdefault(name, ty)
    return by_owner, by_name


def class_lifts(path):
    """Lift every method of one class file -> [(tree_index, name, desc, stmts, stats)]."""
    ck = chunks(Path(path).read_bytes())
    pool = Pool(ck["CONS"][0])
    meta = load_methods_meta(ck)
    by_owner, by_name = fields_index()
    out = []
    for k, rec in enumerate(r for r in ck_tree(ck)):
        m = meta.get(k)
        if m is None:                     # record 0 = compiler's <clinit>
            name, desc = "<clinit>", "()V"
        else:
            name, desc = pool.utf8(m[1]) or "?", pool.utf8(m[2]) or "()V"
        lf = Lifter(pool, by_owner, meta, by_name)
        lf.run(rec, desc, m[0] if m else 0, m[3] if m else 0)
        out.append((k, name, desc, lf.stmts, lf.stats, lf.clashes, lf.linear))
    return out


def ck_tree(ck):
    from lasr_vm import tree_records
    return [r for r in tree_records(ck["TREE"][0]) if r and r[-1] == 0x16]


def show_class(path):
    for k, name, desc, stmts, stats, clashes, linear in class_lifts(path):
        if not stmts:
            continue
        print(f"\n--- #{k} {name}{desc}   ({dict(stats)})")
        for s in stmts:
            if s["target"] is None:
                print(f"      {s['expr']};")
            elif s["target"] == "return":
                print(f"      return {s['expr']};")
            else:
                print(f"      {s['target']} = {s['expr']};"
                      f"    // {s.get('field_type','')}")
        for t, e, u, g in clashes[:6]:
            print(f"   !! 类型不符 {t} = {e}  表达式 {u} vs 字段 {g}")


def dump():
    """Lift every field initialiser in the corpus; write out_init.json."""
    by_owner, by_name = fields_index()
    stats = Counter()
    out = {}
    for f, k, rec, pool, ar, nl in SD.corpus():
        m = load_methods_meta(chunks(f.read_bytes())).get(k)
        name = (pool.utf8(m[1]) if m else "<clinit>") or "?"
        if name not in ("<clinit>", "<i>"):
            continue
        desc = pool.utf8(m[2]) if m else "()V"
        lf = Lifter(pool, by_owner, m, by_name)
        lf.run(rec, desc, m[0] if m else 0, m[3] if m else 0)
        key = f"{f.relative_to(ROOT / 'extracted').as_posix()}#{k}"
        out[key] = {"method": name, "class": pool.utf8(0), "linear": lf.linear,
                    "underflow": lf.underflow_sites,
                    "stmts": lf.stmts, "stats": dict(lf.stats),
                    "clashes": lf.clashes[:20]}
        for s in lf.stats:
            stats[s] += lf.stats[s]
    (ROOT / "out_init.json").write_text(json.dumps(out, ensure_ascii=False))
    nlin = sum(1 for v in out.values() if v["linear"])
    st, cl = stats["stores"], stats["type_clash"]
    print(f"其中直线方法           : {nlin:,} / {len(out):,}")
    print(f"初始化器方法           : {len(out):,}")
    print(f"赋值语句               : {st:,}")
    print(f"  类型相符             : {stats['type_match']:,} = "
          f"{100*stats['type_match']/max(1,st):.2f}%")
    print(f"  类型不符             : {cl:,}")
    print(f"  无法判定             : {stats['type_undecided']:,}")
    for k in sorted(stats):
        if k not in ("stores", "type_match", "type_clash", "type_undecided"):
            print(f"  {k:<22} {stats[k]:,}")
    print(f"written: out_init.json ({(ROOT/'out_init.json').stat().st_size/1e6:.1f} MB)")


def report():
    """Readable dump of every lifted initialiser assignment: out_init_report.txt."""
    d = json.loads((ROOT / "out_init.json").read_text())
    by_class = defaultdict(list)
    for key, v in d.items():
        by_class[v["class"]].append((key, v))
    lines = ["# 所有字段初始化器（由 tools/lift_expr.py 从字节码抬升）",
             "# 格式: 字段 = 表达式        // 字段类型", ""]
    n = 0
    for cls in sorted(by_class):
        lines.append(f"\n{'=' * 78}\n{cls}\n{'=' * 78}")
        for key, v in sorted(by_class[cls]):
            lines.append(f"\n--- {v['method']}   [{key}]")
            for s in v["stmts"]:
                t = s["target"]
                ty = s.get("field_type") or ""
                if t == "return":
                    lines.append(f"      return {s['expr']};    // {s.get('expr_type','')}")
                elif t is None:
                    lines.append(f"      {s['expr']};")
                elif t.startswith("local"):
                    lines.append(f"      {t} = {s['expr']};    // {s.get('expr_type','')}")
                else:
                    lines.append(f"      {t} = {s['expr']};    // {ty}")
                n += 1
    p = ROOT / "out_init_report.txt"
    p.write_text("\n".join(lines), encoding="utf-8")
    print(f"语句 {n:,} 条 -> {p.name} ({p.stat().st_size/1e6:.1f} MB)")


def main():
    a = sys.argv[1:]
    if not a:
        print(__doc__)
        return
    global PARENTS
    PARENTS = load_parents()
    print(f"（父类表已载入：{len(PARENTS):,} 个类）")
    if "--class" in a:
        show_class(a[a.index("--class") + 1])
        return
    if "--dump" in a:
        dump()
        return
    if "--report" in a:
        report()
        return
    print(__doc__)


if __name__ == "__main__":
    main()
