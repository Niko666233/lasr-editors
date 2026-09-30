"""Identify the replay frame channels by physical cross-correlation.

The .rpl frame format is fully decoded (docs/54 §3.3.1) but several fields only
have a *width*, not a meaning.  This tool reconstructs the kinematics from the
decoded frames and tests each unknown field against them, so a meaning is only
reported when a correlation actually supports it.

Step 1 establishes the quaternion convention: the body axes rotated to world are
compared against the path tangent (smoothed central difference of the position)
and against world up.  A car's "forward" body axis must line up with the tangent
(cos ~ 1) -- that is the test, not an assumption.

Step 2 derives speed / yaw rate / lateral acceleration / slip angle and
correlates the unknown frame fields (mask1 bit0 and bit1 float triples, mask2
bytes, the single u32, and the 4 x 6 B wheel records) with them.

Usage:
    python tools/replay_dynamics.py samples/W_Brightwood_St-1.rpl [--json out.json]
"""
import argparse
import json
import math
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rpl_parse import decode_frame, u32, f32          # noqa: E402


# ------------------------------------------------------------------ math helpers

def quat_to_basis(q):
    """(x, y, z, w) -> the three rotated body axes as world vectors."""
    x, y, z, w = q
    n = math.sqrt(x * x + y * y + z * z + w * w) or 1.0
    x, y, z, w = x / n, y / n, z / n, w / n
    return [
        (1 - 2 * (y * y + z * z), 2 * (x * y + z * w), 2 * (x * z - y * w)),
        (2 * (x * y - z * w), 1 - 2 * (x * x + z * z), 2 * (y * z + x * w)),
        (2 * (x * z + y * w), 2 * (y * z - x * w), 1 - 2 * (x * x + y * y)),
    ]


def dot(a, b):
    return sum(p * q for p, q in zip(a, b))


def quat_mul(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw,
            aw * bw - ax * bx - ay * by - az * bz)


def quat_conj(q):
    return (-q[0], -q[1], -q[2], q[3])


def axis_angle(q):
    """Unit quaternion -> (unit axis, angle in radians)."""
    x, y, z, w = q
    n = math.sqrt(x * x + y * y + z * z + w * w) or 1.0
    x, y, z, w = x / n, y / n, z / n, w / n
    if w < 0:                                   # shortest rotation
        x, y, z, w = -x, -y, -z, -w
    s = math.sqrt(max(0.0, 1.0 - w * w))
    if s < 1e-9:
        return [0.0, 0.0, 0.0], 0.0
    return [x / s, y / s, z / s], 2.0 * math.acos(max(-1.0, min(1.0, w)))


def norm(v):
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v] if n > 1e-12 else [0.0, 0.0, 0.0]


def load_track(path):
    """Decode every vehicle blob of a .rpl into a timeline."""
    d = Path(path).read_bytes()
    tracks = []
    p = 0x0C + 24
    while p + 8 <= len(d) - 12:
        tag = d[p:p + 4]
        if tag not in (b"RPLH", b"RPLO"):
            break
        if tag == b"RPLH":
            p += 8 + u32(d, p + 4)
            continue
        if u32(d, p + 8) != 5:
            break
        b0 = p + 12
        slen = u32(d, b0 + 8)
        q = b0 + 12 + slen
        nlen = u32(d, q)
        name = d[q + 4:q + 4 + nlen].split(b"\x00")[0].decode("latin1")
        q += 4 + nlen + 4 + 4                       # slot + native version
        count = u32(d, q)
        q += 4
        frames = []
        for _ in range(count):
            f = decode_frame(d, q)
            frames.append(f)
            q += f["size"]
        extra_count = u32(d, q)
        q += 4
        extra = []
        for i in range(extra_count):
            extra.append({"type": u32(d, q + 36 * i),
                          "values": [round(f32(d, q + 36 * i + 4 + 4 * k), 5) for k in range(8)]})
        q += 36 * extra_count
        tracks.append({"name": name, "frames": frames, "extra_count": extra_count,
                       "extra_records": extra})
        p = q
    return tracks


# ------------------------------------------------------------------ kinematics

