"""硬件断点"写入 → 回读 → 清除 → 回读"往返自测（在一个一次性进程上做）。

为什么必须先做这个：往游戏进程里写 Dr 寄存器，如果 ContextFlags 少了
CONTEXT_DEBUG_REGISTERS(0x10)，Wow64SetThreadContext **会静默忽略** Dr 字段 ——
写入看似成功、实际是空操作。这个错误已经让用户的游戏崩了两次（有 dmp 为证：
Dr7=0x7F 残留 ⇒ 无调试器时 #DB 直接致命）。所以：任何要碰游戏的 Dr 操作，
必须先在一个**可以随便死的**进程上验证往返成功。

流程：起一个只 sleep 的子进程 → 在它的主线程上写 Dr0/Dr7 → 回读断言 →
调用 clear_dr 清除 → 再回读断言全零 → 打印结论 → 杀掉子进程。

用法: python tools/test_dr_roundtrip.py
"""
import ctypes
import subprocess
import sys
import time
from ctypes import wintypes

sys.path.insert(0, __file__.rsplit("\\", 1)[0])
from clear_dr import (THREADENTRY32, TH32CS_SNAPTHREAD, WOW64_CONTEXT,  # noqa: E402
                      Wow64GetThreadContext, Wow64SetThreadContext, clear_dr, k32)

THREAD_GET_CONTEXT = 0x0008
THREAD_SET_CONTEXT = 0x0010
THREAD_SUSPEND_RESUME = 0x0002
CTX_ALL = 0x0010003F


def thread_ids_of(pid):
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)
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


def read_dr(ht):
    c = WOW64_CONTEXT()
    c.ContextFlags = CTX_ALL
    if not Wow64GetThreadContext(ht, ctypes.byref(c)):
        return None
    return c


def main():
    # ★ 靶子必须是 **32 位（WOW64）** 进程：Wow64GetThreadContext 只对 WOW64 进程有效。
    #   第一版拿 64 位的 sys.executable 当靶子 ⇒ 读上下文直接失败（测试自身的问题，
    #   不是工具的问题）。SysWOW64 目录里的是真正的 32 位系统程序，正好当靶子。
    import os
    for cand in (r"C:\Windows\SysWOW64\ping.exe", r"C:\Windows\SysWOW64\notepad.exe",
                 r"C:\Windows\SysWOW64\cmd.exe"):
        if os.path.exists(cand):
            target = cand
            break
    else:
        print("✗ 找不到 32 位靶子进程")
        return 1
    argv = [target] + (["-n", "120", "127.0.0.1"] if "ping" in target else [])
    child = subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    pid = child.pid
    print(f"一次性 32 位子进程 pid={pid} ({target}，随便它死)")
    time.sleep(1.5)
    tids = thread_ids_of(pid)
    if not tids:
        print("✗ 找不到子进程线程")
        child.kill()
        return 1
    tid = tids[0]
    print(f"目标线程 tid={tid}")

    ht = k32.OpenThread(THREAD_SUSPEND_RESUME | THREAD_GET_CONTEXT | THREAD_SET_CONTEXT,
                        False, tid)
    if not ht:
        print(f"✗ OpenThread 失败 err={ctypes.get_last_error()}")
        child.kill()
        return 1

    print("\n--- 0) ContextFlags 对照（根因验证：为什么旧的会清零寄存器）---")
    k32.SuspendThread(ht)
    for flags, label in ((0x00010010, "旧 0x100010（只有 DEBUG_REGISTERS）"),
                         (0x0010003F, "新 0x10003F（CONTROL|INTEGER|SEGMENTS|FLOAT|DEBUG|EXT）")):
        c = WOW64_CONTEXT()
        c.ContextFlags = flags
        if Wow64GetThreadContext(ht, ctypes.byref(c)):
            print(f"   {label}\n      → Esp={c.Esp:#x}  Ebp={c.Ebp:#x}  Eip={c.Eip:#x}"
                  + ("   ✗ 这些字段没被填充 ⇒ 整体写回就会把它们清零"
                     if (c.Esp | c.Ebp | c.Eip) == 0 else "   ✓ 已填充，可安全做读改写"))
    k32.ResumeThread(ht)

    print("\n--- 1) 写入测试：挂一个永远不会执行的地址 ---")
    k32.SuspendThread(ht)
    c = read_dr(ht)
    if c is None:
        print("✗ 读上下文失败")
        k32.ResumeThread(ht); k32.CloseHandle(ht); child.kill()
        return 1
    FAKE = 0x00401000                      # 子进程不会执行到这里
    c.Dr0 = FAKE
    c.Dr7 |= 1                             # 槽 0 使能, LEN=1
    if not Wow64SetThreadContext(ht, ctypes.byref(c)):
        print(f"✗ 写上下文失败 err={ctypes.get_last_error()}")
    v = read_dr(ht)
    armed_ok = bool(v and v.Dr0 == FAKE and (v.Dr7 & 1))
    print(f"   写入 Dr0={FAKE:#x} Dr7|=1")
    print(f"   回读 Dr0={v.Dr0:#x} Dr7={v.Dr7:#x}  →  {'✓ 写入生效' if armed_ok else '✗ 写入被忽略'}")
    k32.ResumeThread(ht)
    k32.CloseHandle(ht)

    print("\n--- 2) 清除测试：调用 clear_dr ---")
    cleared, total = clear_dr(pid, verbose=False)
    print(f"   clear_dr 报告 {cleared}/{total} 个线程被清")

    print("\n--- 3) 回读校验：应当全零 ---")
    ht = k32.OpenThread(THREAD_SUSPEND_RESUME | THREAD_GET_CONTEXT | THREAD_SET_CONTEXT,
                        False, tid)
    k32.SuspendThread(ht)
    v = read_dr(ht)
    zero = bool(v and not (v.Dr0 or v.Dr1 or v.Dr2 or v.Dr3 or v.Dr6 or (v.Dr7 & 0xFF)))
    print(f"   回读 Dr0={v.Dr0:#x} Dr1={v.Dr1:#x} Dr2={v.Dr2:#x} Dr3={v.Dr3:#x} "
          f"Dr6={v.Dr6:#x} Dr7={v.Dr7:#x}")
    k32.ResumeThread(ht)
    k32.CloseHandle(ht)

    print("\n=== 结论 ===")
    print(f"  写入生效   : {'✓' if armed_ok else '✗'}")
    print(f"  清除生效   : {'✓' if zero else '✗ ← 绝不能拿游戏试！'}")
    print("  ⇒ 机制可用，可以安全地在游戏上用了" if (armed_ok and zero)
          else "  ⇒ 机制有问题，先修工具，不要碰游戏")
    child.kill()
    return 0 if (armed_ok and zero) else 1


if __name__ == "__main__":
    sys.exit(main())
