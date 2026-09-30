"""一击即收：在**单个执行地址**上挂一条硬件断点，抓住第一个命中后立刻收手。

用途：确定 `0x564319`（全游戏唯一的音高设置函数）**是被谁调用的** —— 该函数
既无 E8 调用者、也无虚表指针引用（见 docs/34 §4），静态已穷尽。

★ 为什么一击即收：这个函数每帧都会被调用（高命中率）。挂住不放＝每帧停一次目标
（历史事故：DrawIndexedPrimitive 上的断点让画面声音全停）。所以第一个命中就
清断点 + 收工。

★ 断点挂在**函数第一条指令**上，命中时该指令尚未执行 ⇒ `[esp]` 就是**返回地址**
（无论进入方式是 call 还是 jmp 表——jmp 不压栈）。同时抓 40 个 dword 的栈窗口，
并自动挑出"看起来像返回地址"的项（v-5 处是 E8，且目标算得出来）交叉验证。

安全：全程复用 attach_trace.py 已验证的实现（ContextFlags 全套、Dr7 只置 L 位、
写入回读校验、finally 里 清断点→分离→兜底解挂 的顺序）。

用法: python tools/pinch_caller.py <pid> [目标地址] [秒数]
"""
import ctypes
import os
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import attach_trace as AT                      # noqa: E402

ROOT = Path(r"C:\Users\niko6\Desktop\Work\LASR_Reverse_Engineering")
# ★ 绝不覆盖 out_tracer.jsonl（那份赛道内采集有 20002 条记录）
AT.LOG = ROOT / "out_caller.jsonl"

TARGET = 0x564319
SECS = 25
STACK_DWORDS = 40
COUNT = 0          # >0 = 计数模式（最多收这么多次命中，用于判断"是否每帧调用"）


