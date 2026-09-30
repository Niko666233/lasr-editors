"""把两个 GUI 打包成双击即用的单文件 exe（PyInstaller onefile，无窗口）。

用法：  ./.capenv/Scripts/python.exe editors/build_exe.py [--clean]
产物：  editors/dist/LASR车辆数据修改器.exe
        editors/dist/LASR存档修改器.exe

依赖处理：unicorn 带本地 DLL，必须 --collect-all unicorn，否则 exe 里
`import unicorn` 会在运行时报找不到库。
"""
import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PY = sys.executable

TOOLS = (
    # 两个工具都能做成不需要 unicorn 的单文件 exe：
    #   * 车辆修改器：读值走随包发布的明文快照（data/classes）、写值走明文 TUFA
    #     （明文写入已实机验证被游戏接受，见 docs/60 §6/§7）
    #   * 存档修改器：零件目录（VID 表 + getIPart）同样走快照
    # unicorn 的 JIT 在 frozen exe 里必 0xC0000409，所以**不要** import 它，
    # 也别加 --collect-all unicorn（那只会让 exe 大 15 MB 且根本用不了）。
    ("vehicle_editor.pyw", "LASR车辆数据修改器"),
    ("save_editor.pyw", "LASR存档修改器"),
)

DATA = ("data", "data")        # (源目录, exe 内目标目录)


def build(script, name, clean=False):
    src = HERE / script
    if not src.exists():
        print("跳过（源文件不存在）:", src)
        return None
    cmd = [
        PY, "-m", "PyInstaller", "--noconfirm", "--onefile", "--windowed",
        "--name", name,
        "--distpath", str(HERE / "dist"),
        "--workpath", str(HERE / "build"),
        "--specpath", str(HERE / "build"),
        "--add-data", "%s%s%s" % (HERE / DATA[0], os.pathsep, DATA[1]),
        "--exclude-module", "unicorn",
        "--exclude-module", "capstone",
        "--exclude-module", "pytest",
        "--exclude-module", "setuptools",
        str(src),
    ]
    if clean:
        cmd.insert(3, "--clean")
    print("$", " ".join(cmd))
    r = subprocess.run(cmd, cwd=str(HERE))
    out = HERE / "dist" / (name + ".exe")
    print("exit=%d  exe=%s  exists=%s  size=%s"
          % (r.returncode, out, out.exists(),
             ("%.1f MB" % (out.stat().st_size / 1e6)) if out.exists() else "-"))
    return out if r.returncode == 0 and out.exists() else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clean", action="store_true")
    ap.add_argument("--only", default=None)
    a = ap.parse_args()
    built = []
    for script, name in TOOLS:
        if a.only and a.only not in name:
            continue
        out = build(script, name, a.clean)
        if out:
            built.append(out)
    print("\n产物:")
    for b in built:
        print("  ", b)
    if not built:
        print("   （没有构建任何东西——车辆修改器是 .bat 交付，见上面的说明）")
    # 顺带把 README 也放进 dist，方便用户拿到就知道怎么用
    readme = HERE / "README.md"
    if readme.exists():
        shutil.copy2(readme, HERE / "dist" / "使用说明.md")
    return 0 if built else 1


if __name__ == "__main__":
    raise SystemExit(main())
