"""FSB3（FMOD Sound Bank v3）解析器 —— 只读，不依赖任何外部库。

格式（由 16 个实际音库的头部自洽验证：menu.fsb 9 个采样 × 80 = 0x2d0 ✓，
buggy.fsb 5 个采样 × 80 = 0x190 ✓，两处 sampleHeaderSize 与 numSamples 严格吻合）：

  主头（24 字节，小端）
    0  char[4]  "FSB3"
    4  uint32   numSamples
    8  uint32   totalSampleHeaderSize   (= numSamples × 每头字节数)
    12 uint32   dataSize                (数据块总字节数)
    16 uint32   version                 (实测 0x00030001 = 3.1)
    20 uint32   mode
  采样头表（numSamples 个，每个 80 字节）
    0  uint16   size (= 80)          2  char[30] name（★ 明文，形如 "highload.wav"）
    32 uint32   lengthsamples        36 uint32  lengthcompressedbytes
    40 uint32   loopstart            44 uint32  loopend
    48 uint32   mode                 52 int32   deffreq
    56 uint16   defvol               58 int16   defpan
    60 int16    defpri               62 uint16  numchannels
    64 float    mindistance          68 float   maxdistance
    72 int32    varfreq              76 uint16  varvol
    78 int16    varpan
  数据块（紧随采样头表之后）

编码判据不靠 mode 位（FMOD 3 的位值我无法确证，不猜）——改用**自洽的体积比**：
  压缩字节 / 采样数 / 声道 = 每采样字节数 ⇒ 4:1≈IMA-ADPCM、MPEG 会有 MP3 帧头、1:1=16bit PCM。
同时在数据起点打印十六进制，MP3 帧头（FF Ex）一眼可见。

用法：
  python tools/fsb_parse.py [音库文件或目录 ...]      # 不给参数则扫 C:\\Games\\LASR 下的全部 .fsb
  python tools/fsb_parse.py --csv out_fsb.csv         # 输出表格
"""
import csv
import glob
import os
import struct
import sys

ROOT = r"C:\Games\LASR"
PER_HEADER = 80          # 实测值，但以文件里的 size 字段为准


def cstr(b):
    i = b.find(b"\0")
    return b[:i if i >= 0 else len(b)].decode("latin1")


def parse(path):
    with open(path, "rb") as fh:
        blob = fh.read()
    if blob[:4] not in (b"FSB3", b"FSB2", b"FSB4"):
        return None, f"魔数不是 FSB*（实际 {blob[:4]!r}）"
    magic = blob[:4].decode()
    n, hdr_total, data_size, ver, mode = struct.unpack_from("<IIIII", blob, 4)
    if magic != "FSB3":
        return None, f"{magic} 版本，本解析器只处理 FSB3"
    # ★ 采样头长度【可变】：按每条自身的 uint16 size 推进，绝不用 hdr_total//n 的均值。
    #   数据起点由文件尾反推（roadnoise.fsb 首条头 868 字节并内嵌 SYNC 块，
    #   用均值会把 14 条全解析成空名字）。
    data_off = len(blob) - data_size
    out = []
    off = 0
    p = 24
    while len(out) < n and p + 80 <= data_off:
        size = struct.unpack_from("<H", blob, p)[0]
        if size < 80 or p + size > data_off:
            break
        base = p
        name = cstr(blob[base + 2:base + 32])
        (lsamples, lcomp, loopstart, loopend, smode) = struct.unpack_from("<IIIII", blob, base + 32)
        deffreq = struct.unpack_from("<i", blob, base + 52)[0]
        defvol = struct.unpack_from("<H", blob, base + 56)[0]
        defpan = struct.unpack_from("<h", blob, base + 58)[0]
        defpri = struct.unpack_from("<h", blob, base + 60)[0]
        nch = struct.unpack_from("<H", blob, base + 62)[0]
        mind, maxd = struct.unpack_from("<ff", blob, base + 64)
        out.append(dict(idx=len(out), name=name, entry_size=size, lengthsamples=lsamples,
                        compressed=lcomp, loopstart=loopstart, loopend=loopend,
                        mode=smode, freq=deffreq, vol=defvol, pan=defpan, pri=defpri,
                        ch=nch, mindist=mind, maxdist=maxd, off=off, hdr_size=size))
        off += lcomp
        p += size
    dsoff = len(blob) - data_size
    ok = (p == dsoff) and (off == data_size) and (len(out) == n)
    return dict(path=path, magic=magic, n=n, hdr_total=hdr_total, data_size=data_size,
                version=ver, mode=mode, per=hdr_total // max(n, 1), data_off=dsoff,
                samples=out, ok=ok, walked_to=p), None