class Pinch(AT.Tracer):
    def __init__(self, pid):
        super().__init__(pid)
        self.hit = False

    # 只挂一条断点，不用基类的"四个 vtable 槽"
    def setup(self, tid):
        return self.arm(tid, 0, TARGET, "PITCH")

    def arm_all(self, tid):
        return self.setup(tid)

    def u8(self, addr):
        buf = ctypes.create_string_buffer(1)
        n = ctypes.c_size_t()
        if not ctypes.windll.kernel32.ReadProcessMemory(
                self.h, ctypes.c_void_p(addr), buf, 1, ctypes.byref(n)):
            return None
        return buf.raw[0]

    def ret_of(self, site):
        """site 处若是 E8 rel32，返回它的调用目标"""
        if self.u8(site) != 0xE8:
            return None
        b = ctypes.create_string_buffer(4)
        n = ctypes.c_size_t()
        if not ctypes.windll.kernel32.ReadProcessMemory(
                self.h, ctypes.c_void_p(site + 1), b, 4, ctypes.byref(n)):
            return None
        rel = struct.unpack("<i", b.raw)[0]
        return (site + 5 + rel) & 0xFFFFFFFF

    def on_hit(self, tid):
        # ★ setter=True 是必须的：读取模式下的 ContextFlags 不含调试寄存器位，
        #   清槽的写入会被静默忽略（历史 bug：886k 条自旋）。
        ht, c = self.ctx(tid, setter=True)
        if not ht:
            return
        # ★★ 附着后必然先收到一次「初始断点」（eip 落在 ntdll 的 DbgBreakPoint，
        #   实测 0x77cdc000，esp 高得读不到栈）—— 它不是我们的目标。必须用
        #   Eip 硬校验 + Dr6 槽位校验双重确认，否则会把垃圾当命中写盘；
        #   校验不过时【不清断点】（保持武装，等真命中）。
        if c.Eip != TARGET or not (c.Dr6 & (1 << 0)):
            AT.k32.CloseHandle(ht)
            return
        # ★ 计数模式下：上一命中之后的这个事件就是 WX86 单步 ⇒ 无条件挂回
        #   （基类同款机制；靠 Dr6 判断会把单步误当成"又一次命中"而无限自旋）
        if COUNT and self.pending.pop(tid, None) is not None:
            self.arm(tid, 0, TARGET, "PITCH")
            AT.k32.CloseHandle(ht)
            return
        rec = {"t": round(time.time() - self.start, 4), "kind": "PITCH-HIT", "tid": tid,
               "eip": hex(c.Eip), "esp": hex(c.Esp), "ebp": hex(c.Ebp),
               "eax": hex(c.Eax), "ebx": hex(c.Ebx), "ecx": hex(c.Ecx),
               "edx": hex(c.Edx), "esi": hex(c.Esi), "edi": hex(c.Edi),
               "eflags": hex(c.EFlags)}
        # ★ [esp] 就是返回地址
        rec["return_addr"] = hex(self.u32(c.Esp) or 0)
        # 栈窗口
        st = [self.u32(c.Esp + 4 * k) for k in range(STACK_DWORDS)]
        rec["stack"] = [hex(v) if v else None for v in st]
        # 自动挑"像返回地址"的项：v-5 处是 E8
        cand = []
        for k, v in enumerate(st):
            if not v:
                continue
            t = self.ret_of(v - 5)
            if t is not None:
                cand.append({"idx": k, "addr": hex(v), "call_site": hex(v - 5),
                             "call_target": hex(t)})
        rec["ret_candidates"] = cand
        # 参数（若函数以 __stdcall 直接取参）：[esp+4] 起
        rec["args"] = [hex(self.u32(c.Esp + 4 + 4 * k) or 0) for k in range(4)]
        self.say(rec)
        if COUNT:
            # 计数模式：清槽 → 记下 pending → 等随后的单步事件再挂回（防自旋）
            c.Dr6 = 0
            c.Dr7 &= ~(0x3 << 0)
            AT.Wow64SetThreadContext(ctypes.c_void_p(ht), ctypes.byref(c))
            self.pending[tid] = 1
            self.n_hits += 1
            if self.n_hits >= COUNT:
                self.stop = True
            AT.k32.CloseHandle(ht)
            return

        # ★★ 收到即收手：清掉这一槽，绝不挂回（高命中率地址的保命规则）
        c.Dr6 = 0
        c.Dr7 &= ~(0x3 << 0)                 # 清 L0/G0
        AT.Wow64SetThreadContext(ctypes.c_void_p(ht), ctypes.byref(c))
        v = AT.WOW64_CONTEXT()
        v.ContextFlags = AT.WOW64_CONTEXT_FLAGS
        if AT.Wow64GetThreadContext(ctypes.c_void_p(ht), ctypes.byref(v)):
            if (v.Dr7 & 0x3) or v.Dr0:
                print(f"  ✗ 清断点回读校验失败 Dr0={v.Dr0:#x} Dr7={v.Dr7:#x}")
            else:
                print(f"  ✓ 断点已清（回读校验通过）tid={tid}")
        ctypes.windll.kernel32.CloseHandle(ht)
        self.hit = True
        self.stop = True


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    pid = int(sys.argv[1])
    global TARGET
    if len(sys.argv) > 2:
        TARGET = int(sys.argv[2], 16)
    secs = int(sys.argv[3]) if len(sys.argv) > 3 else SECS
    global COUNT
    if "-n" in sys.argv:
        COUNT = int(sys.argv[sys.argv.index("-n") + 1])
        print(f"★ 计数模式：最多收 {COUNT} 次命中（判断是否每帧调用）")

    # 预检：清一遍所有线程的 Dr（顺带确认可写 + 当前无残留断点）
    try:
        from clear_dr import clear_dr
        cnt, tot = clear_dr(pid, verbose=False)
        print(f"✓ 预检 clear_dr：{cnt}/{tot} 个线程（无残留断点）")
    except Exception as e:                      # noqa: BLE001
        print(f"  (预检跳过: {e})")

    tr = Pinch(pid)
    tr.recs, tr.max_recs, tr.stop = 0, 50, False
    tr.n_hits = 0
    if not tr.h:
        print(f"✗ OpenProcess 失败 err={ctypes.get_last_error()}")
        return 1
    if not AT.k32.DebugActiveProcess(pid):
        print(f"✗ DebugActiveProcess 失败 err={ctypes.get_last_error()}")
        return 1
    print(f"✓ 已附着 pid={pid}；断点 {TARGET:#x}，最多等 {secs} 秒（一击即收）")

    ev = AT.DEBUG_EVENT()
    deadline = time.time() + secs
    setup_done = False
    threads = set()
    try:
        while time.time() < deadline and not tr.stop:
            if not AT.k32.WaitForDebugEvent(ctypes.byref(ev), 400):
                continue
            code, tid = ev.dwDebugEventCode, ev.dwThreadId
            status = AT.DBG_CONTINUE
            if code == 1:
                exc = struct.unpack_from("<I", bytes(ev.u.buf), 0)[0]
                if exc in (AT.EXCEPTION_BREAKPOINT, AT.WX86_BP, AT.WX86_SINGLE_STEP):
                    if setup_done:
                        tr.on_hit(tid)
                else:
                    status = AT.DBG_EXCEPTION_NOT_HANDLED
            elif code == 2:                      # CREATE_THREAD（含已存在线程）
                if setup_done:
                    if tr.setup(tid):
                        threads.add(tid)
                        print(f"  + 线程 {tid} 已挂断点（共 {len(threads)}）")
            elif code == 3:
                pass
            elif code == 5:
                print("进程退出")
                tr.fh.close()
                return 0
            AT.k32.ContinueDebugEvent(ev.dwProcessId, tid, status)
            if not setup_done:
                if tr.setup(tid):
                    setup_done = True
                    threads.add(tid)
                    print(f"✓ 断点已挂（首个线程 {tid}）")
    finally:
        try:
            try:
                from clear_dr import clear_dr as _clear
                c_, n_ = _clear(pid, verbose=False)
                print(f"✓ 已清除 {c_}/{n_} 个线程的硬件断点")
            except Exception as e:               # noqa: BLE001
                print(f"  (清断点失败: {e}) ← 注意可能有残留！")
            AT.k32.DebugActiveProcessStop(pid)
            print("✓ 已分离（游戏继续运行）")
            try:
                from thaw import thaw as _thaw
                _thaw(pid)
            except Exception as e:               # noqa: BLE001
                print(f"  (自动解挂跳过: {e})")
        except Exception as e:
            print(f"分离异常: {e}")
        tr.fh.close()
    print(f"\n命中 {len(tr.log)} 次 → {AT.LOG.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
