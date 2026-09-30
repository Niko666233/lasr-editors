"""Render a decoded .rpl replay into a self-contained HTML viewer.

Reads the real recording, decodes every frame with rpl_parse, derives the
kinematics with replay_dynamics, and emits one HTML file that draws the two cars
driving the track from a top-down view with a time scrubber and a telemetry
panel.  It doubles as a visual check of the reverse-engineered format: if the
output looks like a car driving a racing line, the decode is right.

Usage:
    python tools/replay_viewer.py samples/W_Brightwood_St-1.rpl [--out preview_tmp/replay_viewer.html]
"""
import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from replay_dynamics import kinematics, load_track, quat_to_basis   # noqa: E402

RAD2RPM = 9.5493


def build_timeline(track):
    frames = track["frames"]
    kin = kinematics(frames)
    body_axis = 2                       # verified: forward = local Z (docs/54 §3.3.2)
    sign = -1
    tl = []
    for i, f in enumerate(frames):
        b = quat_to_basis(f["quat"])
        fwd = [sign * c for c in b[body_axis]]
        yaw = math.degrees(math.atan2(fwd[2], fwd[0]))
        k = kin[i] or {}
        tl.append({
            "t": round(f["time_s"], 3),
            "x": round(f["pos"][0], 2), "z": round(f["pos"][2], 2),
            "y": round(f["pos"][1], 2),
            "yaw": round(yaw, 1),
            "sp": round(k.get("speed", 0.0), 2),
            "rpm": round(f["mid_f32"] * RAD2RPM),
            "m1": f["mask1"], "m2": f["mask2"],
            "wh": [w[0] for w in f["wheels"]],
        })
    # channels only stored in some frames: attach the vectors when present
    for i, f in enumerate(frames):
        for ch in f["channels"]:
            if ch["chan"] == "m1bit0":
                tl[i]["v"] = [round(v, 2) for v in ch["floats"]]
            elif ch["chan"] == "m1bit1":
                tl[i]["w"] = [round(v, 3) for v in ch["floats"]]
    return tl


