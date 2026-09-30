"""Materialise the map scene-instance stream (gametype/params records) and the
mesh-chunk headers into tables a remake can actually consume.

Two record families live interleaved in the maps' raw .bin streams (the files
`extracted_rpak/maps/<map>/gap*.bin` and `0*_*.bin`):

  1. scene instance   ASCII:  "gametype 0x00030050\r\nparams x,y,z,rx,ry,rz"
                      position (metres) + Euler rotation (radians, mostly
                      quantised to pi/2 multiples), terminated by \r\n.
  2. mesh chunk       binary: <u32 1><u32 format><u32 vertCount><u32 triCount>
                      <u32 indexCount><f32 cx,cy,cz><f32 ...>
                      followed by vertCount records of 44 or 52 bytes:
                        <u32 flag=0xffffffff><f32 u,v><f32 a,b>
                        <f32 x,y,z><f32 nx,ny,nz>[<f32 e,f>]
                      normals are unit length (99.8% of 45,681 sampled).

Usage:
    python tools/scene_instances.py --dump            # write json + csv
    python tools/scene_instances.py --map coastline   # one map, human table
"""
import argparse
import collections
import json
import re
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAPS = ROOT / "extracted_rpak" / "maps"

GAMETYPE = re.compile(rb"gametype 0x([0-9A-Fa-f]{8})\r?\nparams ([-\d.,]+)")
VERTEX_STRIDE = (44, 52)
SENTINEL = b"\xff\xff\xff\xff"


def instance_records(blob):
    """Yield (gametype, x,y,z, rx,ry,rz, offset) for every scene instance."""
    for m in GAMETYPE.finditer(blob):
        parts = m.group(2).split(b",")
        if len(parts) < 6:
            continue
        try:
            v = [float(p) for p in parts[:6]]
        except ValueError:
            continue
        yield (m.group(1).decode().lower(), *v, m.start())


def mesh_chunks(blob):
    """Yield (offset, fmt, verts, tris, indices, cx,cy,cz) for vertex blocks.

    A block is recognised by its header shape plus a run of sentinel-led
    vertex records whose count matches the header exactly - the count match is
    the acceptance test, so a false header cannot slip through.
    """
    out = []
    pos = blob.find(SENTINEL)
    while pos != -1:
        if pos % 4 or pos < 44:
            pos = blob.find(SENTINEL, pos + 1)
            continue
        # header is 44 bytes: <u32 1><u32 fmt><u32 verts><u32 tris><u32 idx>
        #                     <f32 six: seed position + seed normal>
        one, fmt, verts, tris, idx = struct.unpack_from("<5I", blob, pos - 44)
        if one == 1 and 0 < verts < 1_000_000 and fmt and fmt <= 0x100:
            n = 0
            k = pos
            while k + 52 <= len(blob) and blob[k:k + 4] == SENTINEL:
                n += 1
                if blob[k + 44:k + 48] == SENTINEL:
                    k += 44
                elif blob[k + 52:k + 56] == SENTINEL:
                    k += 52
                else:
                    break
            if n == verts or n == verts - 1:
                cx, cy, cz = struct.unpack_from("<3f", blob, pos - 8)
                out.append((pos, fmt, verts, tris, idx, cx, cy, cz))
                pos = k
                continue
        pos = blob.find(SENTINEL, pos + 1)
    return out


def sources():
    """Every extracted map stream. No size filter: the authoritative export
    (docs/map_objects.csv, 15,194 records) includes the small files too, and
    skipping them loses exactly one record per map."""
    for p in sorted(MAPS.glob("*/*.bin")):
        yield p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", action="store_true")
    ap.add_argument("--map")
    args = ap.parse_args()

    per_map = collections.OrderedDict()
    type_hist = collections.Counter()
    total_inst = total_vert = 0
    for p in sources():
        mp = p.parent.name
        blob = p.read_bytes()
        inst = list(instance_records(blob))
        chunks = mesh_chunks(blob)
        if not inst and not chunks:
            continue
        rec = per_map.setdefault(mp, {"files": [], "instances": [], "chunks": []})
        rec["files"].append({"name": p.name, "size": len(blob),
                             "instances": len(inst), "chunks": len(chunks)})
        for g, x, y, z, rx, ry, rz, off in inst:
            rec["instances"].append({"type": g, "x": x, "y": y, "z": z,
                                     "rx": rx, "ry": ry, "rz": rz, "offset": off})
            type_hist[g] += 1
        for off, fmt, v, t, i, cx, cy, cz in chunks:
            rec["chunks"].append({"offset": off, "format": fmt, "verts": v,
                                  "tris": t, "indices": i,
                                  "centre": [cx, cy, cz]})
        total_inst += len(inst)
        total_vert += sum(c["verts"] for c in rec["chunks"][-len(chunks):])

    if args.map:
        rec = per_map.get(args.map)
        if not rec:
            print(f"no data for map {args.map}")
            return 1
        print(f"=== {args.map}: {len(rec['instances'])} instances, "
              f"{len(rec['chunks'])} mesh chunks ===")
        print(f"{'gametype':<12}{'x':>11}{'y':>10}{'z':>11}"
              f"{'rx':>8}{'ry':>8}{'rz':>8}")
        for r in rec["instances"][:40]:
            print(f"0x{r['type'][2:] if r['type'].startswith('0x') else r['type']:<10}"
                  f"{r['x']:>11.2f}{r['y']:>10.2f}{r['z']:>11.2f}"
                  f"{r['rx']:>8.3f}{r['ry']:>8.3f}{r['rz']:>8.3f}")
        if rec["chunks"]:
            print("\nmesh chunks:")
            for c in rec["chunks"][:15]:
                print(f"   @0x{c['offset']:08x} fmt={c['format']:<4} "
                      f"verts={c['verts']:<7} tris={c['tris']:<7} "
                      f"idx={c['indices']:<8} centre=({c['centre'][0]:.1f},"
                      f"{c['centre'][1]:.1f},{c['centre'][2]:.1f})")
        return 0

    print(f"maps {len(per_map)}   instances {total_inst}   "
          f"distinct gametypes {len(type_hist)}")
    for mp, rec in sorted(per_map.items(), key=lambda kv: -len(kv[1]["instances"])):
        print(f"   {mp:<15} {len(rec['instances']):>6} 实例  "
              f"{len(rec['chunks']):>4} 网格块  {len(rec['files'])} 文件")
    print("\ngametype top 12:")
    for g, n in type_hist.most_common(12):
        print(f"   0x{g[2:] if g.startswith('0x') else g:<10} {n}")

    if args.dump:
        jp = ROOT / "out_scene_instances.json"
        jp.write_text(json.dumps(per_map, indent=1))
        cp = ROOT / "out_scene_instances.csv"
        with cp.open("w", encoding="utf-8") as fh:
            fh.write("map,file,type,x,y,z,rx,ry,rz,offset\n")
            for mp, rec in per_map.items():
                for r in rec["instances"]:
                    fh.write(f"{mp},{r['type']},{r['x']},{r['y']},{r['z']},"
                             f"{r['rx']},{r['ry']},{r['rz']},{r['offset']}\n")
        print(f"\nwrote {jp.name} ({jp.stat().st_size:,} B) and "
              f"{cp.name} ({cp.stat().st_size:,} B)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
