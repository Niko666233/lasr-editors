"""Parse a LASR `.rpl` replay file — container + per-frame decoding.

Recovered from a real recording (`samples/W_Brightwood_St-1.rpl`) plus the
native save/load code (0x4282b0 writer / 0x453af0 vehicle serializer /
0x44d540 frame serializer).  See docs/54_REPLAY_AND_GHOST.md.

Layout (all little-endian):

  SDAT container    "SDAT" + u32 0x00030100 + u32 fileSize + payload + 12 B trailer
                    (payload starts at offset 12; the same wrapper is used by the
                     options / career / controls saves)
  Java header       6 x u32 @0x0C : version, mapId, spline, TOD, gameModeId, driverId
  chunk stream      <4B tag><u32 len>[payload]     tags: RPLH / RPLO / "EOF\\0"
    RPLH            u32 nativeVersion (0x00010100) + f32 totalDurationSeconds
    RPLO            u32 kind (5 = Vehicle) + vehicle blob
    EOF\\0          len 0 -> end of stream
  vehicle blob      41 B written by the Java layer (`java.game.Vehicle.save`):
                      u32 9 | u32 objectId | u32 paramStrLen | paramStr |
                      u32 nameLen | name | u32 slot
                    then the native layer:
                      u32 version (0x01040000) | u32 frameCount | frames |
                      u32 extraCount | extraCount x (u32 + 8 x f32)
  frame             u32 time (f32 seconds)
                    f32 x3   world position (x, y, z),  y = up
                    f32 x4   orientation quaternion (x, y, z, w),  |q| == 1
                    u8 mask1   bit0/1/2 -> 12/12/2 extra bytes; bit4-7 = data
                    u8 mask2   bits 0-5 -> one byte each; bits 6-7 carry no byte
                    u32        single value (sample: f32 51.1 .. 781.6)
                    u8 rounds  always 4 in the sample (four wheels)
                    rounds x 6 B quantified wheel values

Verified on the sample: 476 / 519 frames tile their regions with zero residual,
|quaternion| == 1.00000 in every frame, timestamps monotone 0.0 -> 52.6581 s
(dt median 0.1009 s ~ 10 Hz).

Usage:
    python tools/rpl_parse.py <file.rpl> [--json out.json] [--frames N]
"""
import argparse
import hashlib
import json
import struct
import sys
from collections import Counter
from pathlib import Path

KNOWN_VERSIONS = (0x01080000, 0x01050000, 0x11070000)
SDAT_MAGIC = b"SDAT"
SDAT_TRAILER = 12


def u32(d, o):
    return struct.unpack_from("<I", d, o)[0]


def f32(d, o):
    return struct.unpack_from("<f", d, o)[0]


def frame_size(d, o):
    """(size, mask1, mask2, rounds) of the frame at offset `o`."""
    q = o + 32                                    # u32 time + 3 pos + 4 quat
    m1 = d[q]
    q += 1
    q += 12 * bool(m1 & 1) + 12 * bool(m1 & 2) + 2 * bool(m1 & 4)
    m2 = d[q]
    q += 1
    q += bin(m2 & 0x3F).count("1")                # bits 6/7 carry no byte
    q += 4                                        # single value
    rounds = d[q]
    q += 1
    q += 6 * rounds
    return q - o, m1, m2, rounds


def decode_frame(d, o):
    size, m1, m2, rounds = frame_size(d, o)
    q = o + 32
    q += 1                                        # the mask1 byte itself
    ch = []
    if m1 & 1:
        ch.append({"chan": "m1bit0", "floats": [round(f32(d, q + 4 * i), 6) for i in range(3)]})
        q += 12
    if m1 & 2:
        ch.append({"chan": "m1bit1", "floats": [round(f32(d, q + 4 * i), 6) for i in range(3)]})
        q += 12
    if m1 & 4:
        ch.append({"chan": "m1bit2", "bytes": list(d[q:q + 2])})
        q += 2
    m2 = d[q]
    q += 1
    n = bin(m2 & 0x3F).count("1")
    m2b = list(d[q:q + n])
    q += n
    mid = f32(d, q)
    q += 4
    rounds = d[q]
    q += 1
    return {
        "offset": o,
        "size": size,
        "time_s": round(f32(d, o), 4),
        "pos": [round(f32(d, o + 4 + 4 * i), 4) for i in range(3)],
        "quat": [round(f32(d, o + 16 + 4 * i), 6) for i in range(4)],
        "mask1": m1,
        "channels": ch,
        "mask2": m2,
        "mask2_bytes": m2b,
        "mid_f32": round(mid, 4),
        "rounds": rounds,
        "wheels": [list(d[q + 6 * k:q + 6 * k + 6]) for k in range(rounds)],
    }


