"""Read / write the client's video settings in `save/game/options`.

Format recovered from the game's own Java (`java.util.Config.save()` +
`java.gfx.GfxEngine`), not guessed:

    "SDAT"       4 bytes
    0x00, ?, ?   3 bytes
    u32          file size (360)
    u32          SAVEFILEID  = 0xFEDCBA98 (-19088744)
    u32          SAVEFILEVERSION = 37
    u32          featureCount  (= GfxEngine.getFeatureCount(), 19)
    u32 x N      feature values, in GfxEngine's feature order
    u32 x 4      videoMode.width / height / depth / windowed
    u32 ...      vehicle detail, sound volumes, gameplay options

Feature indices (java.gfx.GfxEngine):
    0 GFX_FSAA   1 GFX_RESOLUTION   2 GFX_DX_COMPATIBILITY  <- the renderer mode
    3 REFLECTORDETAIL  4 VIEWRANGE  5 WORLDDETAIL  6 TEXTUREDETAIL  7 SHADOWDETAIL
    8 OBJECTLODDETAIL  9 OBJECTDETAIL  10 PARTICLE  11 SPRITE
    12 PFX_BLUR  13 PFX_GLOW  14 PFX_NOISE  15 PFX_CONTRAST
    16 DYNENVMAP  17 MIRROR  18 GAMMA

    python tools/options_edit.py --show
    python tools/options_edit.py --set 2=1 --windowed 1
"""
import argparse
import shutil
import struct
import sys
from pathlib import Path

OPTIONS = Path(r"C:\Games\LASR\save\game\options")
BACKUP = OPTIONS.with_suffix(".options.bak")
SAVEFILEID = 0xFEDCBA98
FEATURE_NAMES = {
    0: "GFX_FSAA", 1: "GFX_RESOLUTION", 2: "GFX_DX_COMPATIBILITY", 3: "GFX_REFLECTORDETAIL",
    4: "GFX_VIEWRANGE", 5: "GFX_WORLDDETAIL", 6: "GFX_TEXTUREDETAIL", 7: "GFX_SHADOWDETAIL",
    8: "GFX_OBJECTLODDETAIL", 9: "GFX_OBJECTDETAIL", 10: "GFX_PARTICLE", 11: "GFX_SPRITE",
    12: "GFX_PFX_BLUR", 13: "GFX_PFX_GLOW", 14: "GFX_PFX_NOISE", 15: "GFX_PFX_CONTRAST",
    16: "GFX_DYNENVMAP", 17: "GFX_MIRROR", 18: "GFX_GAMMA",
}
IDX_COUNT = 20          # u32 featureCount
IDX_FEATURES = 24       # first feature value

# inferred: GfxEngine.init() defaults dxCompat to 2 and the error strings name
# "no DX9" and "no DX7 card", so the three values are the three backends.
MODE_NAMES = {0: "DX7 (fixed function)", 1: "DX8 (ps.1.1/1.4)", 2: "DX9 (ps.2.0)"}


def load():
    d = OPTIONS.read_bytes()
    if d[:4] != b"SDAT":
        raise SystemExit(f"不是 SDAT 文件: {d[:4]!r}")
    size, fid, ver, count = struct.unpack_from("<IIII", d, 8)
    if fid != SAVEFILEID:
        raise SystemExit(f"SAVEFILEID 不符: 0x{fid:08x}")
    feats = list(struct.unpack_from(f"<{count}I", d, IDX_FEATURES))
    after = IDX_FEATURES + count * 4
    vm = list(struct.unpack_from("<4I", d, after))
    return d, size, ver, count, feats, after, vm


def show():
    d, size, ver, count, feats, after, vm = load()
    print(f"{OPTIONS}  大小={len(d)} (头里的 size={size})  version={ver}  count={count}")
    for i, v in enumerate(feats):
        n = FEATURE_NAMES.get(i, f"feature{i}")
        extra = ""
        if i == 2:
            extra = f"   <-- 渲染模式 = {MODE_NAMES.get(v, '?')}"
        print(f"  [{i:2d}] {n:26s} = {v:12d} (0x{v:08x}){extra}")
    print(f"  videoMode w/h/depth/windowed = {vm}")
    print(f"  其余字段从偏移 {after + 16} 开始（车辆细节/音量/玩法选项）")
    return 0


def edit(sets, windowed=None):
    d, size, ver, count, feats, after, vm = load()
    if not BACKUP.exists():
        shutil.copy2(OPTIONS, BACKUP)
        print(f"已备份 -> {BACKUP}")
    b = bytearray(d)
    for k, v in sets:
        if not (0 <= k < count):
            raise SystemExit(f"特征下标 {k} 越界 (0..{count - 1})")
        old = feats[k]
        struct.pack_into("<I", b, IDX_FEATURES + k * 4, v)
        feats[k] = v
        print(f"  [{k}] {FEATURE_NAMES.get(k, k)}: {old} -> {v}"
              + (f"  ({MODE_NAMES.get(v, '?')})" if k == 2 else ""))
    if windowed is not None:
        struct.pack_into("<I", b, after + 12, windowed)
        print(f"  windowed: {vm[3]} -> {windowed}")
    OPTIONS.write_bytes(bytes(b))
    chk = OPTIONS.read_bytes()
    print(f"已写回 {len(chk)} 字节；校验 magic={chk[:4]!r} size一致={struct.unpack_from('<I', chk, 8)[0] == len(chk)}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--set", action="append", default=[], metavar="IDX=VAL")
    ap.add_argument("--windowed", type=int, default=None, choices=[0, 1])
    ap.add_argument("--restore", action="store_true")
    a = ap.parse_args()
    if a.restore:
        shutil.copy2(BACKUP, OPTIONS)
        print(f"已从 {BACKUP} 恢复")
        return show()
    if a.show or not a.set:
        return show()
    sets = []
    for s in a.set:
        k, v = s.split("=")
        sets.append((int(k), int(v)))
    return edit(sets, a.windowed)


if __name__ == "__main__":
    sys.exit(main())
