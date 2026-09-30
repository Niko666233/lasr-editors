"""解析 Windows minidump（.dmp），不需要调试器、不需要符号。

为什么写它：机器上没有 WinDbg/VS，但 minidump 格式是公开的 —— 一个崩溃转储能回答
"到底炸在哪、什么异常、哪条线程、调用栈是什么"。而且本项目已经静态扫出了 LASR.exe 的
全部**函数起点**（所有 E8 目标），于是崩掉的指令地址和栈上的返回地址都能直接落回函数。

输出：
  1. 异常记录（异常码/地址/线程）
  2. 崩溃地址落在哪个模块、偏移多少、属于哪个函数（用函数起点表归属）
  3. 崩溃线程的 EIP/ESP/EBP
  4. 栈扫描：把栈上所有"像代码地址"的值按顺序列出并归属到函数 —— 穷人版调用栈
  5. 模块表（基址/大小）

用法: python tools/dump_info.py <a.dmp> [exe路径]
"""
import struct
import sys

STREAM = {3: "ThreadList", 4: "ModuleList", 5: "MemoryList", 6: "Exception",
          7: "SystemInfo", 9: "Memory64List", 15: "MiscInfo", 16: "CommentW"}

EXC_NAMES = {
    0xC0000005: "STATUS_ACCESS_VIOLATION (读写非法地址)",
    0xC000001D: "STATUS_ILLEGAL_INSTRUCTION",
    0xC0000094: "STATUS_INTEGER_DIVIDE_BY_ZERO",
    0xC00000FD: "STATUS_STACK_OVERFLOW",
    0xC0000374: "STATUS_HEAP_CORRUPTION",
    0xC0000409: "STATUS_STACK_BUFFER_OVERRUN (GS 溢出)",
    0x80000003: "STATUS_BREAKPOINT (int3 —— 调试器断点残留?)",
    0x4000001F: "STATUS_WX86_BREAKPOINT",
    0x4000001E: "STATUS_WX86_SINGLE_STEP",
    0xC0000135: "STATUS_DLL_NOT_FOUND",
    0xC0000142: "STATUS_DLL_INIT_FAILED",
    0x80000029: "STATUS_ABANDONED_WAIT_0",
}


def u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def u64(b, o):
    return struct.unpack_from("<Q", b, o)[0]


