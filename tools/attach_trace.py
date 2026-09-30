"""附着到**已经在运行**的 LASR.exe，并采集 D3D9 绘制调用（用于赛道内场景）。

与 d3d9_tracer.py 的区别：后者用 CreateProcess 从零启动游戏、靠抓
Direct3DCreate9 → CreateDevice 拿设备指针；本工具用 DebugActiveProcess 附着到
已经进好比赛的游戏上，直接读 **已确证** 的全局 [0x781e04] = IDirect3DDevice9*
（见 docs/26 §4），再挂 vtable 硬件断点。

安全约定（对用户正在玩的进程）：
  * 永不 TerminateProcess —— 只 DebugActiveProcessStop 干净分离 ✓
  * 任何异常/中断路径都在 finally 里分离 ✓
  * 只读内存 + 硬件断点，不写被调试进程的代码/数据 ✓

用法: python tools/attach_trace.py <pid> [秒数]
输出: out_tracer.jsonl（与 d3d9_tracer.py 同格式，可直接 --symbolize）
"""
import ctypes
import json
import struct
import sys
import time
from ctypes import wintypes
from pathlib import Path

ROOT = Path(r"C:\Users\niko6\Desktop\Work\LASR_Reverse_Engineering")
LOG = ROOT / "out_tracer.jsonl"

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
ntdll = ctypes.WinDLL("ntdll")

DEV_GLOBAL = 0x781E04          # ★ 已确证：游戏把 IDirect3DDevice9* 存在这里
# ★★ 安全第一：只挂【低命中率】的槽。历史事故：挂了 DrawIndexedPrimitive（每帧上千次）
#    ⇒ 每帧把目标停上千次 ⇒ 画面声音全停。Present≈1/帧、SetRT/SDS≈2~3/帧 ⇒ 开销可忽略。
SLOT = {"Present": 17, "SetRenderTarget": 37, "SetDepthStencilSurface": 39}

THREAD_GET_CONTEXT = 0x0008
THREAD_SET_CONTEXT = 0x0010
THREAD_SUSPEND_RESUME = 0x0002
PROCESS_ALL_ACCESS = 0x001F0FFF
DBG_CONTINUE = 0x00010002
DBG_EXCEPTION_NOT_HANDLED = 0x80010001
EXCEPTION_BREAKPOINT = 0x80000003
WX86_BP = 0x4000001F
WX86_SINGLE_STEP = 0x4000001E

k32.DebugActiveProcess.argtypes = [wintypes.DWORD]
k32.DebugActiveProcess.restype = wintypes.BOOL
k32.DebugActiveProcessStop.argtypes = [wintypes.DWORD]
k32.DebugActiveProcessStop.restype = wintypes.BOOL
k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
k32.OpenProcess.restype = wintypes.HANDLE
k32.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
k32.OpenThread.restype = wintypes.HANDLE
k32.SuspendThread.argtypes = [wintypes.HANDLE]
k32.ResumeThread.argtypes = [wintypes.HANDLE]
k32.ReadProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                  ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]


Wow64GetThreadContext = k32.Wow64GetThreadContext      # kernel32 exports it, not ntdll
Wow64SetThreadContext = k32.Wow64SetThreadContext
Wow64GetThreadContext.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
Wow64GetThreadContext.restype = ctypes.c_int
Wow64SetThreadContext.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
Wow64SetThreadContext.restype = ctypes.c_int


class WOW64_CONTEXT(ctypes.Structure):
    _fields_ = [("ContextFlags", wintypes.DWORD), ("Dr0", wintypes.DWORD),
                ("Dr1", wintypes.DWORD), ("Dr2", wintypes.DWORD),
                ("Dr3", wintypes.DWORD), ("Dr6", wintypes.DWORD),
                ("Dr7", wintypes.DWORD), ("FloatSave", ctypes.c_byte * 112),
                ("SegGs", wintypes.DWORD), ("SegFs", wintypes.DWORD),
                ("SegEs", wintypes.DWORD), ("SegDs", wintypes.DWORD),
                ("Edi", wintypes.DWORD), ("Esi", wintypes.DWORD),
                ("Ebx", wintypes.DWORD), ("Edx", wintypes.DWORD),
                ("Ecx", wintypes.DWORD), ("Eax", wintypes.DWORD),
                ("Ebp", wintypes.DWORD), ("Eip", wintypes.DWORD),
                ("SegCs", wintypes.DWORD), ("EFlags", wintypes.DWORD),
                ("Esp", wintypes.DWORD), ("SegSs", wintypes.DWORD),
                ("ExtendedRegisters", ctypes.c_byte * 512)]


