"""Health probe: run LASR.exe WITHOUT the debugger and report what it actually does.

Separates "the game hangs on its own" from "my debugger breaks it":
  - does it create a window (and what title/class)?
  - does d3d9 / d3dx9_30 ever get loaded?
  - is it burning CPU (working) or idle (blocked)?
  - does it append to its own diag.log?
"""
import ctypes
import json
import struct
import subprocess
import sys
import time
from ctypes import wintypes as wt
from pathlib import Path

EXE = r"C:\Games\LASR\LASR.exe"
GAME = Path(r"C:\Games\LASR")

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
psapi = ctypes.WinDLL("psapi", use_last_error=True)
user32 = ctypes.WinDLL("user32", use_last_error=True)

PROCESS_QUERY_INFORMATION = 0x0400 | 0x0010
k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
k32.OpenProcess.restype = wt.HANDLE
psapi.EnumProcessModules.argtypes = [wt.HANDLE, ctypes.c_void_p, wt.DWORD,
                                     ctypes.POINTER(wt.DWORD)]
psapi.GetModuleFileNameExW.argtypes = [wt.HANDLE, wt.HMODULE, wt.LPWSTR, wt.DWORD]

WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)


def windows_of(pid):
    out = []

    def cb(hwnd, _):
        q = wt.DWORD(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(q))
        if q.value == pid:
            n = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, n, 256)
            c = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, c, 256)
            vis = user32.IsWindowVisible(hwnd)
            out.append({"hwnd": int(hwnd), "title": n.value, "class": c.value,
                        "visible": bool(vis)})
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return out


def modules_of(pid):
    h = k32.OpenProcess(PROCESS_QUERY_INFORMATION, False, pid)
    if not h:
        return []
    mods = (wt.HMODULE * 1024)()
    need = wt.DWORD(0)
    names = []
    if psapi.EnumProcessModules(h, mods, ctypes.sizeof(mods), ctypes.byref(need)):
        n = need.value // ctypes.sizeof(wt.HMODULE)
        for i in range(n):
            p = ctypes.create_unicode_buffer(512)
            if psapi.GetModuleFileNameExW(h, mods[i], p, 512):
                names.append(p.value)
    k32.CloseHandle(h)
    return names


def cpu_times(pid):
    h = k32.OpenProcess(0x0400, False, pid)
    if not h:
        return None
    a, b, c, d = (ctypes.c_ulonglong(0) for _ in range(4))
    total, empty = ctypes.c_ulonglong(0), ctypes.c_ulonglong(0)  # placeholder
    k32.GetProcessTimes(h, ctypes.byref(a), ctypes.byref(b),
                        ctypes.byref(c), ctypes.byref(d))
    k32.CloseHandle(h)
    return c.value


k32.GetProcessTimes.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                ctypes.c_void_p, ctypes.c_void_p]

gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
user32.GetDC.argtypes = [wt.HWND]
user32.GetDC.restype = wt.HDC
user32.GetClientRect.argtypes = [wt.HWND, ctypes.c_void_p]
gdi32.CreateCompatibleDC.argtypes = [wt.HDC]
gdi32.CreateCompatibleDC.restype = wt.HDC
gdi32.CreateCompatibleBitmap.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int]
gdi32.CreateCompatibleBitmap.restype = wt.HANDLE
gdi32.SelectObject.argtypes = [wt.HDC, wt.HANDLE]
gdi32.SelectObject.restype = wt.HANDLE
gdi32.BitBlt.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                         ctypes.c_int, wt.HDC, ctypes.c_int, ctypes.c_int, wt.DWORD]
gdi32.DeleteObject.argtypes = [wt.HANDLE]
gdi32.DeleteDC.argtypes = [wt.HDC]
gdi32.GetDIBits.argtypes = [wt.HDC, wt.HANDLE, wt.UINT, wt.UINT,
                            ctypes.c_void_p, ctypes.c_void_p, wt.UINT]
gdi32.GetDIBits.restype = ctypes.c_int
user32.ReleaseDC.argtypes = [wt.HWND, wt.HDC]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wt.DWORD), ("biWidth", ctypes.c_long),
                ("biHeight", ctypes.c_long), ("biPlanes", wt.WORD),
                ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
                ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wt.DWORD),
                ("biClrImportant", wt.DWORD)]


def window_signature(hwnd):
    """Hash the window's own pixels: is it actually drawing anything?

    Capture through BitBlt + GetDIBits (no compiler, no screen grab of the whole
    desktop) and sample every 8th pixel so it stays cheap.
    """
    r = wt.RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(r)):
        return None
    w, h = r.right - r.left, r.bottom - r.top
    if w <= 0 or h <= 0:
        return None
    hdc = user32.GetDC(hwnd)
    mdc = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    old = gdi32.SelectObject(mdc, bmp)
    gdi32.BitBlt(mdc, 0, 0, w, h, hdc, 0, 0, 0x00CC0020)     # SRCCOPY
    bi = BITMAPINFOHEADER()
    bi.biSize = ctypes.sizeof(bi)
    bi.biWidth = w
    bi.biHeight = -h                    # top-down
    bi.biPlanes = 1
    bi.biBitCount = 32
    bi.biCompression = 0
    buf = (ctypes.c_ubyte * (w * h * 4))()
    rows = gdi32.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bi), 0)
    gdi32.SelectObject(mdc, old)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mdc)
    user32.ReleaseDC(hwnd, hdc)
    if not rows:
        return None
    import hashlib
    d = bytes(buf[::8 * 4]) if False else bytes(buf)[::32]
    return (w, h, hashlib.md5(d).hexdigest()[:12], sum(buf[::1024]))


def main():
    before = GAME.joinpath("diag.log").read_bytes() if GAME.joinpath("diag.log").exists() else b""
    print(f"diag.log 之前大小 = {len(before)}")
    p = subprocess.Popen([EXE], cwd=str(GAME))
    print(f"启动 pid={p.pid}（无调试器）")

    def sig_of(pid):
        ws = [w for w in windows_of(pid) if w["visible"] and w["class"] == "INVICTUS"]
        return window_signature(ws[0]["hwnd"]) if ws else None

    last = None
    for i in range(1, 13):                      # 15 s x 12 = 180 s
        time.sleep(15)
        if p.poll() is not None:
            print(f"  {i*15}s: 进程已退出, code={p.returncode}")
            break
        cpu = cpu_times(p.pid)
        sig = sig_of(p.pid)
        mods = modules_of(p.pid)
        key = [m.split("\\")[-1] for m in mods
               if any(s in m.lower() for s in ("d3d8", "d3d9", "ddraw", "opengl", "fmod"))]
        changed = "变化✓" if (sig and last and sig[2] != last[2]) else \
                  ("静止✗" if sig and last else "首次")
        print(f"  {i*15:4d}s CPU={cpu} 窗口={(sig[0], sig[1]) if sig else None} "
              f"像素={sig[2] if sig else None} {changed} 模块={key}")
        last = sig
    alive = p.poll() is None
    print(f"存活={alive}")
    if alive:
        p.terminate()
        time.sleep(2)
        if p.poll() is None:
            p.kill()
    after = GAME.joinpath("diag.log").read_bytes() if GAME.joinpath("diag.log").exists() else b""
    print("diag.log 新增:", after[len(before):].decode("latin1", "replace") or "(无)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
