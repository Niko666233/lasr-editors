"""
The TUFA `FILD` field table: layout, validation, and the field-name database.

Layout (solved from Bet.class, then checked byte-exactly on every class):

    FILD blob = <u32 n_grp1>                  count of group 1 (static) fields
                n_grp1 x <u32 flags><u32 name_idx><u32 type_idx><u32 extra>
                <u32 n_grp2>                  count of group 2 (instance) fields
                n_grp2 x <u32 flags><u32 name_idx><u32 type_idx><u32 extra>

    * name_idx / type_idx are CONS indices pointing at UTF8 entries.
    * `extra` looks like compiler buffer residue: it holds values recycled from
      other writes (name-index pairs, flag words) and is not consistent between
      classes, so it is reported but NOT interpreted.
    * flags are plain JVM-style access bits (ACC_PUBLIC=1, ACC_PRIVATE=2,
      ACC_STATIC=8, ACC_FINAL=16, ...), so `0x19` = public static final.

Two independent checks are run:

 1. byte layout: `4 + 16*n1 + 4 + 16*n2 == len(blob)` AND both name/type indices
    resolve to UTF8 entries, for every class.
 2. semantics: a field in group 1 must be referenced only by *_STATIC opcodes and
    a field in group 2 only by *_QUICK (instance) opcodes, and vice versa.  This
    needs no knowledge of the byte layout at all, so it independently pins down
    which group is which.

Usage:
  python tools/fild_shape.py --class <file>
  python tools/fild_shape.py --verify
  python tools/fild_shape.py --export
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
from resolve_pool import Pool, TAG_UTF8                     # noqa: E402

FIELD_OPS = {0x13, 0x14, 0x15, 0x1F, 0x20, 0x21}
REC = 16
ACC = {1: "public", 2: "private", 4: "protected", 8: "static", 16: "final",
       32: "synchronized", 64: "volatile", 128: "transient"}


def flags_text(f):
    names = [v for k, v in ACC.items() if f & k]
    return "|".join(names) if names else f"0x{f:x}"


def parse(blob):
    """-> (group1, group2, ok).  Each group is a list of dicts."""
    out = []
    pos = 0
    for _ in range(2):
        if pos + 4 > len(blob):
            return out, False
        n = struct.unpack_from("<I", blob, pos)[0]
        pos += 4
        recs = []
        for _ in range(n):
            if pos + REC > len(blob):
                return out, False
            fl, ni, ti, ex = struct.unpack_from("<4I", blob, pos)
            recs.append({"flags": fl, "name": ni, "type": ti, "extra": ex})
            pos += REC
        out.append(recs)
    return out, pos == len(blob)


def load_fields(path):
    ck = chunks(Path(path).read_bytes())
    pool = Pool(ck["CONS"][0])
    groups, ok = parse(ck["FILD"][0])
    fields = []
    for gi, recs in enumerate(groups):
        for r in recs:
            fields.append({
                "group": gi + 1,
                "flags": r["flags"],
                "static": (gi == 0),
                "name": pool.utf8(r["name"]),
                "type": pool.utf8(r["type"]),
                "extra": r["extra"],
                "name_idx": r["name"],
                "type_idx": r["type"],
            })
    return ck, pool, fields, ok


def ref_kinds(ck, pool):
    """{(owner, field name): set of 'static'/'instance'} from the operator codes.

    Keyed by owner AND name: several classes declare same-named fields (e.g.
    `player_transmission`), and merging by name alone produces bogus
    cross-class 'this field is used both ways' disagreements.
    """
    kinds = defaultdict(set)
    for rec in tree_records(ck["TREE"][0]):
        if not rec or rec[-1] != 0x16:
            continue
        for ins in disasm(rec):
            if ins.op not in FIELD_OPS or ins.pay is None:
                continue
            r = pool.ref(ins.pay)
            if not r or not r[1]:
                continue
            nm = name_of(ins.op)
            kinds[(r[0], r[1])].add("static" if "STATIC" in nm else "instance")
    return kinds


def show(path):
    ck, pool, fields, ok = load_fields(path)
    kinds = ref_kinds(ck, pool)
    n1 = sum(1 for f in fields if f["static"])
    n2 = len(fields) - n1
    print(f"=== {Path(path).name}  FILD={len(ck['FILD'][0])}B  "
          f"exact_fit={ok}  fields={n1} static + {n2} instance ===")
    owner = pool.utf8(0)
    for f in fields:
        k = kinds.get((owner, f["name"])) or set()
        src = ",".join(sorted(k)) if k else "-"
        print(f"   {'static' if f['static'] else 'inst  '} "
              f"{flags_text(f['flags']):<22} {f['type']:<34} {f['name']:<22}"
              f"  refs:{src}")


def verify():
    ok_fit = ok_idx = 0
    total = 0
    nfields1 = nfields2 = 0
    agree = disagree = 0
    bad = []
    for f in sorted(ROOT.glob("extracted/**/*.class")):
        try:
            ck, pool, fields, ok = load_fields(f)
        except Exception:
            continue
        total += 1
        if ok:
            ok_fit += 1
        good_idx = all(isinstance(x["name"], str) and isinstance(x["type"], str)
                       for x in fields)
        if good_idx:
            ok_idx += 1
        nfields1 += sum(1 for x in fields if x["static"])
        nfields2 += sum(1 for x in fields if not x["static"])
        kinds = ref_kinds(ck, pool)
        owner = pool.utf8(0)
        for x in fields:
            k = kinds.get((owner, x["name"]))
            if not k:
                continue
            want = "static" if x["static"] else "instance"
            if k == {want}:
                agree += 1
            else:
                disagree += 1
                if len(bad) < 10:
                    bad.append((f.name, owner, x["name"], x["type"], want,
                                sorted(k)))
    print(f"classes                       : {total:,}")
    print(f"  byte layout exact           : {ok_fit:,} = "
          f"{100*ok_fit/max(1,total):.2f}%")
    print(f"  name/type indices resolve   : {ok_idx:,} = "
          f"{100*ok_idx/max(1,total):.2f}%")
    print(f"fields: {nfields1:,} static + {nfields2:,} instance "
          f"= {nfields1+nfields2:,}")
    print(f"group-vs-opcode agreement     : {agree:,} agree, "
          f"{disagree:,} disagree  ({100*agree/max(1,agree+disagree):.2f}%)")
    for b in bad:
        print("   ", b)


def export():
    rows = []
    seen_names = set()
    for f in sorted(ROOT.glob("extracted/**/*.class")):
        try:
            ck, pool, fields, ok = load_fields(f)
        except Exception:
            continue
        if not ok:
            continue
        owner = pool.utf8(0)
        for x in fields:
            rows.append([owner, x["name"], x["type"],
                         "static" if x["static"] else "instance", x["flags"]])
            seen_names.add(x["name"])
    (ROOT / "out_fields.json").write_text(json.dumps(rows))
    print(f"fields total      : {len(rows):,}")
    print(f"distinct names    : {len(seen_names):,}")
    print(f"static / instance : "
          f"{sum(1 for r in rows if r[3] == 'static'):,} / "
          f"{sum(1 for r in rows if r[3] == 'instance'):,}")
    print("written: out_fields.json")
    print("\nsample rows:")
    for r in rows[:12]:
        print("   ", r)


def main():
    args = sys.argv[1:]
    if "--verify" in args:
        return verify()
    if "--export" in args:
        return export()
    path = args[args.index("--class") + 1] if "--class" in args else args[0]
    show(path)


if __name__ == "__main__":
    main()