HTML = """<!doctype html>
<meta charset="utf-8">
<style>
  .rp-wrap { display: flex; gap: 14px; align-items: flex-start; flex-wrap: wrap; }
  canvas { border: 1px solid var(--border); border-radius: 8px; }
  .rp-side { min-width: 210px; font-size: 13px; }
  .rp-h { font-weight: 600; margin: 0 0 6px; }
  .rp-row { display: flex; justify-content: space-between; gap: 10px; padding: 2px 0;
            border-bottom: 1px solid var(--border); }
  .rp-row span:last-child { font-variant-numeric: tabular-nums; }
  .rp-ctl { display: flex; align-items: center; gap: 8px; margin-top: 10px; }
  input[type=range] { flex: 1; accent-color: var(--accent); }
  button { background: none; border: 1px solid var(--border); color: var(--foreground);
           border-radius: 6px; padding: 3px 10px; cursor: pointer; }
  .rp-legend { display: flex; gap: 12px; font-size: 12px; margin-top: 6px; }
  .sw { display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 4px; }
  .rp-bar { height: 6px; background: var(--border); border-radius: 3px; overflow: hidden; }
  .rp-bar > i { display: block; height: 100%; background: var(--accent); }
</style>
<div class="rp-wrap">
  <canvas id="cv" width="620" height="440"></canvas>
  <div class="rp-side">
    <p class="rp-h" id="hdr"></p>
    <div class="rp-row"><span>时间</span><span id="t">0.00 s</span></div>
    <div class="rp-row"><span>车速</span><span id="sp">0.0 u/s</span></div>
    <div class="rp-row"><span>转速</span><span id="rpm">0 rpm</span></div>
    <div class="rp-row"><span>朝向</span><span id="yaw">0°</span></div>
    <div class="rp-row"><span>文件位置 (x, z)</span><span id="pos">-</span></div>
    <div class="rp-row"><span>mask1 / mask2</span><span id="mask">-</span></div>
    <div class="rp-row"><span>通道</span><span id="chan">-</span></div>
    <p class="rp-h" style="margin-top:12px">四轮轮速字节</p>
    <div id="wheels"></div>
    <div class="rp-ctl">
      <button id="pp">暂停</button>
      <input type="range" id="sc" min="0" max="100" step="0.1" value="0">
      <span id="rate" style="font-variant-numeric:tabular-nums">1.0x</span>
    </div>
    <div class="rp-legend">
      <span><i class="sw" style="background:var(--accent)"></i>玩家</span>
      <span><i class="sw" style="background:var(--muted-foreground)"></i>AI 对手</span>
      <span><i class="sw" style="background:var(--border)"></i>轨迹</span>
    </div>
  </div>
</div>
<script>
const DATA = __DATA__;
const cv = document.getElementById('cv'), ctx = cv.getContext('2d');
const track = DATA.tracks;
const all = track.flatMap(t => t.frames);
const xs = all.map(f => f.x), zs = all.map(f => f.z);
const minx = Math.min(...xs), maxx = Math.max(...xs), minz = Math.min(...zs), maxz = Math.max(...zs);
const pad = 24, sc = Math.min((cv.width - 2*pad) / Math.max(1e-6, maxx - minx),
                              (cv.height - 2*pad) / Math.max(1e-6, maxz - minz));
const P = (f) => [pad + (f.x - minx) * sc, cv.height - pad - (f.z - minz) * sc];
const t0 = Math.min(...all.map(f => f.t)), t1 = Math.max(...all.map(f => f.t));
const span = t1 - t0 || 1;
document.getElementById('hdr').textContent = DATA.title;

function css(name, fallback) {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}
function sample(frames, t) {
  let lo = 0, hi = frames.length - 1;
  while (lo < hi) { const m = (lo + hi) >> 1; (frames[m].t < t) ? lo = m + 1 : hi = m; }
  const b = frames[lo], a = frames[Math.max(0, lo - 1)];
  const d = (b.t - a.t) || 1, u = Math.max(0, Math.min(1, (t - a.t) / d));
  return { a: a, b: b, u: u,
           x: a.x + (b.x - a.x) * u, z: a.z + (b.z - a.z) * u,
           yaw: a.yaw + (((b.yaw - a.yaw + 540) % 360) - 180) * u };
}
function car(p, color, label) {
  const [px, py] = P(p);
  ctx.save(); ctx.translate(px, py); ctx.rotate(-p.yaw * Math.PI / 180);
  ctx.fillStyle = color; ctx.beginPath();
  ctx.moveTo(9, 0); ctx.lineTo(-6, -5.5); ctx.lineTo(-6, 5.5); ctx.closePath(); ctx.fill();
  ctx.restore();
  ctx.fillStyle = color; ctx.font = '11px system-ui';
  ctx.fillText(label, px + 8, py - 8);
}
let t = t0, playing = true, rate = 1, last = 0;
const scEl = document.getElementById('sc'), rateEl = document.getElementById('rate');
function draw() {
  const fg = css('--foreground', '#ddd'), mg = css('--muted-foreground', '#888'),
        bd = css('--border', '#444'), ac = css('--accent', '#8ab4f8');
  ctx.clearRect(0, 0, cv.width, cv.height);
  // track (player) polyline
  ctx.strokeStyle = bd; ctx.lineWidth = 2; ctx.beginPath();
  track[0].frames.forEach((f, i) => { const [x, y] = P(f); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
  ctx.stroke();
  if (track[1]) {
    ctx.strokeStyle = bd; ctx.setLineDash([3, 3]); ctx.beginPath();
    track[1].frames.forEach((f, i) => { const [x, y] = P(f); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
    ctx.stroke(); ctx.setLineDash([]);
  }
  const seq = [['#accent', ac], ['opp', mg]];
  track.forEach((tr, i) => {
    const p = sample(tr.frames, t);
    car(p, i === 0 ? ac : mg, tr.name);
  });
  const p0 = sample(track[0].frames, t);
  const near = track[0].frames.reduce((best, f) =>
      Math.abs(f.t - t) < Math.abs(best.t - t) ? f : best, track[0].frames[0]);
  document.getElementById('t').textContent = t.toFixed(2) + ' s';
  document.getElementById('sp').textContent = near.sp.toFixed(2) + ' u/s';
  document.getElementById('rpm').textContent = near.rpm + ' rpm';
  document.getElementById('yaw').textContent = p0.yaw.toFixed(1) + '°';
  document.getElementById('pos').textContent = near.x.toFixed(1) + ', ' + near.z.toFixed(1);
  document.getElementById('mask').textContent = '0x' + near.m1.toString(16).padStart(2, '0') +
      ' / 0x' + near.m2.toString(16).padStart(2, '0');
  const chans = [];
  if (near.v) chans.push('v=[' + near.v.join(', ') + ']');
  if (near.w) chans.push('ω=[' + near.w.join(', ') + ']');
  document.getElementById('chan').textContent = chans.length ? chans.join('  ') : '（无附加通道）';
  document.getElementById('wheels').innerHTML = near.wh.map((v, i) =>
      '<div class="rp-bar" style="margin:3px 0"><i style="width:' + (v / 255 * 100).toFixed(0) + '%"></i></div>'
      ).join('') + '<div style="font-size:12px;color:' + mg + '">' + near.wh.join(' / ') + '</div>';
  scEl.value = ((t - t0) / span * 100).toFixed(2);
}
function loop(ts) {
  if (playing) {
    if (last) { t += (ts - last) / 1000 * rate; if (t > t1) t = t0; }
    last = ts; draw();
  } else { last = ts; }
  requestAnimationFrame(loop);
}
document.getElementById('pp').onclick = (e) => {
  playing = !playing; e.target.textContent = playing ? '暂停' : '播放';
};
scEl.oninput = () => { t = t0 + scEl.value / 100 * span; draw(); };
cv.onclick = () => { rate = rate >= 6 ? 0.2 : rate * 2; rateEl.textContent = rate.toFixed(1) + 'x'; };
draw(); requestAnimationFrame(loop);
</script>
"""