def kinematics(frames, smooth=5):
    """Per-frame speed (units/s), tangent, yaw rate, lateral accel, slip angle."""
    n = len(frames)
    t = [f["time_s"] for f in frames]
    pos = [f["pos"] for f in frames]
    out = []
    for i in range(n):
        a, b = max(0, i - smooth), min(n - 1, i + smooth)
        dt = t[b] - t[a]
        if dt <= 0:
            out.append(None)
            continue
        v = [(pos[b][k] - pos[a][k]) / dt for k in range(3)]
        speed = math.sqrt(sum(x * x for x in v))
        out.append({"v": v, "speed": speed, "tangent": norm(v)})
    # yaw rate + lateral accel from the tangent's rotation
    for i, row in enumerate(out):
        j = min(n - 1, i + 5)
        k = max(0, i - 5)
        if row is None or out[j] is None or out[k] is None:
            continue
        dt = t[j] - t[k]
        c = dot(out[k]["tangent"], out[j]["tangent"])
        c = max(-1.0, min(1.0, c))
        ang = math.acos(c)
        row["yaw_rate"] = ang / dt if dt > 0 else 0.0
        row["lat_accel"] = row["speed"] * row["yaw_rate"]
    # angular velocity (body + world) and linear acceleration from the samples
    for i, row in enumerate(out):
        if i == 0 or row is None or out[i - 1] is None:
            continue
        dt = t[i] - t[i - 1]
        if dt <= 0:
            continue
        q0, q1 = frames[i - 1]["quat"], frames[i]["quat"]
        # relative rotation q0^-1 * q1 is expressed in the *body* frame
        rel_body = quat_mul(quat_conj(q0), q1)
        rel_world = quat_mul(q1, quat_conj(q0))
        for tag, rel in (("w_body", rel_body), ("w_world", rel_world)):
            ax, ang = axis_angle(rel)
            row[tag] = [a * ang / dt for a in ax]
        prev = out[i - 1]
        if prev is not None:
            row["accel"] = [(row["v"][k2] - prev["v"][k2]) / dt for k2 in range(3)]
    return out


def analyse(track):
    frames = track["frames"]
    kin = kinematics(frames)
    n = len(frames)

    # ---- step 1: which body axis is "forward" (must track the path tangent)?
    axes = ["X", "Y", "Z"]
    score = {a: [] for a in axes}
    up_score = {a: [] for a in axes}
    for i in range(n):
        if kin[i] is None or kin[i]["speed"] < 0.5:
            continue
        basis = quat_to_basis(frames[i]["quat"])
        tan = kin[i]["tangent"]
        for k, a in enumerate(axes):
            score[a].append(abs(dot(basis[k], tan)))
            up_score[a].append(abs(dot(basis[k], [0.0, 1.0, 0.0])))
    report = {"frames": n, "forward_axis_test": {}, "up_axis_test": {}}
    for a in axes:
        if score[a]:
            report["forward_axis_test"][a] = {
                "mean_abs_cos_with_tangent": round(sum(score[a]) / len(score[a]), 4),
                "samples": len(score[a]),
            }
            report["up_axis_test"][a] = round(sum(up_score[a]) / len(up_score[a]), 4)
    best_axis = max(axes, key=lambda a: report["forward_axis_test"].get(a, {}).get(
        "mean_abs_cos_with_tangent", 0))
    report["forward_axis"] = best_axis

    # ---- step 2: rotate the body axes, sign-correct, correlate
    f_axis = axes.index(best_axis)
    signed = []
    for i in range(n):
        if kin[i] is None or kin[i]["speed"] < 0.5:
            signed.append(None)
            continue
        fb = quat_to_basis(frames[i]["quat"])[f_axis]
        signed.append(1.0 if dot(fb, kin[i]["tangent"]) >= 0 else -1.0)
    pos_sign = sum(s for s in signed if s) or 1.0
    report["forward_sign"] = int(math.copysign(1, pos_sign))

    # slip angle: angle between the body forward axis and the velocity tangent
    slips = []
    for i in range(n):
        if kin[i] is None or kin[i]["speed"] < 1.0:
            continue
        fb = quat_to_basis(frames[i]["quat"])[f_axis]
        fb = [report["forward_sign"] * c for c in fb]
        c = max(-1.0, min(1.0, dot(fb, kin[i]["tangent"])))
        slips.append(math.degrees(math.acos(c)))
    report["slip_angle_deg"] = {
        "mean": round(sum(slips) / len(slips), 2) if slips else None,
        "p95": round(sorted(slips)[int(len(slips) * 0.95)], 2) if slips else None,
    }
    speeds = [k["speed"] for k in kin if k]
    report["speed"] = {"min": round(min(speeds), 3), "max": round(max(speeds), 3),
                       "mean": round(sum(speeds) / len(speeds), 3)}
    return report, kin, signed


