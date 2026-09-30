#!/usr/bin/env python3
"""thunks.py — 导入跳转桩（IAT thunk）目录。

本 EXE 不直接 `call [IAT]`，而是每个导入函数对应一条 6 字节桩：

    <thunk_va>:  ff 25 <iat_va>        ; jmp dword ptr [iat_va]

内部代码一律 `call <thunk_va>`。因此要问「谁用了 D3DXMatrixMultiply / ReadFile / …」，
必须扫 `call <thunk_va>`，而不是扫 IAT 地址。

用法:
    python thunks.py                     # 生成 out_import_thunks.csv 并打印统计
    python thunks.py --who 0x5f9192      # 列出调用该桩的所有函数
    python thunks.py --who-name D3DXMatrixMultiply
    python thunks.py --uses 0x435de0     # 列出某函数用到的全部导入（按名字）
    python thunks.py --list D3DX         # 名称含 D3DX 的全部桩
"""
import struct, sys, os, re, bisect
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import iat

TOOLS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TOOLS)
CSV = os.path.join(ROOT, "out_import_thunks.csv")

TEXT_LO, TEXT_HI = 0x401000, 0x6E7000


def load_binary():
    return iat.PEFile().d


def sections():
    return iat.PEFile()


def find_thunks():
    """返回 [(thunk_va, iat_va, dll, name)]"""
    pe = iat.PEFile()
    imps = {v: (d, n) for v, d, n in pe.imports()}
    d = pe.d
    # 关键：所有索引都相对 .text 切片，避免与整文件偏移混淆
    blk = d[pe.r2o(TEXT_LO - pe.ib): pe.r2o(TEXT_LO - pe.ib) + (TEXT_HI - TEXT_LO)]
    out = []
    for iat_va, (dll, nm) in imps.items():
        # 桩在 .text 里：ff 25 <iat_va>。全 .text 搜索该 imm 的前两字节是否为 ff 25。
        # （不要假设桩就在 IAT 地址附近 —— 本 EXE 的桩集中在 0x5F91xx。）
        pat = struct.pack("<I", iat_va)
        found = None
        for m in re.finditer(re.escape(pat), blk):
            j = m.start()
            if j >= 2 and blk[j - 2:j] == b"\xff\x25":
                found = TEXT_LO + j - 2
                break
        if found is not None:
            out.append((found, iat_va, dll, nm))
    return sorted(out)


def func_starts(b):
    starts = [TEXT_LO]
    for m in re.finditer(bytes.fromhex("cc") + b"{2,}", b):
        starts.append(TEXT_LO + m.end())
    return sorted(set(starts))


def main():
    pe = iat.PEFile()
    o0 = pe.r2o(TEXT_LO - pe.ib)
    b = pe.d[o0: o0 + (TEXT_HI - TEXT_LO)]      # 只保留 .text，索引即 VA-TEXT_LO
    thunks = find_thunks()
    if not thunks:
        print("✗ 没找到桩（检查 iat.py 的输出）")
        return
    with open(CSV, "w", encoding="utf-8") as fh:
        fh.write("thunk_va,iat_va,dll,name\n")
        for t, i, dll, nm in thunks:
            fh.write(f"0x{t:x},0x{i:x},{dll},{nm}\n")
    args = sys.argv[1:]
    tmap = {t: (dll, nm) for t, i, dll, nm in thunks}
    if not args:
        dlls = {}
        for _, _, dll, _ in thunks:
            dlls[dll] = dlls.get(dll, 0) + 1
        print(f"桩 {len(thunks)} 个 → {CSV}")
        for k, v in sorted(dlls.items(), key=lambda x: -x[1]):
            print(f"  {v:5d}  {k}")
        print(f"  桩地址范围 {thunks[0][0]:#x} – {thunks[-1][0]:#x}")
        return
    if args[0] == "--list":
        key = args[1].lower()
        for t, i, dll, nm in thunks:
            if key in nm.lower():
                print(f"  {t:#010x}  {dll}!{nm}")
        return
    if args[0] in ("--who", "--who-name"):
        if args[0] == "--who":
            ts = [int(x, 16) for x in args[1:]]
        else:
            ts = [t for t, i, dll, nm in thunks if args[1].lower() in nm.lower()]
        starts = func_starts(b)
        for th in ts:
            nm = tmap.get(th, ("?", "?"))
            print(f"=== call {th:#x}  ({nm[0]}!{nm[1]}) ===")
            pat = b"\xe8" + struct.pack("<i", th - (0))  # place holder
            # 扫 e8 rel32 目标 == th
            hits = []
            i = 0
            while True:
                j = b.find(b"\xe8", i)
                if j < 0:
                    break
                i = j + 1
                if not (TEXT_LO <= TEXT_LO + j < TEXT_HI):
                    continue
                tgt = TEXT_LO + j + 5 + struct.unpack_from("<i", b, j + 1)[0]
                if tgt == th:
                    hits.append(TEXT_LO + j)
            owners = sorted({starts[bisect.bisect_right(starts, h) - 1] for h in hits})
            for ow in owners:
                print(f"   @{ow:#x}")
            print(f"   （{len(hits)} 处调用 / {len(owners)} 个函数）")
        return
    if args[0] == "--uses":
        fn = int(args[1], 16)
        starts = func_starts(b)
        lo = bisect.bisect_left(starts, fn)
        hi_ = lo + 1
        end = starts[hi_] if hi_ < len(starts) else TEXT_HI
        o0 = pe.r2o(TEXT_LO - pe.ib)
        blk = b[(fn - TEXT_LO):(end - TEXT_LO)]
        used = []
        i = 0
        while True:
            j = blk.find(b"\xe8", i)
            if j < 0:
                break
            i = j + 1
            tgt = fn + j + 5 + struct.unpack_from("<i", blk, j + 1)[0]
            if tgt in tmap:
                used.append(tmap[tgt])
        seen = []
        for x in used:
            if x not in seen:
                seen.append(x)
        print(f"{fn:#x}–{end:#x} 用到 {len(seen)} 个导入：")
        for dll, nm in seen:
            print(f"   {dll}!{nm}")
        return
    print(__doc__)


if __name__ == "__main__":
    main()
