"""
Stage-1 inventory: summarise the decoded TUFA class set so we know the size and
shape of the scripted (Java-like) game logic before tackling the TREE opcodes.

Writes out_class_inventory.md (generated data; kept out of docs/ on purpose)
"""
import collections
import json
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EX = ROOT / "extracted"
OUT = ROOT / "out_class_inventory.md"


def chunks(data):
    off, res = 12, []
    while off + 8 <= len(data):
        tag = data[off:off + 4].decode("latin1")
        size = struct.unpack_from("<I", data, off + 4)[0]
        res.append((tag, size))
        off += 8 + size
    return res


def main():
    rows = []
    for p in sorted(EX.rglob("*.class")):
        d = p.read_bytes()
        if d[:4] != b"TUFA":
            continue
        cs = dict(chunks(d))
        rows.append({
            "path": str(p.relative_to(EX)),
            "size": len(d),
            "cons": cs.get("CONS", 0),
            "fild": cs.get("FILD", 0),
            "mthd": cs.get("MTHD", 0),
            "clss": cs.get("CLSS", 0),
            "tree": cs.get("TREE", 0),
        })
    tot = {k: sum(r[k] for r in rows) for k in ("size", "cons", "fild", "mthd", "clss", "tree")}
    groups = collections.Counter()
    pkg = collections.Counter()
    for r in rows:
        s = r["path"].replace("\\", "/")
        r["path"] = s
        if s.startswith("java"):
            pkg["java." + (s.split("/")[1] if "/" in s else "?")] += 1
            groups["engine"] += 1
        elif s.startswith("vehicles"):
            groups["vehicle parts"] += 1
        elif s.startswith("maps"):
            groups["map logic"] += 1
        elif s.startswith("_loose"):
            groups["NPC driver AI + shader"] += 1
        else:
            groups["other"] += 1

    lines = ["# Decoded TUFA class inventory", "",
             f"{len(rows)} classes, {tot['size']:,} bytes decoded "
             f"({tot['tree']:,} bytes of TREE node-graph = the executable part).", "",
             "| group | classes |", "|---|---|"]
    for k, v in groups.most_common():
        lines.append(f"| {k} | {v} |")
    lines += ["", "## Engine packages (java/*)", "", "| package | classes |", "|---|---|"]
    for k, v in pkg.most_common():
        lines.append(f"| {k} | {v} |")
    lines += ["", "## Chunk totals", "", "| chunk | bytes |", "|---|---|"]
    for k in ("cons", "fild", "mthd", "clss", "tree"):
        lines.append(f"| {k.upper()} | {tot[k]:,} |")
    lines += ["", "## Largest classes (by TREE size = amount of logic)", "",
              "| class | decoded | TREE | CONS | MTHD |", "|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda r: -r["tree"])[:40]:
        lines.append(f"| {r['path']} | {r['size']:,} | {r['tree']:,} | "
                     f"{r['cons']:,} | {r['mthd']:,} |")
    lines += ["", "## Full class list", ""]
    for r in sorted(rows, key=lambda r: r["path"]):
        lines.append(f"- `{r['path']}` ({r['size']:,} B, TREE {r['tree']:,})")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    (ROOT / "extracted" / "_inventory.json").write_text(json.dumps(rows, indent=1))
    print(f"wrote {OUT}")
    print(json.dumps({k: tot[k] for k in sorted(tot)}, indent=1))
    print("groups:", dict(groups))


if __name__ == "__main__":
    main()
