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


def select_tab(root, want):
    """按标签文字选中 Notebook 的一页（在整棵控件树里找 TNotebook）。"""
    stack = [root]
    while stack:
        w = stack.pop()
        try:
            kids = w.winfo_children()
        except Exception:  # noqa: BLE001
            continue
        if w.winfo_class() == "TNotebook" and want:
            for t in w.tabs():
                if want in w.tab(t, "text"):
                    w.select(t)
                    return True
        stack.extend(kids)
    return False


def main():
    tool = sys.argv[1] if len(sys.argv) > 1 else "vehicle"
    out = sys.argv[2] if len(sys.argv) > 2 else "shot.png"
    tab = None
    for a in sys.argv[1:]:
        if a.startswith("--tab="):
            tab = a.split("=", 1)[1]
    if tool == "vehicle":
        spec = importlib.util.spec_from_file_location(
            "vedit", HERE / "vehicle_editor.pyw")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        root = tk.Tk()
        root.geometry("1180x760")
        app = mod.App(root)
        pump(root)
        car = sys.argv[3] if len(sys.argv) > 3 and not sys.argv[3].startswith("-") \
            else "Phoenix_RS_1997"
        names = [app.lb_car.get(i) for i in range(app.lb_car.size())]
        if car in names:
            app.lb_car.selection_set(names.index(car))
            app.on_car()
            pump(root)
            flt = sys.argv[4] if len(sys.argv) > 4 \
                and not sys.argv[4].startswith("-") else "IEngine"
            app.var_filter.set(flt)
            pump(root)
            # 选哪一个：默认挑「零件类」（同名 Item 类没有数据）；可用 --part= 精确指定
            exact = None
            for a in sys.argv[1:]:
                if a.startswith("--part="):
                    exact = a.split("=", 1)[1]
            names_p = [app.lb_part.get(i) for i in range(app.lb_part.size())]
            if exact and exact in names_p:
                idx = names_p.index(exact)
            else:
                cand = [i for i, n in enumerate(names_p) if "_I" not in n[:16]]
                idx = (cand or [0])[0]
            app.lb_part.selection_set(idx)
            app.on_part()
            pump(root, 30)
    else:
        spec = importlib.util.spec_from_file_location(
            "sedit", HERE / "save_editor.pyw")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        root = tk.Tk()
        root.geometry("1180x760")
        app = mod.App(root)
        if len(sys.argv) > 3 and not sys.argv[3].startswith("-"):
            app.var_path.set(sys.argv[3])
            app.load()
        pump(root, 20)
        demo = any(a == "--demo" for a in sys.argv[1:])
        if demo and app.s is not None:
            # 截图用演示数据：只在**临时副本**上做（改昵称/加车/加零件），绝不碰真实存档
            from lasr_core import savefile as _sf
            app.s["nickName"] = "Demo Driver"
            app.s["prestige"] = 1234
            app.s["winSum"], app.s["raceSum"] = 12, 15
            _sf.save(app.s, sys.argv[3], backup=False)
            app.load()
            pump(root, 10)
            for v in (8, 5):
                app.var_add_car.set("%d = %s" % (v, _sf.vehicle_name(v)))
                app.add_car()
            pump(root, 6)
            kids = app.tv_cars.get_children()
            if kids:
                app.tv_cars.selection_set(kids[0])
                pump(root, 4)
                for case in (5, 81, 2053):
                    app.var_case.set(str(case))
                    app.add_part(1)
            pump(root, 10)
        pump(root, 10)
    select_tab(root, tab)
    root.update_idletasks()
    pump(root, 12)
    hwnd = user32.GetAncestor(root.winfo_id(), 2)
    root.lift()
    root.attributes("-topmost", True)
    pump(root, 14)
    grab(hwnd, out)
    print("saved", out)
    root.destroy()


if __name__ == "__main__":
    main()
