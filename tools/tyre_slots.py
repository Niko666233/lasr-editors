"""把 out_tyres.json 的「紧凑序」系数按 PacejkaGlobals.pacVarIdxs_v2/v3 展开成真实槽号。

依据（全部来自 Java 伪码，见 out_pseudo/java/classes/game/parts/PacejkaGlobals.java）：
    pacVarIdxs_v2 = {2,12,0,4,13,11,14,3,17,10,1,6,7,8,18,19,15,16}            // 18 项
    pacVarIdxs_v3 = {2,12,0,4,13,11,14,3,17,10,1,6,7,8,18,19,15,16,34,35}      // 20 项
    common_pacVarIdxs = {15,16,26,24,25,22,23}
    common_pacVars    = {1000,6000,10.0,0.0,0.0,1.0,1.0}

⇒ 变量空间共 36 槽（0..35），与 docs/20 从 C++ 侧读到的
   "tyre[tyreIdx*36+idx] @ +0x20c" 独立互证。缺省槽补 0。
"""
import csv
import json
import os

ROOT = r"C:\Users\niko6\Desktop\Work\LASR_Reverse_Engineering"
V2 = [2, 12, 0, 4, 13, 11, 14, 3, 17, 10, 1, 6, 7, 8, 18, 19, 15, 16]
V3 = [2, 12, 0, 4, 13, 11, 14, 3, 17, 10, 1, 6, 7, 8, 18, 19, 15, 16, 34, 35]
COMMON_IDX = [15, 16, 26, 24, 25, 22, 23]
COMMON_VAL = [1000.0, 6000.0, 10.0, 0.0, 0.0, 1.0, 1.0]
NSLOT = 36


def main():
    data = json.load(open(os.path.join(ROOT, "out_tyres.json"), encoding="utf-8"))
    rows, meta = [], []
    for cls, d in data.items():
        for surf, coef in d["pacVars"].items():
            slots = [0.0] * NSLOT
            mapping = V3 if len(coef) >= 20 else V2
            assert len(coef) == len(mapping), f"{cls}/{surf}: {len(coef)} vs {len(mapping)}"
            for i, v in enumerate(coef):
                slots[mapping[i]] = v
            for j, idx in enumerate(COMMON_IDX):
                slots[idx] = COMMON_VAL[j]
            rows.append([cls, d["params"].get("nameBrand", "").replace("\\", ""), surf] + slots)
        p = d["params"]
        meta.append([cls, p.get("nameBrand", "").replace("\\", ""),
                     len(d["pacVars"].get("Asphalt", [])), p.get("Ref_Width"), p.get("Ref_Sidewall"),
                     p.get("Ref_RimDiam"), p.get("Ref_DeoptAngle"), p.get("Ref_Inflation"),
                     p.get("DeoptRate"), p.get("SpringRate"), p.get("DampingRate"),
                     p.get("treadDensity"), p.get("sidewallDensity")])
    with open(os.path.join(ROOT, "out_tyres_slots.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["tyre", "brand", "contact"] + [f"v{i}" for i in range(NSLOT)])
        w.writerows(rows)
    with open(os.path.join(ROOT, "out_tyres_geom.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["tyre", "brand", "n_coef", "ref_width", "ref_sidewall", "ref_rimdia",
                    "ref_deopt_angle", "ref_inflation", "deopt_rate", "spring_rate",
                    "damping_rate", "tread_density", "sidewall_density"])
        w.writerows(meta)
    print(f"→ out_tyres_slots.csv（{len(rows)} 行 × {NSLOT} 槽）")
    print(f"→ out_tyres_geom.csv（{len(meta)} 行）")

    # 一致性检查：同一配方 6 个接触面里，除了 v0（µ 缩放）是否还有其他差异
    print("\n=== 各配方「逐面差异」检查（除 v0 外是否还有变化）===")
    for cls in data:
        cols = [r for r in rows if r[0] == cls]
        diff = [i for i in range(NSLOT)
                if len({c[3 + i] for c in cols}) > 1]
        print(f"  {cls:12s} 变化的槽: {diff}  (v0 = 接触面抓地缩放)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
