"""证据搜集：游戏安装目录里有没有「不是 FLZD、但还是被游戏加载」的资源？

如果存在（比如某些 .class/资源直接是 TUFA 明文），就证明加载器对非 FLZD 数据
是回退放行而不是报错 —— 那我们就能把改过的 class 以明文 TUFA 写回 zip，
工具端完全不需要压缩器（也就绕开 unicorn 在打包 exe 里 JIT 崩溃的问题）。

输出：每个容器的条目按 magic 分类统计 + 非 FLZD 条目的清单。
"""
import re
import struct
import sys
import zipfile
from pathlib import Path

GAME = Path(r"C:\Games\LASR")
MAGICS = {b"FLZD": "FLZD", b"TUFA": "TUFA", b"\xca\xfe\xba\xbe": "CAFE",
          b"PK\x03\x04": "ZIP", b"RSD\0": "RSD", b"INVO": "INVO"}
rows = []
weird = []

zips = sorted(GAME.rglob("*.zip"))
for zp in zips:
    try:
        with zipfile.ZipFile(zp) as z:
            names = z.namelist()
            counts = {}
            for n in names:
                if n.endswith("/"):
                    continue
                head = z.read(n)[:4]
                tag = MAGICS.get(head, head.hex())
                counts[tag] = counts.get(tag, 0) + 1
                if tag not in ("FLZD", "TUFA"):
                    weird.append((str(zp), n, tag, len(z.read(n))))
            rows.append((str(zp.relative_to(GAME)), len(names), counts))
    except Exception as e:  # noqa: BLE001
        rows.append((str(zp.relative_to(GAME)), -1, {"ERR": str(e)[:40]}))

print("=== 所有 zip 的内容分类 ===")
for name, n, counts in rows:
    print("  %-46s %4d  %s" % (name, n, counts))

print("\n=== 非 FLZD/TUFA 的 zip 条目（前 40）===")
for w in weird[:40]:
    print("  %s ! %s  magic=%s size=%d" % (w[0], w[1], w[2], w[3]))
print("  合计", len(weird))

print("\n=== 散装文件（非 zip）的头 4 字节 ===")
loose = []
for p in sorted(GAME.rglob("*")):
    if not p.is_file() or p.suffix.lower() in (".zip", ".rpk", ".exe", ".dll",
                                               ".dmp", ".log", ".png", ".cfg",
                                               ".als", ".txt"):
        continue
    try:
        head = p.open("rb").read(4)
    except OSError:
        continue
    tag = MAGICS.get(head, head.hex())
    loose.append((str(p.relative_to(GAME)), tag, p.stat().st_size))
for name, tag, size in loose[:60]:
    print("  %-52s %-9s %d" % (name, tag, size))
print("  合计", len(loose), "个散装文件")
