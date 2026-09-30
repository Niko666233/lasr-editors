"""从 Java 伪码里抽出所有轮胎配方（11 个具体类）→ out_tyres.json / out_tyres.csv。

背景：`java.game.parts.Tyre` 是抽象基类（getRef_pacVars/getTreadDensity/
getSidewallDensity 都是 "overriden ... not implemented"），真身在 Typе_XX 子类。
每个子类 <init> 里形如：

    this.Ref_Width = 205.0;
    this.nameBrand = "Pirelli P400 Touring";
    local1 = {20 个数};
    java.game.parts.Tyre_NC.Ref_pacVars[java.game.parts.PacejkaGlobals.CONTACT_Asphalt] = local1;

⇒ 用"记住最后一次数组赋值"的方式把它接到随后那个 CONTACT_* 槽上。
"""
import glob
import json
import os
import re

ROOT = r"C:\Users\niko6\Desktop\Work\LASR_Reverse_Engineering"
PARTS = os.path.join(ROOT, "out_pseudo", "java", "classes", "game", "parts")

SCALAR = ["Ref_Width", "Ref_Sidewall", "Ref_RimDiam", "Ref_DeoptAngle",
          "Ref_Inflation", "DeoptRate", "SpringRate", "DampingRate",
          "nameBrand", "ProfileToSpringrate"]
ARR_RE = re.compile(r"([\w\.]+)\s*=\s*\{([^{}]*)\}\s*;")
CONTACT_RE = re.compile(r"Ref_pacVars\[\s*[\w\.]*?CONTACT_(\w+)\s*\]\s*=")
SCAL_RE = re.compile(r"this\.(\w+)\s*=\s*([^;]+);")


def num(v):
    """解析伪码里的数字：可能是 ((F)9500)、((this.Ref_Width * 55.0) / 100.0) 等。"""
    v = v.strip()
    v = v.replace("((F)", "").replace("(F)", "")
    # 剥掉平衡的外层括号
    while v.startswith("(") and v.endswith(")"):
        inner, d, ok = v[1:-1], 0, True
        for c in inner:
            if c == "(":
                d += 1
            elif c == ")":
                d -= 1
                if d < 0:
                    ok = False
                    break
        if not (ok and d == 0):
            break
        v = inner.strip()
    # 剥掉 ((F) 之后残留的不平衡右括号，如 "9500)"
    while v.endswith(")") and v.count("(") < v.count(")"):
        v = v[:-1].strip()
    return float(eval(v, {"__builtins__": {}}, {}))


def parse(path):
    src = open(path, encoding="utf-8", errors="replace").read()
    cls = os.path.basename(path)[:-5]
    params, tables, last = {}, {}, None

    for line in src.splitlines():
        line = line.strip()
        m = ARR_RE.search(line)
        if m and "Ref_pacVars" not in line:
            vals = [v.strip() for v in m.group(2).split(",") if v.strip()]
            nums = []
            ok = True
            for v in vals:
                try:
                    nums.append(num(v))
                except Exception:          # noqa: BLE001
                    ok = False
                    break
            if ok and nums:
                last = nums
            continue
        m = CONTACT_RE.search(line)
        if m and last is not None:
            tables[m.group(1)] = last
            continue
        m = SCAL_RE.search(line)
        if m and m.group(1) in SCALAR:
            v = m.group(2).strip()
            if v.startswith('"'):
                params[m.group(1)] = v.strip('"')
            else:
                # 表达式里会引用已解析的字段（如 this.Ref_Width），代入后真算出来
                v2 = v.replace("this.Ref_Width", str(params.get("Ref_Width", 0.0)))
                try:
                    params[m.group(1)] = num(v2)
                except Exception:                                          # noqa: BLE001
                    params[m.group(1)] = v
    # 类内常量（tread/sidewall density）走独立方法
    for fn, key in (("getTreadDensity", "treadDensity"), ("getSidewallDensity", "sidewallDensity")):
        m = re.search(rf"{fn}\(\)F\s*\r?\nreturn\s+([\d\.]+);", src)
        if m:
            params[key] = float(m.group(1))
    return cls, params, tables


def main():
    files = sorted(glob.glob(os.path.join(PARTS, "Tyre_*.java")))
    out = {}
    for f in files:
        cls, params, tables = parse(f)
        if tables or params:
            out[cls] = {"params": params, "pacVars": tables}
        print(f"  {cls:12s} 参数 {len(params):2d} 项, 接触面 {len(tables)} 个"
              + (f", 每面 {len(next(iter(tables.values())))} 系数" if tables else ""))
    with open(os.path.join(ROOT, "out_tyres.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, ensure_ascii=False)

    # CSV：一行一个 (轮胎, 接触面)，系数列 c0..c19
    import csv
    maxn = max((len(c) for d in out.values() for c in d["pacVars"].values()), default=0)
    rows = []
    for cls, d in out.items():
        for surf, c in d["pacVars"].items():
            rows.append([cls, d["params"].get("nameBrand", ""), surf] + c + [""] * (maxn - len(c)))
    with open(os.path.join(ROOT, "out_tyres.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["tyre", "brand", "contact"] + [f"c{i}" for i in range(maxn)])
        w.writerows(rows)
    print(f"\n→ out_tyres.json（{len(out)} 个配方）/ out_tyres.csv（{len(rows)} 行，系数列数 {maxn}）")

    # 交叉核对：各配方在第 0 项（µ 缩放）上对冰面 vs 沥青
    print("\n=== 冰面 / 沥青 的 c0 对比（µ 缩放）===")
    for cls, d in out.items():
        a = d["pacVars"].get("Asphalt", [None])[0]
        i = d["pacVars"].get("Ice", [None])[0]
        b = d["params"].get("nameBrand", "?")
        print(f"  {cls:12s} {b:32s} 沥青={a} 冰={i}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
