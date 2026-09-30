"""FSB3 → WAV 提取器。

实测结论（16 个音库逐条验证）：LASR 的 FSB3 **全部是 16-bit PCM @ 44100 Hz**
（压缩字节/采样数/声道 = 2.00，且数据首字节为有符号负值 0xecff），
不需要任何解码器 —— 提取就是按 lengthsamples 切片。

仍然做防护：若某条目不是 PCM（体积比异常），**不猜**、不伪造，原样导出
`<name>.raw` 并在报告里标 ✗，交由人工判断。

循环点写进标准 `smpl` 块的 loop 段（重制引擎可直接读取）：
    loopstart/loopend 全为 0..N-1 表示"整段循环"（引擎音常用）。

用法：
  python tools/fsb_extract.py                    # 全部音库 → out_audio/<库名>/<采样名>.wav
  python tools/fsb_extract.py --only sounds      # 只处理路径含 sounds 的音库
"""
import os
import struct
import sys

ROOT = r"C:\Games\LASR"
OUT = r"out_audio"


def cstr(b):
    i = b.find(b"\0")
    return b[:i if i >= 0 else len(b)].decode("latin1")


def parse(path):
    with open(path, "rb") as fh:
        blob = fh.read()
    if blob[:4] != b"FSB3":
        return None
    n, hdr_total, data_size, ver, mode = struct.unpack_from("<IIIII", blob, 4)
    # ★ 数据起点由【文件尾 - 数据块大小】反推：这个恒等式比 hdr_total//n 可靠得多。
    #   实测 roadnoise.fsb 的采样头长度是【可变】的（首条自身写 0x364=868，且内嵌 SYNC 块），
    #   14×868 ≠ hdr_total(3760)，所以绝不能用均值走表 ⇒ 按每条自己的 size 走。
    data_off = len(blob) - data_size
    samples, off, p = [], 0, 24
    while len(samples) < n and p + 80 <= data_off:
        size = struct.unpack_from("<H", blob, p)[0]
        if size < 80 or p + size > data_off:
            break
        name = cstr(blob[p + 2:p + 32])
        (lsamp, lcomp, lps, lpe, smode) = struct.unpack_from("<IIIII", blob, p + 32)
        freq = struct.unpack_from("<i", blob, p + 52)[0]
        vol = struct.unpack_from("<H", blob, p + 56)[0]
        pan = struct.unpack_from("<h", blob, p + 58)[0]
        pr = struct.unpack_from("<h", blob, p + 60)[0]
        nch = struct.unpack_from("<H", blob, p + 62)[0]
        samples.append(dict(name=name, lsamp=lsamp, lcomp=lcomp, lps=lps, lpe=lpe,
                            mode=smode, freq=freq, vol=vol, pan=pan, pri=pr,
                            ch=nch, off=off, hdr_size=size))
        off += lcomp
        p += size
    # ★ 自校验：走完必须正好落在数据起点，且压缩总量必须等于数据块大小
    ok = (p == data_off) and (off == data_size) and (len(samples) == n)
    return dict(n=n, data_off=data_off, samples=samples, version=ver, mode=mode,
                ok=ok, walked_to=p, expect=data_off, payload_sum=off)


def riff(ch, freq, bits, data, lps=None, lpe=None, lsamp=None):
    """组装 RIFF/WAVE，可选写入 smpl 循环块"""
    is_pcm = bits in (8, 16)
    fmt = struct.pack("<HHIIHH", 1 if is_pcm else 0, ch, freq,
                      freq * ch * (bits // 8), ch * (bits // 8), bits)
    body = b"fmt " + struct.pack("<I", len(fmt)) + fmt
    if lps is not None and lpe is not None and lpe > lps:
        # smpl: 9 个 uint32 头 + 1 个 loop 结构（6 个 uint32）= 36 + 24 = 60 字节
        smpl = struct.pack("<IIIIIIIII", 0, 0, int(1e9 / freq), 60, 0, 0, 0, 1, 0)
        smpl += struct.pack("<IIIIII", 0, 0, lps, lpe, 0, 0)
        body += b"smpl" + struct.pack("<I", len(smpl)) + smpl
    body += b"data" + struct.pack("<I", len(data)) + data
    return b"RIFF" + struct.pack("<I", len(body) + 4) + b"WAVE" + body


def main():
    only = None
    if "--only" in sys.argv:
        only = sys.argv[sys.argv.index("--only") + 1]
    banks = []
    for dirpath, _, files in os.walk(ROOT):
        for f in files:
            if f.lower().endswith(".fsb"):
                p = os.path.join(dirpath, f)
                if only and only.lower() not in p.lower():
                    continue
                banks.append(p)
    banks.sort()
    total_wav = total_bytes = 0
    bad = []
    print(f"待处理音库 {len(banks)} 个\n")
    for p in banks:
        info = parse(p)
        if not info:
            continue
        rel = os.path.relpath(p, ROOT)
        bank = os.path.splitext(os.path.basename(p))[0]
        outdir = os.path.join(OUT, bank)
        os.makedirs(outdir, exist_ok=True)
        with open(p, "rb") as fh:
            payload = fh.read()
        made = 0
        for s in info["samples"]:
            raw = payload[info["data_off"] + s["off"]:info["data_off"] + s["off"] + s["lcomp"]]
            ch = max(s["ch"], 1)
            bps = (len(raw) / s["lsamp"] / ch) if s["lsamp"] else 0
            safe = "".join(c if c.isalnum() or c in " ._-()'" else "_" for c in s["name"]).strip() or f"s{s['off']}"
            if not safe.lower().endswith(".wav"):
                safe += ".wav"
            if 1.9 < bps < 2.1 and len(raw) == s["lsamp"] * ch * 2:
                # 16-bit PCM
                data = riff(ch, s["freq"], 16, raw, s["lps"], s["lpe"], s["lsamp"])
            elif 0.9 <= bps <= 1.1 and len(raw) == s["lsamp"] * ch:
                data = riff(ch, s["freq"], 8, raw, s["lps"], s["lpe"], s["lsamp"])
            else:
                bad.append((rel, s["name"], f"{bps:.3f} B/采样"))
                with open(os.path.join(outdir, safe + ".raw"), "wb") as fh:
                    fh.write(raw)
                continue
            with open(os.path.join(outdir, safe), "wb") as fh:
                fh.write(data)
            made += 1
            total_wav += 1
            total_bytes += len(raw)
        mark = "✓" if info["ok"] else "✗自校验失败"
        print(f"  {mark} {rel:<34} {made}/{info['n']} 条 → {OUT}\\{bank}\\" +
              ("" if info["ok"] else f"   [走到 {info['walked_to']} 应为 {info['expect']}，"
                                     f"负载合计 {info['payload_sum']}]"))
    print(f"\n合计导出 {total_wav} 个 WAV，原始 PCM {total_bytes/1048576:.1f} MB")
    if bad:
        print(f"\n✗ 非 PCM、已原样导出为 .raw（未伪造，待人工判断）{len(bad)} 条：")
        for b in bad[:20]:
            print(f"   {b[0]} :: {b[1]} ({b[2]})")


if __name__ == "__main__":
    main()
