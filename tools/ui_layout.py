#!/usr/bin/env python3
"""LASR UI layout decoder.

Java 前端里每个控件都是
    this.X.construct(window, stringTable, "AABBCC....")
第三个参数是 **十六进制文本**（A=0,B=1,...,P=15，两位一字节）的二进制布局块。
格式（由原生解析器 java.gui.Component.construct @0x5a0450 → 0x5d4b20 判定，
类型分派 = 跳转表 @0x5d57a0，索引 = type-1）：

    u32  size        # = 整块长度 - 4
    u16  version     # 全部为 7
    u16  0x10        # 固定
    u8   kind        # 控件类型号
    cstr name        # 控件名（= Java 里的字段名）
    cstr template    # 模板/皮肤名（可为空）
    prop*            # 属性表
    0x00             # 属性表结束（其后可跟若干 0 字节填充）

    prop := cstr name | u16 type | payload
    payload 按 type（见 TYPE_SPEC）：
        1,2,4 → 4 字节（2 = float，1/4 = int/颜色）
        6     → 16 字节（4 个 float，UV 或颜色向量）
        3,12,13,14 → cstr + **额外 4 字节**（version >= 7 时；见原生 handler 里的 cmp ...,7）
        0,5,7,8,9,10,11,15,16,17 → cstr

属性名与 `gui/*` 的 setter 同名（"Background.Color_Inactive" → Background.setColor_Inactive，
"onAction" → setonAction(...) 的回调名），可直接对照。

用法:
    python tools/ui_layout.py                 # 解码 out_pseudo 里全部布局 → out_ui_layouts.json
    python tools/ui_layout.py --class mainMenu  # 只看某个前端类的布局
    python tools/ui_layout.py --kind 13        # 只看某类控件
"""
import argparse
import collections
import glob
import json
import os
import re
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLASSES = os.path.join(ROOT, "out_pseudo", "java", "classes")
OUT = os.path.join(ROOT, "out_ui_layouts.json")

ALPHA = {chr(ord("A") + i): i for i in range(16)}
# 类型号 → 载荷规格（"n" 定长 / "s" 字符串(+额外字节)）
TYPE_SPEC = {
    0: ("s", 0), 1: ("n", 4), 2: ("n", 4), 3: ("s", 4), 4: ("n", 4), 5: ("s", 0),
    6: ("n", 16), 7: ("s", 0), 8: ("s", 0), 9: ("s", 0), 10: ("s", 0), 11: ("s", 0),
    12: ("s", 4), 13: ("s", 4), 14: ("s", 4), 15: ("s", 0), 16: ("s", 0), 17: ("s", 0),
}
TYPE_NAME = {1: "int", 2: "float", 4: "color_int", 6: "vec4", }

CALL_RE = re.compile(r'construct\([^,]+,[^,]+,\s*"([A-Za-z0-9@#$|+*/=_;:.\- ]{20,})"\)')
# this.field = new java.gui.Class(
FLD_RE = re.compile(r"this\.(\w+)\s*=\s*new\s+java\.gui\.(\w+)")
# stringTable（UI 文本表）："$N|文字"
STRTBL_RE = re.compile(r'"(\$\d+\|[^"]*)"')


def hexblob(s):
    return bytes((ALPHA[s[i]] << 4) | ALPHA[s[i + 1]] for i in range(0, len(s) - 1, 2))


def rdname(b, off, end, maxlen=200):
    j = b.find(b"\0", off, min(end, off + maxlen))
    if j < 0:
        return None
    s = b[off:j]
    if any(c < 32 or c > 126 for c in s):
        return None
    return s.decode("latin1"), j + 1


def conv(pt, raw):
    if pt == 2:
        return struct.unpack("<f", raw)[0]
    if pt in (1, 4):
        return struct.unpack("<i", raw)[0]
    if pt == 6:
        return list(struct.unpack("<4f", raw))
    return None


