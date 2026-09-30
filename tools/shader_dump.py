"""Split shader.dat into individual shader sources + an index.

Container layout (VERIFIED by exhaustive variant test: only this reading gives
175/175 name-compliant entries, 174/174 exact hops and a tail exactly at EOF):

    <name>\\0<u32 size><body>       record_start = name_start
                                   body_start   = name_end + 5   (after \\0 + u32)
                                   record_end   = body_start + size
    so `size` == the body length; <name>\\0 + u32 size are 5 + len(name) bytes

Entries are .psh / .vsh (D3D shader assembly, first line `ps.1.1` / `vs_1_1`) and
.fx (HLSL effect source).  Names carry the material variant taxonomy the engine
uses to pick a shader per surface:

    Col | 0..2 x TexN | Bump | Specular | Reflection | Masked | Layered | Skinned
        x Normal0 | Lightmapped0

PITFALL this tool exists to avoid (it cost a wrong result once): a name regex
restricted to `.psh|.vsh` plus an acceptance window of "+-4 bytes around a
candidate name" silently drops every `.fx` entry AND hides a 4-byte offset error,
because the tolerance absorbs the error and the regex filters the rest.  The
result looked self-consistent (all slack 0, ends at EOF) while missing 55 of 175
entries.  Walk the chain from byte 0 exactly, and reject on name CONTENT, not on
a tolerance window.

    python tools/shader_dump.py --dump
    python tools/shader_dump.py --grep Chassis
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "extracted/_loose/shader.dat"
OUT = ROOT / "out_shaders"
NAME_OK = re.compile(r"[A-Za-z0-9_.\-]{3,60}\.(psh|vsh|fx)")


def parse(path):
    """Walk the record chain from byte 0, exactly.

    record_start = name_start; body_start = name_end + 5; record_end = name_end +
    1 + size  =>  `size` counts from the size field itself, body length == size-4.
    Rejection is on name CONTENT, never on a tolerance window (see module doc).
    """
    d = path.read_bytes()
    ents, notes = [], []
    pos = 0
    while pos < len(d):
        z = d.find(b"\x00", pos)
        if z < 0:
            notes.append(f"pos 0x{pos:x}: 无终止符")
            break
        name = d[pos:z].decode("latin1")
        size = int.from_bytes(d[z + 1:z + 5], "little")
        body_start, end = z + 5, z + 5 + size
        if size < 5 or end > len(d):
            notes.append(f"pos 0x{pos:x} name={name[:30]!r} size={size} 越界，停止")
            break
        blob = d[body_start:end]
        ents.append({
            "name": name, "size": size, "record_start": pos, "offset": body_start,
            "body_len": size, "record_end": end,
            "ext": name.rsplit(".", 1)[-1] if "." in name else "?",
            "first_line": blob.split(b"\r\n")[0][:60].decode("latin1"),
            "body": blob,
        })
        pos = end
    return ents, notes, pos


def taxonomy(name):
    base = name.rsplit(".", 1)[0]
    parts = base.split("_")
    mat, lighting = (parts[0], "_".join(parts[1:])) if len(parts) > 1 else (base, "")
    feats = []
    for f in ("Reflection", "Specular", "Bump", "Lightmapped"):
        if f in mat:
            feats.append(f)
    ntex = len(re.findall(r"Tex\d", mat))
    return {"material": mat, "lighting": lighting, "features": feats, "tex_layers": ntex}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", action="store_true")
    ap.add_argument("--grep")
    a = ap.parse_args()
    ents, notes, pos = parse(SRC)
    total = len(SRC.read_bytes())
    print(f"着色器 {len(ents)} 个")
    ext = {}
    for e in ents:
        ext[e["ext"]] = ext.get(e["ext"], 0) + 1
    print(f"扩展名分布: {dict(sorted(ext.items(), key=lambda kv: -kv[1]))}")
    bad = [e["name"] for e in ents if not NAME_OK.fullmatch(e["name"])]
    print(f"名字不合规的条目 {len(bad)} 个" + (f": {bad[:8]}" if bad else " ✓"))
    print(f"链尾 0x{pos:x} / 文件 {total:,} B  "
          f"{'✓ 精确到文件尾' if pos == total else '✗ 未到文件尾'}")
    breaks = [i for i in range(len(ents) - 1)
              if ents[i]["record_end"] != ents[i + 1]["record_start"]]
    print(f"逐条接续: {len(ents)-1-len(breaks)}/{len(ents)-1} 精确吻合"
          + (f"  ✗ 断点 {breaks[:5]}" if breaks else " ✓"))
    if notes:
        print("注记:", notes)

    vers = {}
    for e in ents:
        v = e["first_line"].split()[0] if e["first_line"] else "?"
        vers[v] = vers.get(v, 0) + 1
    print("首行分布:", dict(sorted(vers.items(), key=lambda kv: -kv[1])[:8]))

    groups = {}
    for e in ents:
        t = taxonomy(e["name"])
        groups.setdefault(t["material"], []).append(t["lighting"])
    print(f"材质族 {len(groups)} 个（含多光照变体）")
    for m, ls in list(sorted(groups.items(), key=lambda kv: -len(kv[1])))[:14]:
        print(f"  {m:<38} {len(ls)} 个变体: {sorted(set(ls))[:5]}")

    if a.grep:
        for e in ents:
            if a.grep.lower() in e["name"].lower():
                print(f"\n### {e['name']}  {e['first_line']}  {e['size']} B")
                print(e["body"].decode("latin1")[:600])
    if a.dump:
        OUT.mkdir(exist_ok=True)
        for e in ents:
            (OUT / e["name"]).write_bytes(e["body"])
        idx = [{k: v for k, v in e.items() if k != "body"} | taxonomy(e["name"]) for e in ents]
        (ROOT / "out_shaders.json").write_text(json.dumps(idx, indent=1))
        print(f"写出 out_shaders/ {len(ents)} 文件 + out_shaders.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