def parse(path, max_frames=None):
    d = Path(path).read_bytes()
    out = {"file": str(path), "size": len(d), "md5": hashlib.md5(d).hexdigest()}
    if d[:4] != SDAT_MAGIC:
        raise SystemExit("not a SDAT file: %r" % d[:4])
    sdat_ver, sdat_size = struct.unpack_from("<II", d, 4)
    out["sdat"] = {
        "version_bytes": "0x%08x" % sdat_ver,
        "declared_size": sdat_size,
        "size_matches": sdat_size == len(d),
        "trailer": d[-SDAT_TRAILER:].hex(" "),
    }

    names = ["version", "mapId", "spline", "TOD", "gameModeId", "driverId"]
    hdr = dict(zip(names, struct.unpack_from("<6I", d, 0x0C)))
    hdr["version_hex"] = "0x%08x" % hdr["version"]
    hdr["version_known"] = hdr["version"] in KNOWN_VERSIONS
    out["java_header"] = hdr
    driver_id = hdr["driverId"]

    end_of_stream = len(d) - SDAT_TRAILER
    chunks = []
    p = 0x0C + 24
    while p + 8 <= end_of_stream:
        tag = d[p:p + 4]
        if tag == b"EOF\x00":
            chunks.append({"offset": p, "tag": "EOF", "len": u32(d, p + 4)})
            break
        if tag not in (b"RPLH", b"RPLO"):
            chunks.append({"offset": p, "tag": "unknown:%r" % tag})
            break
        length = u32(d, p + 4)
        c = {"offset": p, "tag": tag.decode(), "len": length}
        if tag == b"RPLH":
            c["native_version"] = "0x%08x" % u32(d, p + 8)
            c["duration_s"] = round(f32(d, p + 12), 4)
            chunks.append(c)
            p += 8 + length
            continue
        # RPLO: payload = u32 resource kind + the resource's own blob.  The blob is
        # self-describing (the frame count lives inside it), so there is no outer length.
        c["resource_kind"] = u32(d, p + 8)
        if c["resource_kind"] != 5:
            c["note"] = "non-vehicle: generic reference-field writer (0x403a80), shape unknown"
            chunks.append(c)
            break
        b0 = p + 12
        fmt, oid, slen = struct.unpack_from("<3I", d, b0)
        params = d[b0 + 12:b0 + 12 + slen].split(b"\x00")[0].decode("latin1")
        q = b0 + 12 + slen
        nlen = u32(d, q)
        name = d[q + 4:q + 4 + nlen].split(b"\x00")[0].decode("latin1")
        q += 4 + nlen
        slot = u32(d, q)
        q += 4
        c.update({
            "blob_format": fmt, "object_id": "0x%08x" % oid, "name": name, "slot": slot,
            "param_string": params, "java_header_bytes": q - b0,
        })
        toks = params.split()
        if "d" in toks:
            c["param_driver_id"] = int(toks[toks.index("d") + 1])
            c["param_driver_id_matches"] = str(c["param_driver_id"]) == str(driver_id)
        if "r" in toks and "d" in toks:
            c["param_r_ids"] = [int(t) for t in toks[toks.index("r") + 1:toks.index("d")] if t.isdigit()]
        if "s" in toks:
            c["param_s"] = int(toks[toks.index("s") + 1])
        c["native_version"] = "0x%08x" % u32(d, q)
        count = u32(d, q + 4)
        q += 8
        c["frame_count"] = count
        c["frame_region_start"] = q
        frames = []
        for i in range(count):
            if max_frames is not None and i >= max_frames:
                break
            if q + 32 > end_of_stream:
                c["truncated_at_frame"] = i
                break
            frames.append(decode_frame(d, q))
            q += frames[-1]["size"]
        c["frame_region_end"] = q
        c["frames"] = frames
        if frames:
            ts = [f["time_s"] for f in frames]
            c["frames_summary"] = {
                "decoded": len(frames),
                "size_histogram": dict(Counter(f["size"] for f in frames).most_common()),
                "time_first_last": [ts[0], ts[-1]],
                "time_monotonic": all(ts[i] <= ts[i + 1] + 1e-6 for i in range(len(ts) - 1)),
                "quat_norm_ok": all(abs(sum(v * v for v in f["quat"]) - 1) < 1e-4 for f in frames),
                "mask1_set": sorted({f["mask1"] for f in frames}),
                "mask2_set": sorted({f["mask2"] for f in frames}),
                "rounds_set": sorted({f["rounds"] for f in frames}),
            }
        extra = u32(d, q)
        q += 4
        c["extra_count"] = extra
        c["extra_records"] = [
            {"type": u32(d, q + 36 * i),
             "values": [round(f32(d, q + 36 * i + 4 + 4 * k), 4) for k in range(8)]}
            for i in range(extra)
        ]
        q += 36 * extra
        c["blob_end"] = q
        chunks.append(c)
        p = q
    out["chunks"] = chunks
    return out