def codec_guess(s):
    """按体积比 + 体积上限推测编码（不依赖 mode 位）"""
    ch = max(s["ch"], 1)
    if not s["lengthsamples"]:
        return "?"
    bps = s["compressed"] / s["lengthsamples"] / ch
    if bps > 1.9:
        return f"16bit PCM({bps:.2f} B/采样)"
    if 0.9 <= bps <= 1.1:
        return f"8bit PCM({bps:.2f})"
    if 0.45 <= bps <= 0.55:
        return f"IMA-ADPCM 4:1({bps:.2f})"
    if bps < 0.45:
        return f"MPEG MP3({bps:.3f})"
    return f"ADPCM 2:1?({bps:.2f})"


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    csv_path = None
    for a in sys.argv[1:]:
        if a.startswith("--csv"):
            csv_path = a.split("=", 1)[1] if "=" in a else "out_fsb.csv"
    if not args:
        args = sorted(glob.glob(os.path.join(ROOT, "**", "*.fsb"), recursive=True))
    rows = []
    print(f"扫描 {len(args)} 个音库\n")
    for p in args:
        info, err = parse(p)
        if err:
            print(f"✗ {p}: {err}")
            continue
        rel = os.path.relpath(p, ROOT) if p.startswith(ROOT) else p
        print(f"═══ {rel}  （FSB3，{info['n']} 个采样，头 {info['hdr_total']} B，"
              f"数据 {info['data_size']} B，版本 {info['version']:#x}）")
        for s in info["samples"]:
            loop = "—"
            if s["loopend"] > s["loopstart"]:
                loop = f"{s['loopstart']}→{s['loopend']} ({s['loopend']-s['loopstart']} 采样)"
            print(f"   [{s['idx']:2}] {s['name']:<26} {s['lengthsamples']:>9} 采样 "
                  f"{s['freq']:>6} Hz  {s['ch']}ch  vol{s['vol']:<6} pan{s['pan']:<5} "
                  f"{s['compressed']:>8}B  {codec_guess(s):<22} loop {loop}")
            rows.append(dict(bank=rel, idx=s["idx"], name=s["name"], samples=s["lengthsamples"],
                             freq=s["freq"], ch=s["ch"], vol=s["vol"], pan=s["pan"],
                             pri=s["pri"], compressed=s["compressed"],
                             loopstart=s["loopstart"], loopend=s["loopend"],
                             mode=s["mode"], mindist=s["mindist"], maxdist=s["maxdist"],
                             codec=codec_guess(s)))
        # 数据块起点前 16 字节：MP3 帧头一眼可见
        with open(p, "rb") as fh:
            fh.seek(info["data_off"])
            peek = fh.read(16)
        print(f"   数据块 @ {info['data_off']:#x}  前 16 字节: {peek.hex(' ')}\n")
    if csv_path:
        keys = list(rows[0].keys()) if rows else []
        with open(csv_path, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(fh, fieldnames=keys)
            w.writeheader()
            w.writerows(rows)
        print(f"✓ 已写 {csv_path}（{len(rows)} 行）")


if __name__ == "__main__":
    main()
