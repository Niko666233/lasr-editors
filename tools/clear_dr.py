"""清除某个进程【所有线程】的硬件断点寄存器（Dr0-Dr3 / Dr6 / Dr7）。

为什么必须有这个东西（真实事故，有 dmp 铁证）：
把硬件执行断点挂到游戏线程上以后，**分离调试器并不会清除 Dr 寄存器** —— 它们是
每线程的 CPU 状态。我的采集器退出后，游戏就带着 4 个仍然使能的硬件断点继续运行：
下一次执行到被挂钩的 d3d9 方法 ⇒ CPU 抛 #DB(STATUS_SINGLE_STEP 0x80000004) ⇒
已经没人接收 ⇒ 致命异常 ⇒ 游戏崩溃。

证据（游戏自带的崩溃转储 DebugInfo_*.dmp，用 tools/dump_info.py 读出来）：
    Dr7 = 0x0000007F            ← 四个槽全使能
    Dr0=0x6A5E05D0  Dr3=0x6A561040
    异常地址 = 0x6A561040       ← 与我挂在槽 3 的地址【完全一致】
    Dr6 = 0x55                  ← B0/B2 命中标志置位

正确姿势（顺序很重要）：
  SuspendThread 一个线程 → 此时它停了 → Wow64SetThreadContext 清零 → **无条件 ResumeThread**
SuspendThread 加的是计数，ResumeThread 必须无条件配对 —— 写成 "was > 0 才 resume"
会让线程被永久挂起（另一个真实事故：17 个线程全冻住、画面声音全停、进程却还在）。

用法: python tools/clear_dr.py <pid>        # 也可给进程名，如 LASR.exe
"""
import ctypes
import sys
from ctypes import wintypes

k32 = ctypes.WinDLL("kernel32", use_last_error=True)

TH32CS_SNAPTHREAD = 0x00000004
THREAD_SUSPEND_RESUME = 0x0002
THREAD_GET_CONTEXT = 0x0008
THREAD_SET_CONTEXT = 0x0010
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


class THREADENTRY32(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                ("th32ThreadID", wintypes.DWORD), ("th32OwnerProcessID", wintypes.DWORD),
                ("tpBasePri", wintypes.LONG), ("tpDeltaPri", wintypes.LONG),
                ("dwFlags", wintypes.DWORD)]


class WOW64_CONTEXT(ctypes.Structure):
    # 只需要 Dr 区 + 一点点尾部；按标准 x86 CONTEXT 布局留足空间
    _fields_ = [("ContextFlags", wintypes.DWORD),
                ("Dr0", wintypes.DWORD), ("Dr1", wintypes.DWORD),
                ("Dr2", wintypes.DWORD), ("Dr3", wintypes.DWORD),
                ("Dr6", wintypes.DWORD), ("Dr7", wintypes.DWORD),
                ("FloatSave", ctypes.c_ubyte * 112),
                ("SegGs", wintypes.DWORD), ("SegFs", wintypes.DWORD),
                ("SegEs", wintypes.DWORD), ("SegDs", wintypes.DWORD),
                ("Edi", wintypes.DWORD), ("Esi", wintypes.DWORD),
                ("Ebx", wintypes.DWORD), ("Edx", wintypes.DWORD),
                ("Ecx", wintypes.DWORD), ("Eax", wintypes.DWORD),
                ("Ebp", wintypes.DWORD), ("Eip", wintypes.DWORD),
                ("SegCs", wintypes.DWORD), ("EFlags", wintypes.DWORD),
                ("Esp", wintypes.DWORD), ("SegSs", wintypes.DWORD),
                ("ExtendedRegisters", ctypes.c_ubyte * 512)]


Wow64GetThreadContext = k32.Wow64GetThreadContext
Wow64SetThreadContext = k32.Wow64SetThreadContext
for fn in (Wow64GetThreadContext, Wow64SetThreadContext):
    fn.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    fn.restype = wintypes.BOOL

k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
k32.Thread32First.argtypes = [wintypes.HANDLE, ctypes.POINTER(THREADENTRY32)]
k32.Thread32Next.argtypes = [wintypes.HANDLE, ctypes.POINTER(THREADENTRY32)]
k32.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
k32.OpenThread.restype = wintypes.HANDLE
k32.SuspendThread.argtypes = [wintypes.HANDLE]
k32.SuspendThread.restype = wintypes.DWORD
k32.ResumeThread.argtypes = [wintypes.HANDLE]
k32.ResumeThread.restype = wintypes.DWORD


