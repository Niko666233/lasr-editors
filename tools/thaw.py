"""把某个进程的所有线程解除挂起（救活被调试器/工具误挂起的进程）。

背景（真实事故）：调试器代码里写了
    was = SuspendThread(ht)
    ...
    if was > 0: ResumeThread(ht)      # ← 错
SuspendThread 是**加计数**，必须无条件 ResumeThread 一次。条件写错 ⇒ 自己加的
那次挂起永远不撤销 ⇒ 目标进程所有线程被永久挂起 ⇒ 画面声音全停，但进程仍在。

本工具从外部枚举该进程的全部线程并反复 ResumeThread 直到挂起计数归零。
只改挂起状态：对未被挂起的线程 ResumeThread 是无效操作(返回 0xffffffff)，安全。

用法: python tools/thaw.py <pid>
"""
import ctypes
import sys
from ctypes import wintypes

k32 = ctypes.WinDLL("kernel32", use_last_error=True)

TH32CS_SNAPTHREAD = 0x00000004
THREAD_SUSPEND_RESUME = 0x0002
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


class THREADENTRY32(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                ("th32ThreadID", wintypes.DWORD), ("th32OwnerProcessID", wintypes.DWORD),
                ("tpBasePri", wintypes.LONG), ("tpDeltaPri", wintypes.LONG),
                ("dwFlags", wintypes.DWORD)]


k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
k32.Thread32First.argtypes = [wintypes.HANDLE, ctypes.POINTER(THREADENTRY32)]
k32.Thread32Next.argtypes = [wintypes.HANDLE, ctypes.POINTER(THREADENTRY32)]
k32.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
k32.OpenThread.restype = wintypes.HANDLE
k32.ResumeThread.argtypes = [wintypes.HANDLE]
k32.ResumeThread.restype = wintypes.DWORD


def thaw(pid):
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)
    if snap == INVALID_HANDLE_VALUE:
        print("✗ 创建线程快照失败")
        return 1
    te = THREADENTRY32()
    te.dwSize = ctypes.sizeof(THREADENTRY32)
    ok = k32.Thread32First(snap, ctypes.byref(te))
    threads = []
    while ok:
        if te.th32OwnerProcessID == pid:
            threads.append(te.th32ThreadID)
        ok = k32.Thread32Next(snap, ctypes.byref(te))
    print(f"进程 {pid} 的线程 {len(threads)} 个: {threads}")
    fixed = 0
    for tid in threads:
        ht = k32.OpenThread(THREAD_SUSPEND_RESUME, False, tid)
        if not ht:
            print(f"  线程 {tid}: OpenThread 失败")
            continue
        resumed = 0
        for _ in range(12):                      # 挂起计数可能大于 1
            r = k32.ResumeThread(ht)
            if r == 0xFFFFFFFF or r == 0:        # 无效或计数已为 0
                if r == 0:
                    resumed += 1
                break
            resumed += 1
        if resumed:
            fixed += 1
            print(f"  线程 {tid}: 解除 {resumed} 次挂起")
        k32.CloseHandle(ht)
    print(f"\n✓ 共解除 {fixed}/{len(threads)} 个线程的挂起")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: thaw.py <pid>")
        sys.exit(1)
    sys.exit(thaw(int(sys.argv[1])))