class Dump:
    def __init__(self, path):
        self.d = open(path, "rb").read()
        sig, ver, nstreams, dirrva = struct.unpack_from("<IIII", self.d, 0)
        assert sig == 0x504D444D, f"不是 minidump（签名 0x{sig:08x}）"
        self.streams = {}
        for i in range(nstreams):
            o = dirrva + i * 12
            st, size, rva = struct.unpack_from("<III", self.d, o)
            self.streams[st] = (size, rva)
        self.modules = []
        self.threads = []
        self._parse_modules()
        self._parse_threads()

    def _utf16_at(self, rva):
        n = u32(self.d, rva)                       # 字节数
        return self.d[rva + 4:rva + 4 + n].decode("utf-16-le", "replace")

    def _parse_modules(self):
        if 4 not in self.streams:
            return
        size, rva = self.streams[4]
        n = u32(self.d, rva)
        o = rva + 4
        for _ in range(n):
            base, imgsize, csum, tds, namerva = struct.unpack_from("<QIIII", self.d, o)
            o += 108                                # sizeof(MINIDUMP_MODULE)
            try:
                name = self._utf16_at(namerva)
            except Exception:
                name = "?"
            self.modules.append((base, imgsize, name))
        self.modules.sort()

    def _parse_threads(self):
        if 3 not in self.streams:
            return
        size, rva = self.streams[3]
        n = u32(self.d, rva)
        o = rva + 4
        for _ in range(n):
            tid, susp, pc, pri, teb = struct.unpack_from("<IIIII", self.d, o)
            stack_start = u64(self.d, o + 4 + 4 * 5)
            st_size, st_rva = struct.unpack_from("<II", self.d, o + 4 + 4 * 5 + 8)
            ct_size, ct_rva = struct.unpack_from("<II", self.d, o + 4 + 4 * 5 + 16)
            self.threads.append({"tid": tid, "susp": susp, "stack": (stack_start, st_size, st_rva),
                                 "ctx": (ct_size, ct_rva)})
            o += 48                                 # sizeof(MINIDUMP_THREAD)

    def exception(self):
        if 6 not in self.streams:
            return None
        _, rva = self.streams[6]
        tid = u32(self.d, rva)
        o = rva + 8
        code, flags, rec, addr = struct.unpack_from("<IIQQ", self.d, o)
        nparam = u32(self.d, o + 24)
        params = [u64(self.d, o + 32 + 8 * i) for i in range(min(nparam, 15))]
        ct_size, ct_rva = struct.unpack_from("<II", self.d, o + 32 + 8 * 15)
        return {"tid": tid, "code": code, "flags": flags, "addr": addr,
                "params": params, "ctx": (ct_size, ct_rva)}

    def read_ctx(self, ct):
        size, rva = ct
        b = self.d[rva:rva + size]
        if len(b) < 0xC8:
            return {}
        # 标准 x86 CONTEXT 偏移
        return {"Dr0": u32(b, 0x04), "Dr1": u32(b, 0x08), "Dr2": u32(b, 0x0C),
                "Dr3": u32(b, 0x10), "Dr6": u32(b, 0x18), "Dr7": u32(b, 0x1C),
                "Ebp": u32(b, 0xB4), "Eip": u32(b, 0xB8), "Esp": u32(b, 0xC4)}

    def owner(self, addr):
        for base, size, name in self.modules:
            if base <= addr < base + size:
                return name, addr - base
        return None, None


def func_starts(exe_path):
    """扫 exe 里所有 E8 rel32 的目标 = 函数起点集合（本项目已有做法）。"""
    data = open(exe_path, "rb").read()
    starts = set()
    i = 0
    n = len(data)
    while True:
        i = data.find(b"\xe8", i)
        if i < 0 or i + 5 > n:
            break
        rel = struct.unpack_from("<i", data, i + 1)[0]
        starts.add(i + 5 + rel)
        i += 1
    return starts


