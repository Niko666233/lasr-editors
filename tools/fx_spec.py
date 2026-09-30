"""Extract the material/shader specification from the .fx sources.

The nine .fx files inside shader.dat are NOT D3D9 effect-framework files (no
`technique` / `pass`) - they are HLSL FUNCTION LIBRARIES plus a set of
compile-time `#define` switches.  A material is therefore COMPOSED:

    vertex shader   = vs_transform_*  x  vs_layer_*  x  vs_lighting_*  x vs_fog
    pixel  shader   = ps_layer_*      x  ps_lighting_*

which is exactly the grammar of the compiled shader names
(`ColTex2BumpSpecular_Lightmapped0` = layer(coltex2) + bump + specular +
lightmapped).  This tool dumps, per file:

  * the constant-register layout (`<type> <name> : register(cN)`) - each material
    family has its OWN layout (Chassis uses c0/c1, Complex c2/c3),
  * the samplers with their role comments,
  * the function inventory classified by stage,
  * the `#define` variant axes and their value sets.

    python tools/fx_spec.py --dump
    python tools/fx_spec.py --file Chassis.fx
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "out_shaders"

STAGES = [
    ("transform", r"^vs_transform"),
    ("layer_vs", r"^vs_layer"),
    ("lighting_vs", r"^vs_lighting|^vs_fog|^vs_projdepthshadow"),
    ("layer_ps", r"^ps_layer"),
    ("lighting_ps", r"^ps_lighting"),
    ("helper", r"^(compute_|Get|inShadow|ApplyFog)"),
]
CLEAN = re.compile(r"//[^\n]*")


def strip_comments(t):
    """Remove // comments but keep the sampler role text captured separately."""
    return CLEAN.sub("", t)


def parse(path):
    raw = path.read_text("latin1")
    t = strip_comments(raw)

    # constants: <type> <name> : register(cN)  (multi-word types allowed)
    consts = []
    for m in re.finditer(r"([A-Za-z_][\w]*(?:\s*[0-9x]+)?)\s+([A-Za-z_]\w*)\s*:\s*register\((\w+)\)", t):
        typ, name, reg = m.group(1).strip(), m.group(2), m.group(3)
        if name.lower() in ("register",):
            continue
        consts.append({"type": typ, "name": name, "register": reg})
    # dedupe by (register, name) keeping order
    seen, uniq = set(), []
    for c in consts:
        k = (c["register"], c["name"])
        if k not in seen:
            seen.add(k)
            uniq.append(c)

    samplers = []
    for m in re.finditer(r"^\s*(//)?\s*sampler\s+(\w+)\s*;(.*)$", raw, re.M):
        role = m.group(3).strip().lstrip("/").strip()
        samplers.append({"name": m.group(2), "active": not m.group(1), "role": role})

    funcs = []
    for m in re.finditer(r"^\s*(void|float[234]?|half[234]?)\s+(\w+)\s*\(", t, re.M):
        fn = m.group(2)
        stage = next((s for s, pat in STAGES if re.search(pat, fn)), "other")
        funcs.append({"name": fn, "ret": m.group(1), "stage": stage})

    defines = sorted(set(re.findall(r"#define\s+(\w+)", raw)))
    axes = {}
    for d in defines:
        fam = d.split("_")[0]
        axes.setdefault(fam, []).append(d)

    return {"file": path.name, "lines": raw.count("\n") + 1, "bytes": len(raw),
            "constants": uniq, "samplers": samplers, "functions": funcs,
            "defines": defines, "axes": axes}


