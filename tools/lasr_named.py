"""
Named disassembly: JavaMachine bytecode with every operand resolved to a name.

Combines everything recovered so far:

  * instruction boundaries + width table      (docs/08, out_w_final.json)
  * jump semantics `target = off + payload`   (docs/09_CFG.md)
  * the CONS constant pool: 4 tag kinds, one index base  (tools/resolve_pool.py)
  * the MTHD method table: `<u32 0><u32 n>` + n x 5 u32, giving every method its
    real name and descriptor                       (read off Bet.class below)

Only the opcodes that genuinely carry a pool index are resolved as references;
`INT LITERAL` / `LOCAL_LOAD` / jumps carry plain numbers and are printed as such
(an earlier pass resolved those as pool indices too, which produced nonsense).

MTHD record layout (verified against Bet.class's 7 methods, all 7 names and
descriptors matching the pool):

    <u32 reserved=0> <u32 n_methods>
    n x <u32 flags> <u32 name_idx> <u32 desc_idx> <u32 tree_rec_idx+1> <u32 ?>

Usage:
  python tools/lasr_named.py --class <class-file> [--method N]
  python tools/lasr_named.py --export              # game-wide name tables
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
from lasr_cfg import disasm, name_of, JUMPS, jump_target    # noqa: E402
from resolve_pool import Pool                               # noqa: E402
from fild_shape import parse as fild_parse, flags_text as fild_flags  # noqa: E402

# opcode -> how to render its 4-byte operand
CLASS_OPS = {0x01, 0x02, 0x22, 0x27, 0x28}
STRING_OPS = {0x08}
REF_OPS = {0x10, 0x11, 0x12, 0x13, 0x14, 0x15, 0x1F, 0x20, 0x21}
LOCAL_OPS = {0x0B, 0x0D, 0x0F}
LITERAL_OPS = {0x05}
FLOAT_OPS = {0x06}
BOOL_OPS = {0x04}
CHAR_OPS = {0x07}
RID_OPS = {0x09}


def load_methods_meta(ck):
    """MTHD -> {tree_record_index: (flags, name_idx, desc_idx, n_locals)}.

    Layout - two groups with the second count *between* them, exactly like FILD:

        <u32 n1> + n1 x <flags, name_idx, desc_idx, tree_index, n_locals>
        <u32 n2> + n2 x <same 20-byte record>

    Group 1 holds the static methods (flags & 8), group 2 the instance methods.
    Reading a fixed 8-byte header instead made the first group's records be
    parsed as a header, so every class with n1 > 0 got wrong names/descriptors.

    `tree_index` is 1-based, and TREE record 0 is the compiler-generated
    `<clinit>`, which has no MTHD entry - so len(tree_records) == n1 + n2 + 1.
    """
    out = {}
    blob = ck.get("MTHD", [None])[0]
    if not blob or len(blob) < 4:
        return out
    pos = 0
    for _ in range(2):
        if pos + 4 > len(blob):
            break
        n = struct.unpack_from("<I", blob, pos)[0]
        pos += 4
        for _ in range(n):
            if pos + 20 > len(blob):
                return out
            flags, name_i, desc_i, slot, n_locals = struct.unpack_from(
                "<5I", blob, pos)
            out[slot] = (flags, name_i, desc_i, n_locals)
            pos += 20
    return out


def ref_text(pool, idx):
    """Render a reference entry as `Owner.member descriptor`."""
    r = pool.ref(idx)
    if not r:
        return f"<bad ref {idx}>"
    owner, nm, de, kind = r
    if kind == "class" or nm is None:
        return str(owner)
    return f"{owner}.{nm} {de}" if de else f"{owner}.{nm}"


def class_name(pool, idx):
    """A class operand may be a UTF8 entry or a tag4 entry -> UTF8."""
    if pool.tag(idx) == 0:
        return pool.utf8(idx)
    r = pool.ref(idx)
    return r[0] if r and r[3] == "class" else None


def fmt(pool, ins):
    """Operand text for one instruction."""
    if ins.pay is None:
        return ""
    p = ins.pay
    if ins.op in JUMPS:
        t = jump_target(ins, "op0")
        return f" -> {t}  ({ins.signed:+d})"
    if ins.op in CLASS_OPS:
        nm = class_name(pool, p)
        return f"  {nm if nm else p}"
    if ins.op in STRING_OPS:
        s = pool.utf8(p)
        return f"  {s!r}" if s is not None else f"  idx {p}"
    if ins.op in REF_OPS:
        return f"  {ref_text(pool, p)}"
    if ins.op in LOCAL_OPS:
        return f"  slot {p}"
    if ins.op in FLOAT_OPS:
        f = struct.unpack("<f", struct.pack("<I", p))[0]
        return f"  {f!r}"
    if ins.op in CHAR_OPS:
        return f"  {p:#x} {chr(p)!r}"
    if ins.op in RID_OPS:
        return f"  rid {p}"
    return f"  {p}"


def show_class(path, only=None, max_lines=200, quiet=False):
    ck = chunks(Path(path).read_bytes())
    pool = Pool(ck["CONS"][0])
    meta = load_methods_meta(ck)
    recs = [r for r in tree_records(ck["TREE"][0]) if r and r[-1] == 0x16]
    fields, _ = fild_parse(ck["FILD"][0])
    if not quiet:
        cls = pool.utf8(0)
        sup = pool.ref(struct.unpack_from("<I", ck["CLSS"][0], 12)[0])
        print(f"=== {Path(path).name}  pool={pool.count} exact={pool.exact} "
              f"methods={len(recs)} (MTHD names: {len(meta)}) ===")
        print(f"class {cls} extends {sup[0] if sup else '?'}")
        for gi, group in enumerate(fields):
            for r in group:
                fl = fild_flags(r['flags'])
                print(f"   {'static' if gi == 0 else 'field ':<7}{fl:<24}"
                      f"{pool.utf8(r['type']):<34}{pool.utf8(r['name'])}")
    for k, rec in enumerate(recs):
        if only is not None and k != only:
            continue
        m = meta.get(k)
        head = f"{m[1]}" if m else "?"
        name = pool.utf8(m[1]) if m else None
        desc = pool.utf8(m[2]) if m else None
        slots = f"   locals={m[3]}" if m and m[3] else ""
        print(f"\n--- method #{k}: {name or head}{desc or ''}"
              f"   ({len(rec)} bytes){slots}")
        lines = []
        for ins in disasm(rec):
            lines.append(f"   {ins.off:6d}  {ins.op:02x} {name_of(ins.op):<20}"
                         f"{fmt(pool, ins)}")
            if len(lines) >= max_lines:
                lines.append("   ... (truncated)")
                break
        print("\n".join(lines))


def export():
    """Game-wide name tables from every class's pool + MTHD."""
    classes = math = fields = 0
    cls_names, mem, meth_names = set(), set(), set()
    for f in sorted(ROOT.glob("extracted/**/*.class")):
        try:
            ck = chunks(f.read_bytes())
            pool = Pool(ck["CONS"][0])
        except Exception:
            continue
        if not pool.exact:
            continue
        classes += 1
        if pool.utf8(0):
            cls_names.add(pool.utf8(0))
        for i in pool.entries:
            r = pool.ref(i)
            if not r:
                continue
            owner, nm, de, kind = r
            if kind == "class":
                if owner:
                    cls_names.add(owner)
            elif kind == "ref" and owner and nm:
                mem.add((owner, nm, de))
        for k, (flags, ni, di, extra) in load_methods_meta(ck).items():
            n, d = pool.utf8(ni), pool.utf8(di)
            if n:
                meth_names.add((n, d))
    print(f"classes with exact pool : {classes:,}")
    print(f"distinct class names    : {len(cls_names):,}")
    print(f"distinct member refs    : {len(mem):,}")
    print(f"distinct method names   : {len(meth_names):,}")
    (ROOT / "out_names.json").write_text(json.dumps({
        "classes": sorted(cls_names),
        "members": sorted([o, n, d or ""] for o, n, d in mem if o),
        "method_names": sorted([n, d or ""] for n, d in meth_names),
    }, indent=0))
    print("written: out_names.json")
    print("\nsample class names:")
    for c in sorted(cls_names)[:15]:
        print(f"   {c}")
    print("\nsample members:")
    for o, n, d in sorted(mem)[:15]:
        print(f"   {o}.{n} {d}")


def main():
    args = sys.argv[1:]
    if "--export" in args:
        return export()
    path = args[args.index("--class") + 1] if "--class" in args else args[0]
    only = int(args[args.index("--method") + 1]) if "--method" in args else None
    show_class(path, only=only)


if __name__ == "__main__":
    main()