def show(o):
    print("%s  %d B  md5=%s" % (o["file"], o["size"], o["md5"]))
    s = o["sdat"]
    print("  SDAT  version=%s  size=%d (一致=%s)  尾=%s"
          % (s["version_bytes"], s["declared_size"], s["size_matches"], s["trailer"]))
    h = o["java_header"]
    print("  Java 头  version=%s(已知=%s) mapId=%s spline=%d TOD=%d gameModeId=%d driverId=%d"
          % (h["version_hex"], h["version_known"], h["mapId"], h["spline"], h["TOD"],
             h["gameModeId"], h["driverId"]))
    for c in o["chunks"]:
        if c["tag"] == "RPLH":
            print("  RPLH @0x%x  nativeVersion=%s  时长=%.4f s"
                  % (c["offset"], c["native_version"], c["duration_s"]))
        elif c["tag"] == "RPLO" and c.get("resource_kind") == 5:
            print("  RPLO @0x%x  kind=5  objId=%s  name=%r  slot=%d  Java头=%d B"
                  % (c["offset"], c["object_id"], c["name"], c["slot"], c["java_header_bytes"]))
            print("        param: %s%s" % (c["param_string"][:110],
                                           "..." if len(c["param_string"]) > 110 else ""))
            print("        nativeVersion=%s  帧数=%d  d<->头一致=%s"
                  % (c["native_version"], c["frame_count"], c["param_driver_id_matches"]))
            su = c.get("frames_summary")
            if su:
                print("        帧长分布=%s" % su["size_histogram"])
                print("        时间 %.4f..%.4f 单调=%s  |q|=1 全帧=%s"
                      % (su["time_first_last"][0], su["time_first_last"][1],
                         su["time_monotonic"], su["quat_norm_ok"]))
                print("        mask1=%s mask2=%s 轮数=%s"
                      % (su["mask1_set"], su["mask2_set"], su["rounds_set"]))
                f = c["frames"][0]
                print("        帧0: 长%d 时间=%.4f 位置=%s 四元数=%s mid=%.2f 轮=%s"
                      % (f["size"], f["time_s"], f["pos"], f["quat"], f["mid_f32"], f["wheels"]))
            print("        帧区 @0x%x..0x%x  额外列表=%d 条  块终点 @0x%x"
                  % (c["frame_region_start"], c["frame_region_end"],
                     c["extra_count"], c["blob_end"]))
            if c["extra_records"]:
                print("        额外列表第 0 条: type=%d %s"
                      % (c["extra_records"][0]["type"], c["extra_records"][0]["values"]))
        elif c["tag"] == "RPLO":
            print("  RPLO @0x%x  kind=%s (非车辆)" % (c["offset"], c.get("resource_kind")))
        else:
            print("  %s @0x%x  len=%s" % (c["tag"], c["offset"], c.get("len")))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--json", default=None)
    ap.add_argument("--frames", type=int, default=0, help="decode only the first N frames")
    a = ap.parse_args()
    o = parse(a.file, max_frames=a.frames or None)
    show(o)
    if a.json:
        Path(a.json).write_text(json.dumps(o, indent=2, ensure_ascii=False), encoding="utf-8")
        print("\n-> %s" % a.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
