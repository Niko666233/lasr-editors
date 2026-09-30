#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RPAK 资产盘点：递归枚举全部 .rpk，解出条目 + 命名表 + 覆盖率。

已知结构（本次核实）：

    "RPAK" <u32 index_size> <index[index_size]>
    index:
        +0  u32  依赖包数量
        +4  ...  依赖包名表（长度前缀 + NUL，如 "system.rpk"）
        ... 命名资源表：每条记录
              f32 1.0f        ← 记录标记（索引里唯一的 00 00 80 3f）
              u32 offset      ← 相对数据区（= 8+index_size）的偏移
              u32 size
              u8  len         ← 含结尾 NUL
              char name[len]
    数据区：连续条目链
        <4B tag> <u32 size> <payload[size]>

用法：
  python tools/rpak_export.py --audit                     # 盘点 → out_rpak_inventory.json
  python tools/rpak_export.py --audit --verify DIR        # 与已导出目录比对，列出缺口
"""
from __future__ import annotations

import collections
import json
import re
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GAME = Path(r"C:\Games\LASR")
MAGICS = {b"DDS ": "dds", b"INVO": "invo", b"TUFA": "tufa", b"RPAK": "rpak",
          b"FMod": "fmod", b"OggS": "ogg", b"RIFF": "riff"}
SAFE = re.compile(r"[^A-Za-z0-9_.\-]")


# ── 索引 ────────────────────────────────────────────────────────────────────
def parse_index(d: bytes):
    """→ (index_size, deps[list[str]], named[list[(off,size,name)]])"""
    if d[:4] != b"RPAK":
        return 0, [], []
    n = struct.unpack_from("<I", d, 4)[0]
    idx = d[8:8 + n]
    deps = []
    # 依赖包名表：+0 u32 数量，随后 64 字节槽位里放长度前缀名
    cnt = struct.unpack_from("<I", idx, 0)[0]
    off = 8
    for _ in range(cnt):
        if off >= n or idx[off] == 0:
            break
        ln = idx[off]
        if ln > 120 or off + 1 + ln > n:
            break
        s = idx[off + 1:off + 1 + ln]
        if s[-1:] != b"\x00" or not all(32 <= c < 127 for c in s[:-1]):
            break
        deps.append(s[:-1].decode())
        off += 64 - ((off - 8) % 64)          # 每个依赖名占一个 64 字节槽
    named = []
    for m in re.finditer(re.escape(b"\x00\x00\x80\x3f"), idx):
        h = m.start()
        if h + 13 > n:
            continue
        o, s = struct.unpack_from("<2I", idx, h + 4)
        ln = idx[h + 12]
        if not (1 <= ln <= 120) or h + 13 + ln > n:
            continue
        nm = idx[h + 13:h + 13 + ln]
        if nm[-1] != 0 or not all(32 <= c < 127 for c in nm[:-1]):
            continue
        named.append((o, s, nm[:-1].decode()))
    return n, deps, named


# ── 条目链 ──────────────────────────────────────────────────────────────────
def entry_at(d: bytes, off: int):
    if off + 8 > len(d):
        return None
    tag = d[off:off + 4]
    if not all(0x20 <= c < 0x7F for c in tag):
        return None
    size = int.from_bytes(d[off + 4:off + 8], "little")
    if size == 0 or off + 8 + size > len(d):
        return None
    return tag, size


def walk(d: bytes, start: int, whitelist, reseed: bool = True):
    """Contiguous walk. Any well-formed entry at the cursor is taken; the
    whitelist / payload magic is only used to decide where to reseed after a
    break, so recovering across gaps cannot drag in random bytes.
    reseed=False → 严格模式，遇断即停（用于比较不同起点的链长）。"""
    off, ents, gaps = start, [], []
    while off + 8 <= len(d):
        e = entry_at(d, off)
        if e:
            ents.append((e[0].decode("latin1"), off, e[1]))
            off += 8 + e[1]
            continue
        if not reseed:
            break
        nxt = off + 1
        while nxt + 8 <= len(d):
            e2 = entry_at(d, nxt)
            if e2 and (e2[0] in whitelist or d[nxt + 8:nxt + 12] in MAGICS):
                break
            nxt += 1
        if nxt + 8 > len(d):
            break
        gaps.append((off, nxt))
        off = nxt
    return ents, gaps


def start_of_chain(d: bytes, data: int) -> int:
    """条目链起点：先信数据区开头；若不成链，在有界窗口里找第一个像资源的位置。

    （原实现从数据区扫 8 字节对齐的最长链，O(n²)，49 MB 存档上跑不动 —— 实测超时。）
    """
    if entry_at(d, data) and entry_at(d, data + 8 + entry_at(d, data)[1]):
        return data
    limit = min(len(d) - 12, data + (1 << 20))
    for off in range(data, limit, 4):
        e = entry_at(d, off)
        if not e:
            continue
        if d[off + 8:off + 12] in MAGICS or e[0][:1] in (b"I", b"m"):
            nxt = entry_at(d, off + 8 + e[1])
            if nxt and (d[off + 8 + e[1] + 8:off + 8 + e[1] + 12] in MAGICS
                        or nxt[0][:1] == e[0][:1]):
                return off
    return data


def dir_records(d: bytes):
    """全文扫描目录记录：u16 flags(0x04xx) f32 1.0 u32 file_offset u32 size(+8) u8 len name。

    目录流会跨越索引/数据区边界（frontend.rpk 就是），所以必须扫全文，不能只扫"gap"。
    """
    recs = []
    for m in re.finditer(re.escape(b"\x00\x00\x80\x3f"), d):
        h = m.start()
        if h < 2 or h + 13 > len(d):
            continue
        flags = struct.unpack_from("<H", d, h - 2)[0]
        if not (0x0400 <= flags <= 0x04FF):
            continue
        o, s = struct.unpack_from("<2I", d, h + 4)
        ln = d[h + 12]
        if not (1 <= ln <= 160) or h + 13 + ln > len(d):
            continue
        nm = d[h + 13:h + 13 + ln]
        if nm[-1] != 0 or not all(32 <= c < 127 for c in nm[:-1]):
            continue
        recs.append({"name": nm[:-1].decode(), "off": o, "size": s,
                     "flags": flags, "abs": h})
    return recs


def best_start(d: bytes, data: int, records):
    """条目链起点：数据区开头 / 命名记录里的偏移，取最长的严格链。"""
    cands = {data} | {r["off"] for r in records if r["off"] > 0}
    best = (0, data)
    for c in sorted(cands):
        if not (data <= c < len(d) - 8):
            continue
        chain, _ = walk(d, c, set(), reseed=False)
        if len(chain) > best[0]:
            best = (len(chain), c)
    return best[1] if best[0] >= 2 else start_of_chain(d, data)


def scan_archive(p: Path):
    """→ dict：条目 / 命名记录 / 依赖包 / 覆盖率。两个工具共用这一份解析。"""
    d = p.read_bytes()
    idx_size, deps, named = parse_index(d)
    data = 8 + idx_size
    records = dir_records(d) if d[:4] == b"RPAK" else []
    if d[:4] == b"RPAK":
        cstart = best_start(d, data, records)
        clean, _ = walk(d, cstart, set())
        wl = {t.encode("latin1") for t, _, _ in clean}
        ents, gaps = walk(d, data, wl)
    else:
        ents, gaps = [], []
    # 按条目偏移索引命名记录（记录 size = 条目 size + 8，起止都对齐才算绑定）
    ents_out = []
    for tag, off, size in ents:
        ents_out.append({"tag": tag, "off": off, "size": size,
                         "kind": MAGICS.get(d[off + 8:off + 12], tag)})
    by_off = {}
    for e in ents_out:
        by_off.setdefault(e["off"], []).append(e)
    for r in records:
        for e in by_off.get(r["off"], []):
            if e["size"] == r["size"] - 8:
                e.setdefault("names", []).append(r["name"])
    return {"path": p, "data": d, "index_size": idx_size, "data_start": data,
            "deps": deps, "records": records, "entries": ents_out, "gaps": gaps}


def archive_report(p: Path):
    sc = scan_archive(p)
    d, data, records = sc["data"], sc["data_start"], sc["records"]
    deps, ents, gaps = sc["deps"], sc["entries"], sc["gaps"]
    idx_size = sc["index_size"]
    named = [(r["off"], r["size"], r["name"]) for r in records]
    # 按 offset 索引命名表
    names = {}
    for o, s, nm in named:
        names.setdefault(o, []).append({"name": nm, "size": s})
    out_ents = []
    kinds = collections.Counter()
    for i, e in enumerate(ents):
        kind = e["kind"]
        kinds[kind] += 1
        rec = {"i": i, "tag": e["tag"], "off": e["off"], "size": e["size"], "kind": kind,
               "names": e.get("names", [])}
        if kind == "invo":
            rec["mesh_name"] = invo_name(d, e["off"] + 8, e["size"])
        out_ents.append(rec)
    cov = sum(e["size"] + 8 for e in ents)
    return {
        "archive": p.relative_to(GAME).as_posix(),
        "file_size": len(d),
        "index_size": idx_size,
        "deps": deps,
        "named_records": [{"off": o, "size": s, "name": nm} for o, s, nm in named],
        "entries": out_ents,
        "kind_hist": dict(kinds),
        "entry_count": len(ents),
        "covered_bytes": cov,
        "data_region": len(d) - data,
        "coverage_pct": round(cov / max(len(d) - data, 1) * 100, 3),
        "gaps": [{"off": a, "len": b - a} for a, b in gaps],
        "nested_archives": [r["i"] for r in out_ents if r["kind"] == "rpak"],
        "dir_records": len(records),
        "named_entries": sum(1 for e in out_ents if e["names"]),
    }


def invo_name(d: bytes, off: int, size: int):
    """INVO 头里的名字（第一个长度前缀串）。"""
    blk = d[off:off + size]
    if blk[:4] != b"INVO":
        return None
    try:
        ver, n = struct.unpack_from("<2I", blk, 4)
        pairs = [struct.unpack_from("<2I", blk, 0x0C + 8 * i) for i in range(n)]
    except struct.error:
        return None
    for _, o in pairs:
        if 0 < o < len(blk) - 1:
            ln = blk[o]
            s = blk[o + 1:o + 1 + ln]
            if 1 <= ln <= 64 and all(32 <= c < 127 for c in s):
                return s.decode()
    return None


def main():
    args = sys.argv[1:]
    out = ROOT / "out_rpak_inventory.json"
    files = sorted(GAME.rglob("*.rpk"))
    reports, agg = [], collections.Counter()
    for f in files:
        r = archive_report(f)
        reports.append(r)
        for k, v in r["kind_hist"].items():
            agg[k] += v
    tot = {
        "archives": len(reports),
        "entries": sum(r["entry_count"] for r in reports),
        "covered_bytes": sum(r["covered_bytes"] for r in reports),
        "data_region": sum(r["data_region"] for r in reports),
        "named_records": sum(len(r["named_records"]) for r in reports),
        "nested_archives": sum(len(r["nested_archives"]) for r in reports),
        "by_kind": dict(agg.most_common()),
    }
    tot["coverage_pct"] = round(tot["covered_bytes"] / max(tot["data_region"], 1) * 100, 3)
    doc = {"_source": "tools/rpak_export.py --audit",
           "_format": "RPAK = 'RPAK' u32 index_size index[.]，数据区为 <4B tag><u32 size><payload> 连续链",
           "totals": tot, "archives": reports}
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"存档 {tot['archives']} 个 / 条目 {tot['entries']:,} / 数据区 {tot['data_region']:,} B")
    print(f"条目覆盖 {tot['covered_bytes']:,} B = {tot['coverage_pct']}%  "
          f"命名记录 {tot['named_records']}  嵌套 RPAK {tot['nested_archives']}")
    print("按载荷类型:", json.dumps(tot["by_kind"], ensure_ascii=False))
    print(f"\n→ {out.relative_to(ROOT)}  {out.stat().st_size:,} B")
    worst = sorted(reports, key=lambda r: r["coverage_pct"])[:6]
    print("\n覆盖率最低的 6 个:")
    for r in worst:
        print(f"  {r['archive']:32s} {r['coverage_pct']:6.2f}%  "
              f"条目 {r['entry_count']:4d}  未覆盖 {r['data_region']-r['covered_bytes']:>12,} B")

    if "--verify" in args:
        d = Path(args[args.index("--verify") + 1])
        missing, present = [], 0
        for r in reports:
            dest = d / Path(r["archive"]).with_suffix("")
            for e in r["entries"]:
                f = dest / f"{e['i']:04d}_{SAFE.sub('_', e['tag'])}" 
                hit = [p for p in dest.glob(f"{e['i']:04d}_{SAFE.sub('_', e['tag'])}*") ]
                if hit:
                    present += 1
                else:
                    missing.append((r["archive"], e["i"], e["tag"], e["size"]))
        print(f"\n与 {d.name}/ 比对：已导出 {present}，缺 {len(missing)}")
        for m in missing[:15]:
            print("  缺:", m)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