class DEBUG_U(ctypes.Union):
    _fields_ = [("align", ctypes.c_ulonglong), ("buf", ctypes.c_byte * 168)]


class DEBUG_EVENT(ctypes.Structure):
    _fields_ = [("dwDebugEventCode", wintypes.DWORD), ("dwProcessId", wintypes.DWORD),
                ("dwThreadId", wintypes.DWORD), ("u", DEBUG_U)]


# ★★ 必须是「全套」标志。曾经写成 0x00010000|0x10（只有 DEBUG_REGISTERS），
#   于是 Wow64GetThreadContext 不填充 Eip/Ebp/Esp 等字段（读回来是 0），
#   而我随后「改一个字段整体写回」⇒ 把没读到的寄存器用 0 覆盖 ⇒ Dr0-D3 被清零、
#   Dr7 使能位却留着 ⇒ 目标带着指向 0 的使能断点跑 ⇒ 无人接收的 #DB ⇒ 崩溃。
WOW64_CONTEXT_FLAGS = 0x0010003F      # CONTEXT_i386 | CONTROL|INTEGER|SEGMENTS|FLOAT|DEBUG|EXTENDED


class Tracer:
    def __init__(self, pid):
        self.pid = pid
        self.h = k32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
        self.start = time.time()
        self.dev = 0
        self.vt = 0
        self.armed = {}          # tid -> {slot: tag}
        self.pending = {}
        self.frames = 0
        self.log = []
        self.fh = open(LOG, "w", encoding="utf-8")

    def say(self, rec):
        self.log.append(rec)
        self.fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self.fh.flush()

    def u32(self, addr):
        buf = ctypes.create_string_buffer(4)
        n = ctypes.c_size_t()
        if not k32.ReadProcessMemory(self.h, ctypes.c_void_p(addr), buf, 4, ctypes.byref(n)):
            return None
        return struct.unpack("<I", buf.raw)[0]

    def ctx(self, tid, setter=False):
        acc = (THREAD_GET_CONTEXT | (THREAD_SET_CONTEXT if setter else 0)
               | THREAD_SUSPEND_RESUME)
        ht = k32.OpenThread(acc, False, tid)
        if not ht:
            return None, None
        c = WOW64_CONTEXT()
        c.ContextFlags = WOW64_CONTEXT_FLAGS
        if not Wow64GetThreadContext(ctypes.c_void_p(ht), ctypes.byref(c)):
            k32.CloseHandle(ht)
            return None, None
        return ht, c

    def arm(self, tid, slot, addr, tag):
        """只在**被调试事件停住的**线程上改寄存器。

        ★ 不做 SuspendThread：调试器持有事件期间该线程本就停着，而
        SuspendThread 是**加计数**的——只要有一处忘记配平 ResumeThread，
        目标进程的线程就会被永久挂起（真实事故：17 个线程全冻住，画面声音全停，
        进程却还在）。宁可少一次保险，也不要这个风险。
        """
        ht, c = self.ctx(tid, setter=True)
        if not ht:
            return False
        setattr(c, f"Dr{slot}", addr)
        # ★★ x86 Dr7 的正确布局：L_s = bit 2s，G_s = bit 2s+1，**R/W 与 LEN 在 bit 16 以上**。
        #   曾经写成 (2 << 2s) | (1 << 2s)，以为高那位是 LEN=1 —— 实际设的是 **G 位** ✗。
        #   G=1 = 该断点在全任务（含内核态）生效，会把一个"调试器不在场时的 #DB"放大成
        #   无法处理的致命异常。执行断点只需要 L=1，LEN 保持 0（=1 字节）即可。
        c.Dr7 |= (1 << (slot * 2))          # 只置 L_s；G 位永远不碰
        ok = bool(Wow64SetThreadContext(ctypes.c_void_p(ht), ctypes.byref(c)))
        if ok:
            # ★ 回读校验：写入被静默忽略（ContextFlags 不全 / 权限不足）必须立刻大声失败，
            #   绝不能像以前那样"看似挂上了、其实是空的/被清零的" ⇒ 后面目标崩溃。
            v = WOW64_CONTEXT()
            v.ContextFlags = WOW64_CONTEXT_FLAGS
            if Wow64GetThreadContext(ctypes.c_void_p(ht), ctypes.byref(v)):
                got = getattr(v, f"Dr{slot}", 0)
                if got != addr or not (v.Dr7 & (1 << (slot * 2))):
                    print(f"  ✗ 挂断点【回读校验失败】tid={tid} 槽{slot}: "
                          f"期望 {addr:#x} 实得 {got:#x} Dr7={v.Dr7:#x} ⇒ 立即中止采集")
                    self.stop = True
                    k32.CloseHandle(ht)
                    return False
            else:
                print(f"  ✗ 挂断点后回读上下文失败 tid={tid} ⇒ 立即中止")
                self.stop = True
                k32.CloseHandle(ht)
                return False
            # ★ armed 存的是【tag 字符串】用于识别命中，地址必须另存一张表 ——
            #   曾经把 armed 当"槽→地址"用，于是 arm() 收到字符串当地址写进 Dr 直接 TypeError。
            self.armed.setdefault(tid, {})[slot] = tag
            if not hasattr(self, "slot_addr"):
                self.slot_addr = {}
            self.slot_addr.setdefault(tid, {})[slot] = addr
        k32.CloseHandle(ht)
        return ok

    def on_hit(self, tid):
        # ★★ 必须 setter=True：读取模式下的 ContextFlags 不含调试寄存器位，
        #    于是 Dr7 的写入会被系统静默忽略 —— 表现为"清了槽但断点仍然无限命中"。
        ht, c = self.ctx(tid, setter=True)
        if not ht:
            return
        pd = self.pending.pop(tid, None)
        if pd is not None:
            # 上一命中之后紧跟的这个事件就是 WX86 单步 ⇒ 无条件挂回。
            # ★ 不能靠 Dr6 判断：Dr6 的标志位在软件清除前一直保持置位，
            #   用它判断会把单步事件误当成"又一次命中" ⇒ 无限自旋 + 记录爆炸。
            self.arm(tid, pd[0], pd[1], pd[2])
            k32.CloseHandle(ht)
            return
        slot = next((i for i in range(4) if c.Dr6 & (1 << i)), None)
        if slot is None:
            k32.CloseHandle(ht)
            return
        tag = self.armed.get(tid, {}).get(slot, "?")
        ret = self.u32(c.Esp)
        self.recs += 1
        rec = {"t": round(time.time() - self.start, 3), "kind": tag, "slot": slot,
               "ret": hex(ret) if ret else None, "tid": tid, "esp": hex(c.Esp)}
        if tag in ("SetRenderTarget", "SetDepthStencilSurface"):
            # ★ 入口处参数布局：[esp]=返回地址, [esp+4]=第一个参数, [esp+8]=第二个参数。
            #   SetRenderTarget(DWORD i, IDirect3DSurface9* p) ⇒ arg1 就是那个表面指针，
            #   有了它就能判定每帧一次的离屏通道是阴影图还是镜面反射。
            rec["arg0"] = self.u32(c.Esp + 4)
            rec["arg1"] = self.u32(c.Esp + 8)
        self.say(rec)
        if tag == "Present":
            self.frames += 1
        if self.recs > self.max_recs:          # ★ 保险丝：不许无限写盘（自旋时能立刻止损）
            self.stop = True
        # 先清槽（含 Dr6 命中标志），等随后的 WX86 单步事件再挂回
        c.Dr6 = 0
        c.Dr7 &= ~((2 << (slot * 2)) | (1 << (slot * 2)))
        Wow64SetThreadContext(ctypes.c_void_p(ht), ctypes.byref(c))
        self.pending[tid] = (slot, self.slot_addr[tid][slot], tag)
        k32.CloseHandle(ht)

    def setup_dev(self):
        """读设备全局 → 读 vtable（不挂断点）。"""
        if self.dev:
            return True
        dev = self.u32(DEV_GLOBAL)
        if not dev:
            return False
        vt = self.u32(dev)
        if not vt:
            return False
        self.dev, self.vt = dev, vt
        self.say({"t": round(time.time() - self.start, 3), "kind": "note",
                  "msg": f"device=0x{dev:08x} vtable=0x{vt:08x}"})
        return True

    def arm_all(self, tid):
        """在这一个线程上挂齐四个槽的断点。"""
        if not self.setup_dev():
            return False
        ok = False
        for i, (name, sl) in enumerate(list(SLOT.items())[:4]):
            a = self.u32(self.vt + sl * 4)
            if a:
                ok = self.arm(tid, i, a, name) or ok
        return ok

    def setup(self, tid):
        return self.arm_all(tid)