def find_pid(name):
    import subprocess
    out = subprocess.run(["tasklist"], capture_output=True, text=True).stdout
    for line in out.splitlines():
        if line.lower().startswith(name.lower()):
            parts = line.split()
            if len(parts) > 1 and parts[1].isdigit():
                return int(parts[1])
    return None


def threads_of(pid):
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)
    if snap == INVALID_HANDLE_VALUE:
        return []
    te = THREADENTRY32()
    te.dwSize = ctypes.sizeof(THREADENTRY32)
    out = []
    ok = k32.Thread32First(snap, ctypes.byref(te))
    while ok:
        if te.th32OwnerProcessID == pid:
            out.append(te.th32ThreadID)
        ok = k32.Thread32Next(snap, ctypes.byref(te))
    k32.CloseHandle(snap)
    return out


def clear_dr(pid, verbose=True):
    """清除 pid 所有线程的硬件断点。返回 (清除成功数, 线程总数)。"""
    tids = threads_of(pid)
    if not tids:
        print(f"✗ 找不到进程 {pid} 的线程")
        return 0, 0
    cleared = 0
    for tid in tids:
        ht = k32.OpenThread(THREAD_SUSPEND_RESUME | THREAD_GET_CONTEXT | THREAD_SET_CONTEXT,
                            False, tid)
        if not ht:
            if verbose:
                print(f"  线程 {tid}: OpenThread 失败 (err={ctypes.get_last_error()})")
            continue
        k32.SuspendThread(ht)                      # ← 加计数
        c = WOW64_CONTEXT()
        # ★★ ContextFlags 必须包含 CONTEXT_DEBUG_REGISTERS = 0x10！
        #    写成 0x00100007 (=CONTROL|INTEGER|SEGMENTS) 会漏掉调试寄存器位，
        #    于是 Wow64SetThreadContext 静默忽略 Dr0-Dr7 ⇒ "清断点"变成空操作 ⇒
        #    目标带着残留断点在无调试器时抛 #DB 崩溃。用 ALL(0x3F) 最保险。
        c.ContextFlags = 0x0010003F                # CONTEXT_i386 | ALL
        if Wow64GetThreadContext(ht, ctypes.byref(c)):
            had = c.Dr7 & 0xFF
            c.Dr0 = c.Dr1 = c.Dr2 = c.Dr3 = 0
            c.Dr6 = 0
            c.Dr7 = 0
            if Wow64SetThreadContext(ht, ctypes.byref(c)):
                # ★ 回读校验：静默失败必须变成大声失败
                v = WOW64_CONTEXT()
                v.ContextFlags = 0x0010003F
                if Wow64GetThreadContext(ht, ctypes.byref(v)):
                    if (v.Dr0 or v.Dr1 or v.Dr2 or v.Dr3 or v.Dr6 or (v.Dr7 & 0xFF)):
                        if verbose:
                            print(f"  线程 {tid}: ✗ 清断点未生效！"
                                  f"回读 Dr0={v.Dr0:#x} Dr7={v.Dr7:#x}（需要管理员/更高的访问权）")
                    else:
                        cleared += 1
                        if verbose:
                            print(f"  线程 {tid}: ✓ 已清（回读校验通过）"
                                  + (f" [原本低位=0x{had:02X}]" if had else ""))
                elif verbose:
                    print(f"  线程 {tid}: 回读失败 (err={ctypes.get_last_error()})")
            elif verbose:
                print(f"  线程 {tid}: 写上下文失败 (err={ctypes.get_last_error()})")
        elif verbose:
            print(f"  线程 {tid}: 读上下文失败 (err={ctypes.get_last_error()})")
        k32.ResumeThread(ht)                       # ★ 无条件配对，绝不条件化
        k32.CloseHandle(ht)
    return cleared, len(tids)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    arg = sys.argv[1]
    pid = int(arg) if arg.isdigit() else find_pid(arg)
    if not pid:
        print(f"✗ 找不到进程 {arg}")
        sys.exit(1)
    print(f"清除进程 {pid} 的全部硬件断点寄存器……")
    cleared, total = clear_dr(pid)
    print(f"\n✓ {cleared}/{total} 个线程已清（这些线程从此不会再因残留断点崩溃）")
