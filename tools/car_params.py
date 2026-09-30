"""
Extract the per-car part parameters from the vehicle part classes.

Layout on disk:

    extracted/vehicles/<Car>_<Year>/<body>/classes/classes/<Body>_<Part>_<stage>.class

192 part classes per car (bumpers, doors, hood, engine stages, gearbox, tyres,
suspension, ...), and the numbers live in their parameter getters - the engine
classes alone carry `eRPMs()[F` and `eMuls()[F`, a 13-point torque curve.

Those getters build an array and fill it one element at a time:

    LOCAL_CREATE
    INT LITERAL 13 ; NEWARRAY ; LOCAL_STORE 0     ; a = new float[13]
    INT LITERAL 0 ; LOCAL_LOAD 0 ; INT LITERAL 1058 ; I2F ; ARRAY_STORE
    ...
    return a

so the value is only visible after materialising the array from the store
sequence - which is what `materialise()` does on top of the lifter's statements.

Usage:
  python tools/car_params.py --list                 # parameters found per class
  python tools/car_params.py --dump                 # -> out_car_params.json
  python tools/car_params.py --engine               # engine curves, all cars
"""
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

from lasr_vm import chunks, tree_records                     # noqa: E402
from resolve_pool import Pool                                # noqa: E402
from lasr_named import load_methods_meta                     # noqa: E402
import lift_expr as LX                                       # noqa: E402

VEH = ROOT / "extracted" / "vehicles"
NUM = re.compile(r"^-?\d+(\.\d+)?$")


def num(txt):
    """Parse a lifted literal ('((F)1058)' / '-3' / '"x"') into a number."""
    t = txt.strip()
    for _ in range(3):
        m = re.fullmatch(r"\(\((\w|\[|;|\.)+\)(.+)\)", t)
        if m:
            t = m.group(2).strip()
        else:
            break
    t = t.strip("()")
    if NUM.match(t):
        return float(t) if "." in t else int(t)
    return None


def materialise(stmts):
    """Rebuild arrays from `local = new T[n]` + `local[i] = v` sequences."""
    arrays, scalars = {}, {}
    for s in stmts:
        t, e = s.get("target"), s.get("expr")
        t = t or ""
        if not t:
            continue
        m = re.fullmatch(r"(local\d+)\[(\d+)\]", t)
        if m:
            loc, idx = m.group(1), int(m.group(2))
            v = num(e)
            if v is not None:
                arr = arrays.setdefault(loc, {})
                arr[idx] = v
            continue
        m = re.fullmatch(r"(local\d+)", t)
        if m:
            loc = m.group(1)
            mm = re.match(r"new (\S+)\[", e or "")
            if mm:
                arrays[loc] = {}
            else:
                v = num(e)
                if v is not None:
                    scalars[loc] = v
                else:
                    scalars[loc] = e
            continue
        if t != "return" and not t.startswith("this."):
            continue
    return arrays, scalars


def class_params(path, by_owner, by_name):
    """-> {method_name: value} for one part class (values may be lists)."""
    ck = chunks(path.read_bytes())
    pool = Pool(ck["CONS"][0])
    meta = load_methods_meta(ck)
    out, descs = {}, {}
    for k, rec in enumerate(r for r in tree_records(ck["TREE"][0])
                            if r and r[-1] == 0x16):
        m = meta.get(k)
        if m is None:
            continue
        name = pool.utf8(m[1]) or "?"
        desc = pool.utf8(m[2]) or ""
        lf = LX.Lifter(pool, by_owner, meta, by_name)
        lf.run(rec, desc, m[0], m[3])
        arrays, scalars = materialise(lf.stmts)
        rets = [s["expr"] for s in lf.stmts if s.get("target") == "return"]
        val = None
        if rets:
            r = rets[-1].strip()
            if r in arrays:
                n = len(arrays[r])
                val = [arrays[r].get(i) for i in range(n)]
            elif r in scalars:
                val = scalars[r]
            else:
                v = num(r)
                val = v if v is not None else r.strip('"')
        elif name == "staticinit" and lf.stmts:
            pass
        if name == "<init>":
            # `<init>` fills instance fields - keep them, they are the part's data
            inst = {s["target"].split(".")[-1]: s["expr"] for s in lf.stmts
                    if (s.get("target") or "").startswith("this.")}
            if inst:
                val = inst
        if val is not None:
            out[name] = val
            descs[name] = desc
    return out, descs, pool.utf8(0)


def scan():
    by_owner, by_name = LX.fields_index()
    cars = defaultdict(dict)
    for f in sorted(VEH.glob("*/*/classes/classes/*.class")):
        rel = f.relative_to(VEH).parts        # <car>/<body>/classes/classes/X.class
        car, body = rel[0], rel[1]
        try:
            params, descs, cls = class_params(f, by_owner, by_name)
        except Exception as exc:              # noqa: BLE001
            print(f"   !! {f.name}: {exc}")
            continue
        if not params:
            continue
        key = f"{body}/{f.stem}"
        cars[car][key] = {"class": cls, "params": params, "descs": descs}
    return cars


def dump(cars):
    p = ROOT / "out_car_params.json"
    p.write_text(json.dumps(cars, ensure_ascii=False))
    print(f"车辆 {len(cars)} 台写盘 -> {p.name} ({p.stat().st_size/1e6:.1f} MB)")
    for car in sorted(cars):
        n = len(cars[car])
        keys = sum(len(v["params"]) for v in cars[car].values())
        print(f"   {car:<26} {n:>4} 个部件类 / {keys:>6} 个参数")


def engine(cars):
    """Print the engine torque curves side by side for every car."""
    for car in sorted(cars):
        rows = {k: v for k, v in cars[car].items() if "IEngine" in k}
        if not rows:
            continue
        print(f"\n{'=' * 78}\n{car}\n{'=' * 78}")
        for key in sorted(rows):
            pp = rows[key]["params"]
            rpm, mul = pp.get("eRPMs"), pp.get("eMuls")
            if not (isinstance(rpm, list) and isinstance(mul, list)):
                continue
            print(f"  {key:<34} RPM {rpm}")
            print(f"  {'':<34} MUL {mul}")


def main():
    a = sys.argv[1:]
    if not a:
        print(__doc__)
        return
    LX.PARENTS = LX.load_parents()
    cars = scan()
    if "--dump" in a:
        dump(cars)
    if "--list" in a:
        names = Counter()
        for car in cars.values():
            for v in car.values():
                names.update(v["params"].keys())
        print("\n参数/方法名出现次数:")
        for n, c in names.most_common(40):
            print(f"   {c:>6}  {n}")
    if "--engine" in a:
        engine(cars)


if __name__ == "__main__":
    main()
