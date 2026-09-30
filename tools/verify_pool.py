"""
Validate the constant-pool resolution against opcode semantics.

This is the decisive test that the CONS pool layout is right, independent of
byte-exactness: every operand must name a constant of the *kind its opcode
demands*.

    INVOKE / INVOKESPECIAL / INVOKESTATIC   -> a member ref whose descriptor
                                               starts with '(' (a method)
    FIELD_REF_* / PUTFIELD_*                -> a member ref whose descriptor is
                                               a field type (I, F, Ljava...;)
    NEW / CAST / INSTANCEOF / ...           -> a class name

A single mismatched kind would prove the pool mis-parsed.  Note that `NEW` and
friends carry a **UTF8 entry index**, not a tag-4 class index, while INVOKE and
FIELD carry a tag-5 reference - the two encodings coexist, so both are resolved.

Usage: python tools/verify_pool.py
"""
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

from lasr_vm import chunks, tree_records                    # noqa: E402
from lasr_cfg import disasm                                 # noqa: E402
from resolve_pool import Pool, TAG_UTF8                     # noqa: E402

INVOKES = {0x10, 0x11, 0x12}
FIELDS = {0x13, 0x14, 0x15, 0x1F, 0x20, 0x21}
CLASSES = {0x01, 0x02, 0x22, 0x27, 0x28}


def class_name(pool, idx):
    """A class operand may be a UTF8 entry or a tag4 entry -> UTF8."""
    if pool.tag(idx) == TAG_UTF8:
        return pool.utf8(idx)
    r = pool.ref(idx)
    return r[0] if r and r[3] == "class" else None


def main():
    tally = Counter()
    bad = []
    pools = 0
    for f in sorted(ROOT.glob("extracted/**/*.class")):
        try:
            ck = chunks(f.read_bytes())
            pool = Pool(ck["CONS"][0])
        except Exception:
            continue
        if not pool.exact:
            continue
        pools += 1
        for rec in tree_records(ck["TREE"][0]):
            if not rec or rec[-1] != 0x16:
                continue
            for ins in disasm(rec):
                if ins.pay is None:
                    continue
                p = ins.pay
                if ins.op in INVOKES:
                    r = pool.ref(p)
                    good = bool(r and r[3] == "ref" and r[0] and r[1]
                                and (r[2] or "").startswith("("))
                    tally["invoke ok" if good else "invoke BAD"] += 1
                    if not good and len(bad) < 10:
                        bad.append((f.name, hex(ins.op), p, r))
                elif ins.op in FIELDS:
                    r = pool.ref(p)
                    good = bool(r and r[3] == "ref" and r[0] and r[1]
                                and r[2] and not r[2].startswith("("))
                    tally["field ok" if good else "field BAD"] += 1
                    if not good and len(bad) < 10:
                        bad.append((f.name, hex(ins.op), p, r))
                elif ins.op in CLASSES:
                    nm = class_name(pool, p)
                    # NEWARRAY legitimately names an array descriptor ('[I',
                    # '[F') rather than a dotted class, so accept both.
                    good = bool(nm and ("." in nm or nm.startswith("[")))
                    tally["class ok" if good else "class BAD"] += 1
                    if not good and len(bad) < 10:
                        bad.append((f.name, hex(ins.op), p, nm))

    print(f"classes with an exact pool : {pools:,}\n")
    print("=== operand kind must match opcode kind ===")
    total_ok = total_bad = 0
    for kind in ("invoke", "field", "class"):
        ok, bd = tally[f"{kind} ok"], tally[f"{kind} BAD"]
        tot = ok + bd
        total_ok += ok
        total_bad += bd
        print(f"  {kind:<7}: OK {ok:>8,}   BAD {bd:>6,}   "
              f"{100*ok/max(1, tot):7.2f}%")
    print(f"\n  TOTAL  : OK {total_ok:,}   BAD {total_bad:,}")
    if bad:
        print("\nmismatch samples:")
        for b in bad:
            print("   ", b)
    else:
        print("\nno mismatches - the pool layout is confirmed semantically")


if __name__ == "__main__":
    main()