def classify(name):
    """Map a compiled shader name to the .fx building blocks it is composed of.

    Returns (kind, {keyword: matched}) where kind is 'vsh'/'psh'/other.
    """
    base = name.rsplit(".", 1)[0]
    kind = name.rsplit(".", 1)[-1]
    # split off the lighting suffix after the last '_'
    parts = base.split("_")
    core, lighting = parts[0], parts[1] if len(parts) > 1 else ""
    hits = {}
    rules = {
        "transform_skinned": re.compile(r"Skinned(?!.*Pal)", re.I),
        "transform_palskinned": re.compile(r"PalSkinned", re.I),
        "transform_slot": re.compile(r"Slot", re.I),
        "transform_intopara": re.compile(r"IntoPara(b|oloid)", re.I),
        "layer_vcol": re.compile(r"Vcol|VC", re.I),
        "layer_tex3": re.compile(r"Tex3", re.I),
        "layer_tex2": re.compile(r"Tex2", re.I),
        "layer_tex": re.compile(r"Tex(?!t?\d)", re.I),
        "layer_col": re.compile(r"^Col|Col$", re.I),
        "lighting_bump": re.compile(r"Bump", re.I),
        "lighting_specular": re.compile(r"Spec", re.I),
        "lighting_reflection": re.compile(r"Refl", re.I),
        "lighting_planar": re.compile(r"Planar", re.I),
        "lighting_lightmap": re.compile(r"Lightmap", re.I),
        "lighting_shadow": re.compile(r"Shadow|ZOffset", re.I),
        "lighting_masked": re.compile(r"Masked", re.I),
        "lighting_anim": re.compile(r"Anim", re.I),
    }
    for k, rx in rules.items():
        if rx.search(core) or rx.search(lighting):
            hits[k] = True
    return kind, core, lighting, sorted(hits)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", action="store_true")
    ap.add_argument("--file")
    ap.add_argument("--map", action="store_true")
    a = ap.parse_args()
    files = sorted(SRC.glob("*.fx"))
    spec = [parse(p) for p in files]
    print(f".fx 文件 {len(spec)} 个")

    # global variant axes
    allaxes = {}
    for s in spec:
        for fam, names in s["axes"].items():
            allaxes.setdefault(fam, set()).update(names)
    print("\n=== 全局变体轴（#define 家族）===")
    for fam, names in sorted(allaxes.items()):
        print(f"  {fam:<16} {len(names):>2}: {sorted(names)}")

    print("\n=== 逐文件 ===")
    for s in spec:
        st = {}
        for f in s["functions"]:
            st[f["stage"]] = st.get(f["stage"], 0) + 1
        regs = [c["register"] for c in s["constants"]]
        print(f"  {s['file']:<28} {s['lines']:>4}行 常量{len(s['constants']):>2}"
              f" 采样器{len(s['samplers']):>2} 函数{len(s['functions']):>3}  {st}")
        print(f"      寄存器: {','.join(regs[:14])}{' ...' if len(regs) > 14 else ''}")
    if a.file:
        s = next((x for x in spec if a.file.lower() in x["file"].lower()), None)
        if s:
            print(f"\n### {s['file']}")
            for c in s["constants"]:
                print(f"  {c['register']:<4} {c['type']:<10} {c['name']}")
            print("  采样器:", [(x["name"], x["role"]) for x in s["samplers"]])
            print("  函数:", [(f["name"], f["stage"]) for f in s["functions"]])
    if a.map:
        import json as _json
        idx = _json.loads((ROOT / "out_shaders.json").read_text())
        names = [e["name"] for e in idx]
        fns = {f["name"] for s in spec for f in s["functions"]}
        # rule -> does the source library actually contain such a building block?
        probe = {
            "transform_normal": "vs_transform_normal", "transform_skinned": "vs_transform_skinned2",
            "transform_palskinned": "vs_transform_palskinned1", "transform_slot": "vs_transform_slot",
            "transform_intopara": "vs_transform_intopara", "layer_col": "vs_layer_col",
            "layer_vcol": "vs_layer_vcol", "layer_tex": "vs_layer_tex", "layer_tex2": "vs_layer_tex2",
            "layer_tex3": "vs_layer_tex3", "lighting_bump": "vs_lighting_diffusebump",
            "lighting_specular": "vs_lighting_spec", "lighting_reflection": "vs_lighting_ref",
            "lighting_planar": "vs_lighting_planarref", "lighting_lightmap": "vs_lighting_diffuse_lightmap",
            "lighting_shadow": "vs_projdepthshadow", "lighting_masked": "ps_lighting_maskedspecref",
            "lighting_anim": "vs_layer_tex2",
        }
        miss = {k: v for k, v in probe.items() if v not in fns}
        print(f"\n=== 关键词→构建块 双向核对 ===")
        print(f"  .fx 提供的函数 {len(fns)} 个；映射规则对应的构建块缺失 {len(miss)} 个"
              + (f" ✗ {miss}" if miss else " ✓ 全部存在"))
        used, unexplained, bykind = {}, [], {}
        for n in names:
            kind, core, lighting, hits = classify(n)
            bykind[kind] = bykind.get(kind, 0) + 1
            for h in hits:
                used[h] = used.get(h, 0) + 1
            if not hits:
                unexplained.append(n)
        print(f"  已归类名字 {len(names)} 个（{bykind}）")
        print(f"  关键词使用统计: {dict(sorted(used.items(), key=lambda kv: -kv[1]))}")
        print(f"  无法归类（没有任何关键词命中）: {len(unexplained)} 个"
              + (f" {unexplained[:10]}" if unexplained else " ✓"))
        # reverse: a building block the names never reference is suspicious
        never = [k for k in probe if k not in used]
        print(f"  规则定义了但 175 个名字从未用到: {never if never else '✓ 无'}")

    if a.dump:
        p = ROOT / "out_fx_spec.json"
        p.write_text(json.dumps({"files": spec,
                                 "axes": {k: sorted(v) for k, v in allaxes.items()}}, indent=1))
        print(f"\nwrote {p.name} ({p.stat().st_size:,} B)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