# ------------------------------------------------------------------ correlation

def pearson(xs, ys):
    n = len(xs)
    if n < 10:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if sx < 1e-12 or sy < 1e-12:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy)


def correlate_fields(track):
    """Correlate each unknown field with the kinematics, per stable slot.

    Two traps this avoids: (1) mask2 payload bytes do not exist in every frame, so
    the key must be the *slot* (bit index), never the position in the list;
    (2) a key present only in a subset of frames must stay in the sample set
    (dropping the column because one frame lacks it throws away the signal).
    """
    frames = track["frames"]
    kin = kinematics(frames)
    rows = []
    for i, f in enumerate(frames):
        k = kin[i]
        if k is None:
            continue
        v = k["v"]
        body = quat_to_basis(f["quat"])
        row = {"t": f["time_s"], "speed": k["speed"], "yaw_rate": k.get("yaw_rate"),
               "lat_accel": k.get("lat_accel"), "mid": f["mid_f32"]}
        for j in range(3):
            row["v_world%d" % j] = v[j]
            row["v_body%d" % j] = dot(body[j], v)      # body-frame velocity
        for tag in ("w_body", "w_world", "accel"):
            vec = k.get(tag)
            if vec:
                for j in range(3):
                    row["%s%d" % (tag, j)] = vec[j]
        for j, val in enumerate(f["quat"]):
            row["quat%d" % j] = val
        for ch in f["channels"]:
            for j, val in enumerate(ch.get("floats", [])):
                row["%s_f%d" % (ch["chan"], j)] = val
            for j, val in enumerate(ch.get("bytes", [])):
                row["%s_b%d" % (ch["chan"], j)] = val
        for slot, val in zip([b for b in range(6) if f["mask2"] >> b & 1], f["mask2_bytes"]):
            row["m2slot%d" % slot] = val
        for w, wheel in enumerate(f["wheels"]):
            for j, val in enumerate(wheel):
                row["w%d_b%d" % (w, j)] = val
        rows.append(row)

    targets = ["speed", "yaw_rate", "lat_accel"] \
        + ["v_world%d" % j for j in range(3)] + ["v_body%d" % j for j in range(3)] \
        + ["w_body%d" % j for j in range(3)] + ["w_world%d" % j for j in range(3)] \
        + ["accel%d" % j for j in range(3)]
    out = {}
    for key in sorted({k for r in rows for k in r}):
        if key in ("t", "mid") and key == "t":
            continue
        pairs = [(r[key], r) for r in rows if r.get(key) is not None]
        if len(pairs) < 30:
            continue
        out[key] = {"n": len(pairs)}
        for t in targets:
            xs = [r[t] for _, r in pairs if r.get(t) is not None]
            ys = [v for v, r in pairs if r.get(t) is not None]
            c = pearson(xs, ys)
            if c is not None:
                out[key][t] = round(c, 3)
    return out