def main():
    if len(sys.argv) < 2:
        print("用法: attach_trace.py <pid> [秒数]")
        return 1
    pid = int(sys.argv[1])
    secs = int(sys.argv[2]) if len(sys.argv) > 2 else 150
    tr = Tracer(pid)
    tr.recs, tr.max_recs, tr.stop = 0, 20000, False   # ★ 保险丝：记录上限 + 止损开关
    if not tr.h:
        print(f"✗ OpenProcess 失败 pid={pid} err={ctypes.get_last_error()}")
        return 1
    if not k32.DebugActiveProcess(pid):
        print(f"✗ DebugActiveProcess 失败 err={ctypes.get_last_error()}"
              f"（可能需要同架构/同权限；游戏正在运行？）")
        return 1
    print(f"✓ 已附着 pid={pid}，采集 {secs} 秒（结束时干净分离，不结束游戏）")
    ev = DEBUG_EVENT()
    deadline = time.time() + secs
    setup_done = False
    armed_threads = set()
    try:
        while time.time() < deadline and not tr.stop:
            if not k32.WaitForDebugEvent(ctypes.byref(ev), 500):
                continue
            code = ev.dwDebugEventCode
            tid = ev.dwThreadId
            status = DBG_CONTINUE
            if code == 1:                                   # EXCEPTION
                exc = struct.unpack_from("<I", bytes(ev.u.buf), 0)[0]
                if exc in (EXCEPTION_BREAKPOINT, WX86_BP, WX86_SINGLE_STEP):
                    if setup_done:
                        tr.on_hit(tid)
                else:
                    status = DBG_EXCEPTION_NOT_HANDLED
            elif code == 2:                                 # CREATE_THREAD
                # DebugActiveProcess 会为**每个已存在线程**发这个事件 —— 必须在这里
                # 逐个挂断点，否则只有第一个线程被挂上（渲染线程漏掉 ⇒ 一条记录都没有）。
                if setup_done or tr.dev:
                    if tr.arm_all(tid):
                        armed_threads.add(tid)
                        print(f"  + 线程 {tid} 已挂断点 (共 {len(armed_threads)} 个线程)")
            elif code == 3:                                 # CREATE_PROCESS
                pass
            elif code == 5:                                 # EXIT_PROCESS
                print("进程退出")
                tr.fh.close()
                return 0
            k32.ContinueDebugEvent(ev.dwProcessId, tid, status)
            if not setup_done:
                # 第一次事件后：读设备全局 → 挂断点。此时所有已有线程都该被覆盖
                if tr.setup(tid):
                    setup_done = True
                    print(f"✓ 断点已挂（device=0x{tr.dev:08x}），开始记录")
                time.sleep(0.05)
    finally:
        # 绝不移除进程：只干净分离
        try:
            # ★★ 退出顺序是铁律（dmp 铁证换来的一课）：
            #   1) 先清掉每个线程的硬件断点 —— 分离【不会】清 Dr 寄存器，残留的
            #      使能断点会让目标在无调试器时抛 #DB(STATUS_SINGLE_STEP) 直接崩；
            #   2) 再分离；
            #   3) 最后兜底解挂（SuspendThread 若没配平会把线程永久挂起）。
            try:
                from clear_dr import clear_dr as _clear
                c_, n_ = _clear(pid, verbose=False)
                print(f"✓ 已清除 {c_}/{n_} 个线程的硬件断点（防目标带残留断点崩溃）")
            except Exception as e:           # noqa: BLE001
                print(f"  (清理硬件断点失败: {e})  ← 注意：可能有残留！")
            k32.DebugActiveProcessStop(pid)
            print("✓ 已分离（游戏继续运行）")
            # ★ 保险丝：万一还有线程被挂起（历史事故：写反的 ResumeThread 条件把
            # 17 个线程永久冻住 —— 画面声音全停而进程还在），这里无条件解挂一次。
            try:
                from thaw import thaw as _thaw
                _thaw(pid)
            except Exception as e:           # noqa: BLE001
                print(f"  (自动解挂跳过: {e})")
        except Exception as e:
            print(f"分离异常: {e}")
        tr.fh.close()

    print(f"帧数 {tr.frames}；记录 {len(tr.log)} 条 -> {LOG.name}")
    kinds = {}
    for e in tr.log:
        kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
    print("  分类:", kinds)
    return 0


if __name__ == "__main__":
    sys.exit(main())
