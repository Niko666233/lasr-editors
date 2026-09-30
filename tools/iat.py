#!/usr/bin/env python3
"""iat.py — LASR.exe 的 IAT 反查工具。

用法:
    python iat.py 0x6E71C4 [0x... ...]      # 反查若干 IAT 槽的 VA
    python iat.py --scan 0x6E7100 0x6E7200  # 列出区间内所有 IAT 槽
    python iat.py --dll d3d9.dll            # 列出某 DLL 的全部导入

原理: 解析 PE 导入表（IMAGE_IMPORT_DESCRIPTOR → FirstThunk = IAT），
把每个槽的原像（OriginalFirstThunk）解成函数名，打印 `IAT_VA = DLL!name`。
地址一律为**原生 VA**（含 ImageBase），与项目其它工具一致。
"""
import struct, sys, os

EXE = r"C:\Games\LASR\LASR.exe"


class PEFile:
    def __init__(self, path=EXE):
        self.d = d = open(path, "rb").read()
        e = struct.unpack_from("<I", d, 0x3C)[0]
        assert d[e:e + 4] == b"PE\0\0", "not a PE"
        coff = e + 4
        self.nsec, = struct.unpack_from("<H", d, coff + 2)
        opt = coff + 20
        self.magic, = struct.unpack_from("<H", d, opt)
        self.ib, = struct.unpack_from("<I", d, opt + 28)
        dd = opt + (96 if self.magic == 0x10B else 112)
        self.imp_rva, self.imp_sz = struct.unpack_from("<II", d, dd + 8)
        self.secs = []
        so = opt + struct.unpack_from("<H", d, coff + 16)[0]
        for i in range(self.nsec):
            b = so + i * 40
            name = d[b:b + 8].rstrip(b"\0").decode()
            vsz, va, rsz, ptr = struct.unpack_from("<IIII", d, b + 8)
            self.secs.append((name, va, vsz, ptr, rsz))

    def r2o(self, rva):
        for name, va, vsz, ptr, rsz in self.secs:
            if va <= rva < va + max(vsz, rsz):
                return ptr + (rva - va)
        return None

    def va2rva(self, va):
        return va - self.ib

    def cstr(self, rva):
        o = self.r2o(rva)
        return self.d[o:].split(b"\0")[0].decode(errors="replace") if o is not None else "?"

    def imports(self):
        """生成 (iat_va, dll, name) 三元组。"""
        o = self.r2o(self.imp_rva)
        i = 0
        out = []
        while True:
            oft, ts, fc, nrva, fthunk = struct.unpack_from("<IIIII", self.d, o + i * 20)
            if oft == 0 and nrva == 0:
                break
            dll = self.cstr(nrva)
            src = oft or fthunk
            # 注意: 本文件的 TimeDateStamp(ts) == 0，不能用它当 IAT 长度；
            # 沿 OriginalFirstThunk 数组走到空项为止（上限 4096 保护）。
            so_src = self.r2o(src)
            slot = 0
            while slot < 4096:
                ent, = struct.unpack_from("<I", self.d, so_src + slot * 4)
                if ent == 0:
                    break
                nm = (self.cstr(ent + 2) if not (ent & 0x80000000)
                      else f"ord#{ent & 0xffff}")
                out.append((self.ib + fthunk + slot * 4, dll, nm))
                slot += 1
            i += 1
        return out


def main():
    pe = PEFile()
    imps = pe.imports()
    byva = {va: (dll, nm) for va, dll, nm in imps}
    args = sys.argv[1:]
    if not args:
        dlls = {}
        for _, dll, _ in imps:
            dlls[dll] = dlls.get(dll, 0) + 1
        print(f"{len(imps)} 个导入，{len(dlls)} 个 DLL：")
        for k, v in sorted(dlls.items(), key=lambda x: -x[1]):
            print(f"  {v:5d}  {k}")
        return
    if args[0] == "--dll":
        want = args[1].lower()
        for va, dll, nm in imps:
            if dll.lower() == want:
                print(f"  {va:#010x}  {dll}!{nm}")
        return
    if args[0] == "--scan":
        a, b = int(args[1], 16), int(args[2], 16)
        for va, dll, nm in imps:
            if a <= va < b:
                print(f"  {va:#010x}  {dll}!{nm}")
        return
    for a in args:
        va = int(a, 16)
        if va in byva:
            dll, nm = byva[va]
            print(f"  {va:#010x}  = {dll}!{nm}")
        else:
            # 落在某个 IAT 区间内但不是起点 → 提示相邻
            near = [x for x in imps if abs(x[0] - va) <= 0x20]
            print(f"  {va:#010x}  ✗ 不是任何 IAT 槽" +
                  (f"；邻近: " + ", ".join(f'{v:#x}={d}!{n}' for v, d, n in near) if near else ""))


if __name__ == "__main__":
    main()