def mid_field_test(track):
    """Is the single mid u32 (as f32) monotone in time (arc length) or a sawtooth (rpm)?

    Also compares it against the cumulative path length: a distance-like field
    must track it closely; an engine-speed field must not.
    """
    frames = track["frames"]
    t = [f["time_s"] for f in frames]
    mid = [f["mid_f32"] for f in frames]
    dist = [0.0]
    for i in range(1, len(frames)):
        a, b = frames[i - 1]["pos"], frames[i]["pos"]
        dist.append(dist[-1] + math.sqrt(sum((b[k] - a[k]) ** 2 for k in range(3))))
    drops = sum(1 for i in range(1, len(mid)) if mid[i] < mid[i - 1] - 1e-6)
    c_dist = pearson(dist, mid)
    # speed bins -> mid median (an rpm field saturates inside a gear then falls)
    kin = kinematics(frames)
    bins = {}
    for i, k in enumerate(kin):
        if k is None:
            continue
        b = int(k["speed"] // 5) * 5
        bins.setdefault(b, []).append(mid[i])
    return {
        "first_last": [round(mid[0], 3), round(mid[-1], 3)],
        "range": [round(min(mid), 2), round(max(mid), 2)],
        "monotone_increasing": drops == 0,
        "down_steps": drops,
        "corr_with_cumulative_distance": round(c_dist, 3) if c_dist is not None else None,
        "speed_bin_medians": {str(b): round(sorted(v)[len(v) // 2], 1) for b, v in sorted(bins.items())},
    }


def extra_list_stats(track):
    """Column-wise statistics of the extra list records (36 B: u32 + 8 x f32)."""
    d = Path(track.get("path", "")).read_bytes() if track.get("path") else None
    recs = track.get("extra_records") or []
    if not recs:
        return {"count": 0}
    cols = [[] for _ in range(8)]
    for r in recs:
        for j, v in enumerate(r["values"]):
            cols[j].append(v)
    stats = {"count": len(recs), "types": sorted({r["type"] for r in recs})}
    for j, c in enumerate(cols):
        stats["f%d" % j] = {"min": round(min(c), 4), "max": round(max(c), 4),
                            "mean": round(sum(c) / len(c), 4),
                            "monotone": c == sorted(c) or c == sorted(c, reverse=True),
                            "int_like": all(abs(x - round(x)) < 1e-4 for x in c)}
    return stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--json", default=None)
    a = ap.parse_args()
    tracks = load_track(a.file)
    allrep = {}
    for tr in tracks:
        rep, kin, signed = analyse(tr)
        rep["correlations"] = correlate_fields(tr)
        rep["mid_field"] = mid_field_test(tr)
        rep["extra_list"] = extra_list_stats(tr)
        allrep[tr["name"]] = rep
        print("=== %s : %d 帧, extra=%d" % (tr["name"], len(tr["frames"]), tr["extra_count"]))
        print("  前向轴判定: " + ", ".join(
            "%s=%.3f" % (k, v["mean_abs_cos_with_tangent"]) for k, v in rep["forward_axis_test"].items())
            + "  -> 前向轴 = %s (符号 %+d)" % (rep["forward_axis"], rep["forward_sign"]))
        print("  上轴判定: " + ", ".join("%s=%.3f" % (k, v) for k, v in rep["up_axis_test"].items()))
        print("  速度 %.2f..%.2f (均 %.2f)  滑移角 均 %.1f° p95 %.1f°" % (
            rep["speed"]["min"], rep["speed"]["max"], rep["speed"]["mean"],
            rep["slip_angle_deg"]["mean"], rep["slip_angle_deg"]["p95"]))
        print("  相关性（|r| >= 0.5 才列）:")
        for k, v in rep["correlations"].items():
            hits = {t: c for t, c in v.items() if t != "n" and abs(c) >= 0.5}
            if hits:
                print("    %-12s %s" % (k, hits))
        mf = rep["mid_field"]
        print("  中段 u32: %.2f..%.2f  单调=%s(down %d) 与累计里程 r=%s"
              % (mf["range"][0], mf["range"][1], mf["monotone_increasing"],
                 mf["down_steps"], mf["corr_with_cumulative_distance"]))
        print("           速度分箱中位数: %s" % mf["speed_bin_medians"])
        ex = rep["extra_list"]
        if ex.get("count"):
            print("  额外列表 %d 条 type=%s" % (ex["count"], ex["types"]))
            for j in range(8):
                c = ex["f%d" % j]
                print("     f%d: %.4f..%.4f 均 %.4f 单调=%s 整型=%s"
                      % (j, c["min"], c["max"], c["mean"], c["monotone"], c["int_like"]))
    if a.json:
        Path(a.json).write_text(json.dumps(allrep, indent=2, ensure_ascii=False), encoding="utf-8")
        print("\n-> %s" % a.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