def nearest(starts, addr):
    best = None
    for s in starts:
        if s <= addr and (best is None or s > best):
            best = s
    return best


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    dmp_path = sys.argv[1]
    exe = sys.argv[2] if len(sys.argv) > 2 else r"C:\Games\LASR\LASR.exe"
    d = Dump(dmp_path)
    print(f"=== {dmp_path} ===")
    print("流:", ", ".join(f"{STREAM.get(k, k)}" for k in sorted(d.streams)))
    print(f"\n=== 模块 ({len(d.modules)}) ===")
    for base, size, name in d.modules:
        print(f"  {base:#012x}  {size:>9,}  {name}")

    ex = d.exception()
    if not ex:
        print("\n✗ 没有 ExceptionStream（可能不是崩溃转储）")
        return 0
    print(f"\n=== 异常 ===")
    print(f"  线程      : {ex['tid']}")
    print(f"  异常码    : 0x{ex['code']:08X}  {EXC_NAMES.get(ex['code'], '（未知）')}")
    print(f"  异常地址  : 0x{ex['addr']:08X}", end="")
    m, off = d.owner(ex["addr"])
    print(f"   →  {m}" + (f"+0x{off:X}" if m else "   ✗ 不在任何模块内（野指针/栈/堆！）"))
    if ex["params"]:
        print("  参数      :", " ".join(f"0x{p:08X}" for p in ex["params"]))
        if ex["code"] == 0xC0000005 and len(ex["params"]) >= 2:
            kind = {0: "读", 1: "写", 8: "执行(DEP)"}.get(ex["params"][0], "?")
            print(f"              → 访问类型 = {kind}，目标地址 = 0x{ex['params'][1]:08X}")

    starts = set()
    try:
        starts = func_starts(exe)
        print(f"\n  (函数起点表: {len(starts):,} 个，来自 {exe})")
    except Exception as e:
        print(f"  (函数起点表加载失败: {e})")

    ctx = d.read_ctx(ex["ctx"]) or {}
    for t in d.threads:
        if t["tid"] == ex["tid"]:
            ctx = d.read_ctx(t["ctx"]) or ctx
    if ctx:
        print(f"\n=== 崩溃线程寄存器 ===")
        print(f"  EIP=0x{ctx.get('Eip', 0):08X}  ESP=0x{ctx.get('Esp', 0):08X}  "
              f"EBP=0x{ctx.get('Ebp', 0):08X}")
        print(f"  Dr0=0x{ctx.get('Dr0', 0):08X}  Dr1=0x{ctx.get('Dr1', 0):08X}  "
              f"Dr2=0x{ctx.get('Dr2', 0):08X}  Dr3=0x{ctx.get('Dr3', 0):08X}")
        print(f"  Dr6=0x{ctx.get('Dr6', 0):08X}  Dr7=0x{ctx.get('Dr7', 0):08X}"
              f"   ← ★ 硬件断点是【本进程自己的】还是调试器留下的？")
        if ctx.get("Dr6", 0) & 0xF:
            flags = [f"B{i}" for i in range(4) if ctx["Dr6"] & (1 << i)]
            print(f"  ★ Dr6 命中标志置位: {', '.join(flags)}")
        if ctx.get("Dr7", 0) & 0xFF:
            print("  ★ Dr7 低位非 0 ⇒ 崩溃时硬件执行断点仍处于【使能】状态！")
            for i in range(4):
                if ctx["Dr7"] & (1 << (2 * i)):
                    tgt = ctx.get(f"Dr{i}", 0)
                    extra = ""
                    m, off = d.owner(tgt)
                    if m:
                        extra = f"  ({m}+0x{off:X})"
                    mark = ""
                    if tgt == ex["addr"]:
                        mark = "   ★★ 与异常地址完全一致 ⇒ 就是它触发的！"
                    print(f"    槽{i} 使能: 目标 0x{tgt:08X}{extra}{mark}")

    # 栈扫描：把栈上像代码地址的 DWORD 按顺序归属到函数
    for t in d.threads:
        if t["tid"] != ex["tid"]:
            continue
        start, size, rva = t["stack"]
        st = d.d[start:start + size] if rva is None else d.d[rva:rva + size]
        print(f"\n=== 栈扫描（线程 {ex['tid']}，{start:#x} 起 {size:,} 字节）===")
        if not st:
            print("  ✗ 转储里没有该线程的栈内存")
            break
        hits = []
        lasr = next(((b, s) for b, s, n in d.modules if n.lower().endswith("lasr.exe")), None)
        for i in range(0, len(st) - 4, 4):
            v = struct.unpack_from("<I", st, i)[0]
            if v < 0x10000:
                continue
            m, off = d.owner(v)
            if m:
                hits.append((start + i, v, m, off))
        for slot, v, m, off in hits[:40]:
            extra = ""
            # 只有落在 LASR.exe 自己的范围内才谈"属于哪个 LASR 函数"，
            # 否则会把系统 DLL 的地址硬套成 LASR 函数（错得很难看）。
            if starts and lasr and lasr[0] <= v < lasr[0] + lasr[1]:
                fs = nearest(starts, v)
                if fs is not None and fs >= lasr[0]:
                    extra = f"  ← LASR 函数 0x{fs:X}+0x{v - fs:X}"
            print(f"  [{slot:#010x}] 0x{v:08X}  {m}+0x{off:X}{extra}")
        print(f"  （共 {len(hits)} 个代码地址落在栈上）")
        break
    return 0


if __name__ == "__main__":
    sys.exit(main())
