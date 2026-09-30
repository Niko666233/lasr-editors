#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LASR 地图数据提取器 —— 把 out_pseudo/maps/<图>/classes/classes/*.java 里的
字段初始化器 + 方法体直线赋值，解析成机器可读 JSON（重制用数据层）。

伪码形态（见 docs/48 §0）：
    // maps.boulevard.classes.Boulevard_track_0.<init>()
    local1 = {"a.spl2", "b.spl2"};
    this.spline = local1;
    local7 = {new java.game.CheckPoint.<init>(new java.lang.Vector3.<init>((-186.2),7.5,36.5), ...), ...};
    this.checkpoints = local7;
    java.gfx.GfxEngine.setFog(0, 1350.0, 10000.0, ...);
    this.skydome[0] = new java.util.resource.RenderRef.<init>(...);

用法：
    python tools/map_data.py                 # 解析全部地图 → out_map_data.json
    python tools/map_data.py boulevard       # 只解析一张图，打印摘要
"""
import os, re, sys, json, glob

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PSEUDO_MAPS = os.path.join(ROOT, "out_pseudo", "maps")

# ---------------------------------------------------------------- 表达式解析

def _balanced(s, i, open_ch, close_ch):
    """s[i] == open_ch 时返回匹配的 close_ch 下标，否则 -1"""
    d = 0
    while i < len(s):
        c = s[i]
        if c == open_ch:
            d += 1
        elif c == close_ch:
            d -= 1
            if d == 0:
                return i
        i += 1
    return -1

def _strip_parens(s):
    s = s.strip()
    while s.startswith("(") and _balanced(s, 0, "(", ")") == len(s) - 1:
        s = s[1:-1].strip()
    return s

def split_top(s, sep=","):
    """在括号/花括号/方括号嵌套为 0 且不在字符串字面量内的位置切分"""
    out, depth, cur, i, in_str = [], 0, [], 0, False
    while i < len(s):
        c = s[i]
        if c == '"' and (i == 0 or s[i - 1] != "\\"):
            in_str = not in_str
        if not in_str:
            if c in "([{":
                depth += 1
            elif c in ")]}":
                depth -= 1
            if c == sep and depth == 0:
                out.append("".join(cur).strip()); cur = []
                i += 1
                continue
        cur.append(c)
        i += 1
    if "".join(cur).strip():
        out.append("".join(cur).strip())
    return out

NUM = re.compile(r"^(?:[-\d.]+)[Ff]?$")
CAST = re.compile(r"^\(\s*([FIS])\s*\)\s*(.+)$", re.S)

def parse_value(s):
    s = _strip_parens(s)
    if not s:
        return None
    # 强制类型转换 ((F)(-1)) / ((I)local1) / ((S)local2)
    m = CAST.match(s)
    if m and m.group(2):
        inner = _strip_parens(m.group(2))
        if NUM.match(inner):
            return float(inner.rstrip("Ff")) if ("." in inner or m.group(1) == "F") else int(float(inner))
        parsed = parse_value(inner)
        if isinstance(parsed, (int, float)):
            return int(parsed) if m.group(1) in "IS" else float(parsed)
        return {"cast": m.group(1), "value": parsed}
    if NUM.match(s):
        return float(s.rstrip("Ff")) if "." in s else int(s)
    if s == "true":  return True
    if s == "false": return False
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        return s[1:-1].replace("\\\\", "\\")
    # 数组字面量
    if s.startswith("{") and _balanced(s, 0, "{", "}") == len(s) - 1:
        body = s[1:-1].strip()
        if not body:
            return []
        return [parse_value(x) for x in split_top(body)]
    # new 表达式  new a.b.C.<init>(args)   /  new [Ltype;[N]
    if s.startswith("new "):
        t = s[4:].strip()
        if t.startswith("["):
            return {"new_array": t.split(";")[0].lstrip("["), "expr": s}
        o = t.find("(")
        if o > 0:
            head = t[:o].strip()
            close = _balanced(t, o, "(", ")")
            args = split_top(t[o + 1:close]) if close > o else []
            cls = head[:-len(".<init>")] if head.endswith(".<init>") else head
            return {"new": cls, "args": [parse_value(a) for a in args]}
        return {"expr": s}
    # 方法调用  a.b.c(args)
    om = re.match(r"^([\w.$]+)\s*\(", s)
    if om:
        o = s.index("(")
        close = _balanced(s, o, "(", ")")
        if close == len(s) - 1:
            return {"call": om.group(1), "args": [parse_value(a) for a in split_top(s[o + 1:close])] if close > o else []}
    # 局部变量 / 常量引用 / 位或表达式
    if re.match(r"^local\d+$", s):
        return {"ref": s}
    if re.match(r"^[\w.$]+(\s*\|\s*[\w.$]+)*$", s):
        return {"const": s}
    return {"expr": s}

def resolve(v, locals_):
    """递归把 {"ref": localN} 换成实际值（含 args 列表内的嵌套引用）"""
    if isinstance(v, dict):
        if set(v) == {"ref"}:
            got = locals_.get(v["ref"], None)
            if got is None:
                return v
            return resolve(got, locals_)
        return {k: resolve(x, locals_) for k, x in v.items()}
    if isinstance(v, list):
        return [resolve(x, locals_) for x in v]
    return v

STMT_ASSIGN = re.compile(r"^(this\.[\w$]+(?:\[[\d]+\])?)\s*=\s*(.+);$")
STMT_LOCAL  = re.compile(r"^(local\d+)\s*=\s*(.+);$")
STMT_CALL   = re.compile(r"^([\w.$]+)\s*\((.*)\);$")

def parse_class_file(path):
    """返回 {fields: {...}, calls: {method: [...]}, methods: [...]}"""
    text = open(path, encoding="utf-8", errors="replace").read()
    # 按 `    // 签名` 切成方法块
    parts = re.split(r"^\s*//\s*([\w.$]+\.\S+)\(.*\)\S*\s*$", text, flags=re.M)
    # parts = [前置, 签名1, 体1, 签名2, 体2, ...]
    out = {"fields": {}, "fields_src": {}, "calls": {}, "methods": []}
    blocks = []
    for i in range(1, len(parts) - 1, 2):
        blocks.append((parts[i], parts[i + 1]))
    for sig, body in blocks:
        out["methods"].append(sig)
        locals_ = {}
        for raw in body.split("\n"):
            line = raw.strip()
            if not line or line.startswith("//"):
                continue
            m = STMT_LOCAL.match(line)
            if m:
                v = parse_value(m.group(2))
                locals_[m.group(1)] = v
                if isinstance(v, dict) and "call" in v:      # local1 = Sound.addRoomBox(...)
                    out["calls"].setdefault(sig, []).append(v)
                continue
            m = STMT_ASSIGN.match(line)
            if m:
                lhs, rhs = m.group(1), m.group(2)
                key = lhs[len("this."):]
                out["fields"][key] = resolve(parse_value(rhs), locals_)
                out["fields_src"][key] = line
                continue
            m = STMT_CALL.match(line)
            if m:
                # 注意：不能用整行（含结尾分号）去 parse，要重建调用表达式；再解析 local 引用
                out["calls"].setdefault(sig, []).append(
                    resolve(parse_value(f"{m.group(1)}({m.group(2)})"), locals_))
    return out

def map_classes(mapname):
    """<map> 目录下的类名（Boulevard.java / Boulevard_track_0.java ...）"""
    d = os.path.join(PSEUDO_MAPS, mapname, "classes", "classes")
    return sorted(glob.glob(os.path.join(d, "*.java"))) if os.path.isdir(d) else []

def build():
    res = {"_source": "out_pseudo/maps/<地图>/classes/classes/*.java（每张图的地图类伪码）",
           "_tool": "tools/map_data.py", "maps": {}}
    for mapname in sorted(os.listdir(PSEUDO_MAPS)):
        files = map_classes(mapname)
        if not files:
            continue
        entry = {"classes": {}}
        for f in files:
            cn = os.path.basename(f)[:-5]
            entry["classes"][cn] = parse_class_file(f)
        res["maps"][mapname] = entry
    return res

def _callee(x):
    return x.get("call", "").split(".")[-1] if isinstance(x, dict) else None

def _calls(c, name):
    return [x for lst in c["calls"].values() for x in lst if _callee(x) == name]

def _v(node, idx=0):
    """取 new(...) 节点的第 idx 个参数"""
    if isinstance(node, dict) and "args" in node and len(node["args"]) > idx:
        return node["args"][idx]
    return None

def _vec(node):
    """{new Vector3, args:[x,y,z]} → [x,y,z]；也吃裸列表"""
    if isinstance(node, dict) and node.get("new", "").endswith("Vector3"):
        return node["args"]
    if isinstance(node, list):
        return node
    return None

def export_tracks(data, routes_json):
    """输出重制直接可用的干净结构 out_map_tracks.json"""
    import math
    routes = {}
    if os.path.exists(routes_json):
        routes = json.load(open(routes_json, encoding="utf-8"))
    routes_ci = {k.lower(): v for k, v in routes.items()}     # 盘上目录小写，类里写的大写
    def real_len(path):
        v = routes_ci.get(path.replace("\\", "/").lower())
        if v is None: return None
        return round(sum(math.dist(s["p0"], s["p1"]) for s in v), 3)

    def sound_records(c):
        """按调用顺序把 addRoomBox/addReverbBox + SetPosition/SetOrientation 合成记录"""
        rooms, revs = [], []
        for lst in c["calls"].values():
            cur = None
            for x in lst:
                f = _callee(x)
                if f == "addRoomBox":
                    cur = {"args": x["args"]}; rooms.append(cur)
                elif f == "addReverbBox":
                    cur = {"args": x["args"]}; revs.append(cur)
                elif f in ("roomSetPosition", "reverbSetPosition"):
                    if cur is not None: cur["pos"] = x["args"][1:]
                elif f in ("roomSetOrientation", "reverbSetOrientation"):
                    if cur is not None: cur["ori"] = x["args"][1:]
        return rooms, revs

    out = {"_source": "out_pseudo/maps/<地图>/classes/classes/*.java + .spl2 实测长度（out_routes.json）",
           "_tool": "tools/map_data.py --export", "maps": {}}
    for m, info in data["maps"].items():
        ent = {"env": {}, "tracks": {}, "banners": [], "sound": {"rooms": [], "reverbs": []}}
        for cn, c in info["classes"].items():
            F = c["fields"]
            if "_track_" in cn:
                cp = F.get("checkpoints", []) or []
                cps = []
                for x in cp:
                    if isinstance(x, dict) and x.get("new") == "java.game.CheckPoint":
                        a = x["args"]
                        cps.append({"pos": _vec(a[0]), "ypr": (a[1]["args"] if len(a) > 1 and isinstance(a[1], dict) else None),
                                    "size": _vec(a[2]) if len(a) > 2 else None})
                grids = [_vec(_v(x, 0)) for x in (F.get("startGrid") or [])]
                var = []
                cs = F.get("complexspline")
                if isinstance(cs, dict) and cs.get("args"):
                    var = [v for v in cs["args"][0] if isinstance(v, str)]
                # 优先级：complexspline 变体（normal/slow/fast/shortcut）
                ent["tracks"][cn.split("_")[-1]] = {
                    "class": cn, "name": F.get("name"),
                    "difficulty_field": F.get("difficulty"), "direction_field": F.get("direction"),
                    "overallLength_field": F.get("overallLength"),   # ⚠ 全部地图同值，模板残留
                    "roadCondition_field": F.get("roadCondition"), "officialBestLap_field": F.get("officialBestLap"),
                    "trackFlags": F.get("trackFlags"),
                    "spline_rescue_shortcut": F.get("spline", []),
                    "spline_variants": var,
                    "spline_length_m": {v: real_len(v) for v in var},
                    "checkpoints": cps, "startGrid": grids,
                    "visualisationBounds": F.get("visualisationBounds"),
                    "routePreviewTexture": (F.get("previewFiles") or c["calls"]) and None,
                    "prepareTrack_calls": c["calls"].get([k for k in c["calls"] if k.endswith("prepareTrack")][0], []) if any(k.endswith("prepareTrack") for k in c["calls"]) else [],
                    "customObjects": [
                        {"gametype_ref": [a for a in x["args"][0]["args"] if isinstance(a, dict) and a.get("new") == "java.util.resource.GameType"],
                         "transform": [a for a in x["args"][0]["args"] if isinstance(a, str) and a.count(",") >= 5],
                         "name": [a for a in x["args"][0]["args"] if isinstance(a, str) and a.count(",") < 5]}
                        for x in _calls(c, "addElement")
                        if x.get("args") and isinstance(x["args"][0], dict) and x["args"][0].get("new") == "java.util.resource.GameRef"],
                }
                continue
            if cn.endswith("_b"):
                ent["env"]["_b_variant"] = F
                continue
            # 地图主类
            ent["name"] = F.get("name")
            ent["trackFlags"] = F.get("trackFlags")
            ent["bounds"] = [F.get("VisualisationBounds_min"), F.get("VisualisationBounds_max")]
            ent["previewFiles"] = F.get("previewFiles")
            ent["winningSceneLocation"] = F.get("winningSceneLocation")
            ent["blimpCamPos"] = F.get("blimpCamPos")
            ent["todNames"] = F.get("todNames")
            ent["timeLimit"] = F.get("timeLimit")
            ent["totalSpeedTraps"] = F.get("totalSpeedTraps")
            ent["sun"] = F.get("sun")
            ent["skydome"] = [F[k] for k in sorted(F) if k.startswith("skydome[")]
            ent["citynoise"] = F.get("citynoise")
            for fn in ["setFog", "setWater", "setDirtType", "setDirtLevel", "setGlowThreshold",
                       "setEnvmapIntensity", "setReflectorColor", "setShadowColor", "setGlobalCubemap",
                       "setShadowmap", "setLightlet", "setLight", "preparetrack"]:
                v = _calls(c, fn)
                if v: ent["env"][fn] = v
            ent["banners"] = [{"args": x["args"][0]["args"]}
                              for x in _calls(c, "addElement")
                              if x.get("args") and isinstance(x["args"][0], dict) and x["args"][0].get("new") == "java.game.Trigger"]
            rooms, revs = sound_records(c)
            ent["sound"]["rooms"] = rooms
            ent["sound"]["reverbs"] = revs
            ent["music"] = [x["args"] for x in _calls(c, "changeMusicSet")]
            ent["customObjects_gametype"] = [x["args"] for x in _calls(c, "addElement")
                                            if x.get("args") and isinstance(x["args"][0], dict) and x["args"][0].get("new") == "java.util.resource.GameRef"]
        if ent["tracks"] or "name" in ent or ent["env"]:
            out["maps"][m] = ent
    return out

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--export":
        data = build()
        tr = export_tracks(data, os.path.join(ROOT, "out_routes.json"))
        out = os.path.join(ROOT, "out_map_tracks.json")
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(tr, fh, ensure_ascii=False, indent=1)
        ncp = sum(len(t["checkpoints"]) for m in tr["maps"].values() for t in m["tracks"].values())
        nbn = sum(len(m["banners"]) for m in tr["maps"].values())
        nsnd = sum(len(m["sound"]["rooms"]) + len(m["sound"]["reverbs"]) for m in tr["maps"].values())
        print(f"out_map_tracks.json: {len(tr['maps'])} 张图 / 检查点 {ncp} 个 / 横幅 {nbn} 个 / 声学盒 {nsnd} 个")
        sys.exit(0)
    if len(sys.argv) > 1:
        m = sys.argv[1]
        info = build()["maps"].get(m)
        if not info:
            print("没这张图:", m); sys.exit(1)
        for cn, cd in info["classes"].items():
            print(f"### {cn}  fields={len(cd['fields'])} methods={len(cd['methods'])} calls={len(cd['calls'])}")
            for k, v in cd["fields"].items():
                s = json.dumps(v, ensure_ascii=False)
                print(f"   {k} = {s[:220]}")
    else:
        data = build()
        # 统计
        nm = len(data["maps"])
        ncls = sum(len(m["classes"]) for m in data["maps"].values())
        cp = sum(1 for m in data["maps"].values() for c in m["classes"].values()
                 if "checkpoints" in c["fields"])
        out = os.path.join(ROOT, "out_map_data.json")
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=1)
        print(f"地图 {nm} 张 / 类 {ncls} 个 / 含 checkpoints 的类 {cp} 个 → {out}")