def parse(b):
    """解析一个布局块；返回 dict 或 None"""
    end = len(b)
    if end < 12 or int.from_bytes(b[:4], "little") != end - 4:
        return None
    zs = end
    while zs > 8 and b[zs - 1] == 0:
        zs -= 1
    kind = b[8]
    r = rdname(b, 9, end)
    if not r:
        return None
    name, o = r
    r = rdname(b, o, end)
    if not r:
        return None
    template, o = r
    props = []
    while o < zs:
        if b[o] == 0:
            break
        r = rdname(b, o, end, 48)
        if not r:
            return None
        pname, o2 = r
        if o2 + 2 > end:
            return None
        pt = int.from_bytes(b[o2:o2 + 2], "little")
        o3 = o2 + 2
        mode, sz = TYPE_SPEC.get(pt, ("s", 0))
        if mode == "n":
            if o3 + sz > end:
                return None
            raw = b[o3:o3 + sz]
            props.append({"name": pname, "type": pt, "kind": TYPE_NAME.get(pt, "blob"),
                          "value": conv(pt, raw), "raw": raw.hex(" ")})
            o = o3 + sz
        else:
            rs = rdname(b, o3, end)
            if not rs:
                return None
            o = rs[1]
            props.append({"name": pname, "type": pt, "kind": "str", "value": rs[0]})
            if sz:
                if o + sz > end:
                    return None
                o += sz
    return {"kind": kind, "name": name, "template": template, "props": props}


def field_classes(path):
    """文件里 this.field = new java.gui.Class 的映射"""
    t = open(path, encoding="utf-8", errors="replace").read()
    return {m.group(1): m.group(2) for m in FLD_RE.finditer(t)}, t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--class", dest="cls", help="只看某前端类（文件名，不带 .java）")
    ap.add_argument("--kind", type=int, help="只看某控件类型号")
    ap.add_argument("--dump", action="store_true", help="打印人类可读清单")
    a = ap.parse_args()

    records, kind2cls = [], collections.defaultdict(collections.Counter)
    for p in sorted(glob.glob(os.path.join(CLASSES, "**", "*.java"), recursive=True)):
        src = os.path.basename(p)[:-5]
        if a.cls and src != a.cls:
            continue
        text = open(p, encoding="utf-8", errors="replace").read()
        if "construct(" not in text:
            continue
        fmap, _ = field_classes(p)
        for m in CALL_RE.finditer(text):
            res = parse(hexblob(m.group(1)))
            if not res:
                print(f"[!] 解析失败 {src}", file=sys.stderr)
                continue
            res["source"] = src
            res["widget_class"] = fmap.get(res["name"]) or fmap.get(res["name"].split(".")[0])
            if res["widget_class"]:
                kind2cls[res["kind"]][res["widget_class"]] += 1
            records.append(res)

    if a.dump or a.cls or a.kind:
        for r in records:
            if a.kind is not None and r["kind"] != a.kind:
                continue
            print(f"\n=== [{r['source']}] {r['widget_class'] or '?'} kind={r['kind']} "
                  f"name={r['name']!r} template={r['template']!r} ({len(r['props'])} props)")
            for pr in r["props"]:
                print(f"      {pr['name']:<34} {pr['kind']:<9} {pr['value']}")
    else:
        out = {"layouts": records,
               "kind_to_class": {k: dict(v.most_common(3)) for k, v in sorted(kind2cls.items())}}
        with open(OUT, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
        print(f"{len(records)} 个布局 → {OUT}")
        print("控件类型号 → gui 类（票数前三）:")
        for k in sorted(kind2cls):
            top = ", ".join(f"{c}×{n}" for c, n in kind2cls[k].most_common(3))
            names = [r["name"] for r in records if r["kind"] == k][:4]
            print(f"   kind {k:3d}  {top:<58} 例: {names}")


if __name__ == "__main__":
    main()
