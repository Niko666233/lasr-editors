"""抓一张 GUI 真图（PrintWindow，Tk 窗口用 ImageGrab 常常全黑）。

用法: python screenshot_gui.py <tool> <out.png> [car] [filter]
     <tool> = vehicle | save
"""
import ctypes
import ctypes.wintypes as wt
import importlib.util
import sys
import time
import tkinter as tk
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32


def grab(hwnd, path):
    rect = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    w, h = rect.right - rect.left, rect.bottom - rect.top
    hdc = user32.GetWindowDC(hwnd)
    mem = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    gdi32.SelectObject(mem, bmp)
    # 2 = PW_RENDERFULLCONTENT (needed for composited / DWM windows)
    user32.PrintWindow(hwnd, mem, 2)

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG),
                    ("biHeight", wt.LONG), ("biPlanes", wt.WORD),
                    ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
                    ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", wt.LONG),
                    ("biYPelsPerMeter", wt.LONG), ("biClrUsed", wt.DWORD),
                    ("biClrImportant", wt.DWORD)]

    bi = BITMAPINFOHEADER()
    bi.biSize = ctypes.sizeof(bi)
    bi.biWidth, bi.biHeight = w, -h
    bi.biPlanes, bi.biBitCount = 1, 32
    bi.biCompression = 0
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(bi), 0)
    img = Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1)
    img.convert("RGB").save(path)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mem)
    user32.ReleaseDC(hwnd, hdc)
    return path


def pump(root, n=20, dt=0.04):
    for _ in range(n):
        root.update()
        time.sleep(dt)


def main():
    tool = sys.argv[1] if len(sys.argv) > 1 else "vehicle"
    out = sys.argv[2] if len(sys.argv) > 2 else "shot.png"
    if tool == "vehicle":
        spec = importlib.util.spec_from_file_location(
            "vedit", HERE / "vehicle_editor.pyw")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        root = tk.Tk()
        app = mod.App(root)
        pump(root)
        car = sys.argv[3] if len(sys.argv) > 3 else "Phoenix_RS_1997"
        names = [app.lb_car.get(i) for i in range(app.lb_car.size())]
        if car in names:
            app.lb_car.selection_set(names.index(car))
            app.on_car()
            pump(root)
            app.var_filter.set(sys.argv[4] if len(sys.argv) > 4 else "IEngine")
            pump(root)
            app.lb_part.selection_set(0)
            app.on_part()
            pump(root, 30)
    else:
        spec = importlib.util.spec_from_file_location(
            "sedit", HERE / "save_editor.pyw")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        root = tk.Tk()
        app = mod.App(root)
        if len(sys.argv) > 3:
            app.var_path.set(sys.argv[3])
            app.load()
        pump(root, 30)
    root.update_idletasks()
    hwnd = user32.GetAncestor(root.winfo_id(), 2)
    root.lift()
    root.attributes("-topmost", True)
    pump(root, 10)
    grab(hwnd, out)
    print("saved", out)
    root.destroy()


if __name__ == "__main__":
    main()