def render_png(tracks, path, size=(900, 700), step=40):
    """Static top-down PNG of the decoded replay (PIL) — doubles as a decode check."""
    from PIL import Image, ImageDraw, ImageFont

    def font(size):
        for cand in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf",
                     "C:/Windows/Fonts/segoeui.ttf"):
            try:
                return ImageFont.truetype(cand, size)
            except Exception:
                continue
        return ImageFont.load_default()

    tl = [build_timeline(t) for t in tracks]
    xs = [f["x"] for t in tl for f in t]
    zs = [f["z"] for t in tl for f in t]
    minx, maxx, minz, maxz = min(xs), max(xs), min(zs), max(zs)
    pad = 46
    W, H = size
    sc = min((W - 2 * pad) / max(1e-6, maxx - minx), (H - 2 * pad) / max(1e-6, maxz - minz))
    img = Image.new("RGB", size, (250, 250, 248))
    dr = ImageDraw.Draw(img)

    def P(f):
        return (pad + (f["x"] - minx) * sc, H - pad - (f["z"] - minz) * sc)

    for i, (t, col) in enumerate(zip(tl, [(40, 90, 200), (150, 150, 150)])):
        pts = [P(f) for f in t]
        dr.line(pts, fill=col, width=3 if i == 0 else 2, joint="curve")
        for f in t[::step]:
            x, y = P(f)
            a = math.radians(-f["yaw"])
            tri = [(x + 11 * math.cos(a + r), y + 11 * math.sin(a + r)) for r in (-0.42, 0, 0.42)]
            dr.polygon(tri, fill=col)
        x, y = P(t[0])
        dr.ellipse([x - 6, y - 6, x + 6, y + 6], outline=col, width=3)
    dr.text((pad, 16), "%s  —  蓝=玩家 %s / 灰=AI %s, 三角=车头朝向, 圆圈=起点" %
            (Path(path).name, tracks[0]["name"], tracks[1]["name"] if len(tracks) > 1 else "-"),
            fill=(40, 40, 40), font=font(15))
    dr.text((pad, 38), "x %.0f..%.0f  z %.0f..%.0f  |  帧 %.2f..%.2f s  |  两车轨迹重合 ⇒ 帧解码自证" %
            (minx, maxx, minz, maxz, tl[0][0]["t"], tl[0][-1]["t"]),
            fill=(110, 110, 110), font=font(13))
    j = Path(path).with_suffix(".png")
    img.save(j)
    return j


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--out", default="preview_tmp/replay_viewer.html")
    ap.add_argument("--png", default=None)
    a = ap.parse_args()
    tracks = load_track(a.file)
    payload = {"title": Path(a.file).name + "  (" + " / ".join(t["name"] for t in tracks) + ")",
               "tracks": [{"name": t["name"], "frames": build_timeline(t)} for t in tracks]}
    html = HTML.replace("__DATA__", json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print("wrote %s  (%d 字节, %d 轨迹, %d 帧)"
          % (out, len(html), len(payload["tracks"]),
             sum(len(t["frames"]) for t in payload["tracks"])))
    if a.png:
        print("wrote %s" % render_png(tracks, a.png))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
