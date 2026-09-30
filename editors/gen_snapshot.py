"""生成「解压后明文类」快照 -> editors/data/classes/。

为什么需要：车辆修改器要读零件的当前数值，就得解开 FLZD 容器；而解压要跑
`LASR.exe` 自己的例程（unicorn），unicorn 在 PyInstaller 产物里会 0xC0000409
（见 docs/60 §6）。既然**明文 TUFA 写进 zip 已被游戏实测接受**，那就把每个类的
明文预先存一份随工具发布 —— 读值走快照，写值写明文，工具端彻底不需要模拟器。

    data/classes/<Car>/<body>/<Class>.tufa

用法（需要 unicorn，只在开发机跑）：
    cd editors && ../.capenv/Scripts/python.exe gen_snapshot.py [--force]

一致性：每个条目的 FLZD 头里有 uncompressedSize，生成时记录到 manifest 里；
工具读取时会拿它跟当前安装的容器头比对（长度不符 = 你换过游戏文件，快照不可信）。
"""
import argparse
import json
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from lasr_core import flzd, vdata  # noqa: E402

OUT = HERE / "data" / "classes"
MANIFEST = HERE / "data" / "classes_manifest.json"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="已有快照也重建")
    ap.add_argument("--game", default=None)
    ns = ap.parse_args()

    game = vdata.find_game_dir(ns.game)
    if not game:
        print("找不到游戏目录")
        return 1
    codec = flzd.FlzdCodec(game / "LASR.exe")
    jobs = [(zp, zp.parts[-3], zp.parts[-2])
            for zp in sorted(game.glob("vehicles/*/*/classes.zip"))]
    jz = game / "java" / "classes.zip"
    if jz.is_file():
        jobs.append((jz, "_java", ""))
    print("游戏目录 %s，容器 %d 个" % (game, len(jobs)))

    manifest = {}
    n_new = n_skip = n_fail = 0
    total = 0
    for zp, cat, body in jobs:
        with zipfile.ZipFile(zp) as z:
            for name in z.namelist():
                if not name.lower().endswith(".class"):
                    continue
                short = Path(name).stem
                dst = (OUT / cat / body / (short + ".tufa") if body
                       else OUT / cat / (short + ".tufa"))
                raw = z.read(name)
                _level, usize, _pay = flzd.parse_header(raw)
                key = ("%s/%s/%s" % (cat, body, short) if body
                       else "%s/%s" % (cat, short))
                if dst.is_file() and not ns.force:
                    n_skip += 1
                    total += usize
                    manifest[key] = usize
                    continue
                try:
                    data = codec.unpack(raw)
                except Exception as exc:  # noqa: BLE001
                    print("  解压失败 %s: %s" % (key, exc))
                    n_fail += 1
                    continue
                assert len(data) == usize, key
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_bytes(data)
                manifest[key] = usize
                total += usize
                n_new += 1

    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(manifest, separators=(",", ":")),
                        encoding="utf-8")
    size = sum(f.stat().st_size for f in OUT.rglob("*.tufa"))
    print("新增 %d / 跳过 %d / 失败 %d；清单 %d 条"
          % (n_new, n_skip, n_fail, len(manifest)))
    print("快照目录 %s：%.1f MB（明文 %d 字节）"
          % (OUT, size / 1e6, total))
    return 0 if not n_fail else 1


if __name__ == "__main__":
    raise SystemExit(main())
