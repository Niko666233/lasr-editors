"""决定性验证：**把 unicorn 完全封掉**，两个工具还能不能用。

打包成 exe 时 unicorn 被 --exclude-module 排除（它的 JIT 在 frozen exe 里
0xC0000409，见 docs/60 §6）。这个测试用一个 import 钩子让 `import unicorn` 直接
ModuleNotFoundError，然后跑完两个 GUI 的真实流程 —— 通过就说明 exe 会正常работать。
"""
import importlib.util
import os
import shutil
import sys
import time
import tkinter as tk
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

FAILS = []


def check(cond, label, extra=""):
    print("%s %s %s" % ("✓" if cond else "✗", label, extra))
    if not cond:
        FAILS.append(label)


class Blocker:
    """禁止 import unicorn / capstone（模拟 exe 里的模块缺失）。"""

    def find_module(self, name, path=None):
        if name.split(".")[0] in ("unicorn", "capstone"):
            return self
        return None

    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in ("unicorn", "capstone"):
            raise ModuleNotFoundError("No module named %r (被测试封掉)" % name)
        return None


sys.meta_path.insert(0, Blocker())
try:
    import unicorn  # noqa: F401
    check(False, "unicorn 已被封掉")
except ModuleNotFoundError:
    check(True, "unicorn 已被封掉（模拟 exe）")


def pump(root, n=8, dt=0.04):
    for _ in range(n):
        root.update()
        time.sleep(dt)


def load_pyw(name, mod=None):
    spec = importlib.util.spec_from_file_location(name, HERE / (name + ".pyw"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # 无头环境里模态框会永久阻塞：换成抛异常
    class NoDialog:
        def _boom(self, *a, **k):
            raise AssertionError("弹了对话框（无头测试里不允许）：%s" % (a[:2],))

        showinfo = showerror = showwarning = _boom
        askokcancel = askyesno = _boom
    mod.messagebox = NoDialog()
    return mod


from lasr_core import savefile, vdata  # noqa: E402  （这两个都不需要 unicorn）

game = vdata.find_game_dir()
scratch = Path(os.environ.get("TMPDIR",
                              r"C:\Users\niko6\AppData\Local\hermes\cache\scratch"))
scratch.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------- 车辆修改器
print("\n=== 车辆数据修改器（无 unicorn）===")
vedit = load_pyw("vehicle_editor")
check(True, "vehicle_editor.pyw 导入成功（模块级没拖进 unicorn）")
src_zip = game / "vehicles" / "Phoenix_RS_1997" / "coupe" / "classes.zip"
work_zip = scratch / "smoke_nou_coupe.zip"
shutil.copy2(src_zip, work_zip)
for stale in (Path(str(work_zip) + ".bak"),):
    if stale.exists():
        stale.unlink()          # 同 smoke_vehicle_editor：别复用上一轮的旧备份

root = tk.Tk()
app = vedit.App(root)
pump(root)
check(getattr(app, "codec_ok", None) is False, "自检判定 FLZD 不可用 → 默认原样 TUBA",
      "codec_ok=%s, 当前=%s" % (getattr(app, "codec_ok", None), app.var_mode.get()))

names = [app.lb_car.get(i) for i in range(app.lb_car.size())]
app.lb_car.selection_set(names.index("Phoenix_RS_1997"))
app.on_car()
pump(root)
app.editor.close()
app.editor = vdata.ZipPartEditor(game, work_zip, write_mode="raw")
app.parts = app.editor.part_entries()
app.var_filter.set("IEngine_stage_IV")
app.fill_parts()
pump(root)
app.lb_part.selection_set(0)
app.on_part()
pump(root)
check(app.stats is not None, "零件已解析（走明文快照）", app.stats.class_name)
check(len(app.curves) >= 2, "曲线已识别", ",".join(c.name for c in app.curves))
before = [v for _i, v in app.curves[1].values()]
app.var_factor.set("1.5")
app.scale_curve(whole_family=True)
pump(root, 12)
check(len(app.pending) >= 3, "改值进了 pending",
      "%d 个 class" % len(app.pending))
edits = {e: t.tobytes() for e, t in app.pending.items()}
app.editor.save(edits)
ent = sorted(edits)[0]
with zipfile.ZipFile(work_zip) as z:
    blob = z.read(ent)
check(not blob[:4] == b"FLZD", "写回的是明文 TUFA", "条目 %d 字节" % len(blob))
with zipfile.ZipFile(work_zip) as z:
    st2 = app.editor.load(ent, allow_snapshot=False)
check(st2.tufa.tobytes() == edits[ent], "从 zip 回读 == 写进去的字节码")
after = [v for _i, v in
         vdata.curves(st2.tufa)[1].values()]
check(after != before, "改后的值确实变了", "%s -> %s" % (before[:3], after[:3]))
app.editor.restore()
with zipfile.ZipFile(src_zip) as a, zipfile.ZipFile(work_zip) as b:
    check(all(a.read(n) == b.read(n) for n in a.namelist()),
          "恢复备份后与原始 zip 逐字节一致")
root.destroy()

# ---------------------------------------------------------------- 存档修改器
print("\n=== 存档修改器（无 unicorn）===")
sedit = load_pyw("save_editor")
check(True, "save_editor.pyw 导入成功")
src_sav = Path(r"C:\Games\LASR\save\career\001.sav")
work_sav = scratch / "smoke_nou_001.sav"
shutil.copy2(src_sav, work_sav)
root = tk.Tk()
app2 = sedit.App(root)
pump(root)
app2.var_path.set(str(work_sav))
app2.load()
pump(root)
check(app2.s is not None, "存档已解析", app2.lb_info.cget("text"))
check(len(app2.tv_cars.get_children()) >= 1, "车辆列表已填充")
idx0 = savefile.vehicle_index_of(app2.s["cars"][0]["vehicle"])
m = app2.case_map(idx0)
check(len(m) > 50, "零件目录走快照可用（VID %d）" % idx0, "%d 项" % len(m))
check("引擎" in app2.part_desc(idx0, [k for k, v in m.items()
                                     if v and "IEngine" in v][0]),
      "零件中文说明可用")
rows = app2.tv_cars.get_children()
app2.tv_cars.selection_set(rows[0])
app2.fill_parts()
pump(root)
app2.open_part_browser()
pump(root)
wins = [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)]
check(wins, "零件目录窗口能打开")
if wins:
    tvs = [c for c in wins[0].winfo_children() if c.winfo_class() == "Treeview"]
    check(tvs and len(tvs[0].get_children()) > 50, "目录窗口列出零件",
          "%d 行" % (len(tvs[0].get_children()) if tvs else 0))
    wins[0].destroy()
app2.s["cars"][0]["parts"].append([savefile.make_part_id(idx0, 0), 1])
app2.fill_parts()
pump(root)
check(len(app2.tv_parts.get_children()) >= 1, "加零件后表格刷新")
sedit.savefile.save(app2.s, work_sav, backup=True)
back = savefile.load(work_sav)
check(len(back["cars"][0]["parts"]) == len(app2.s["cars"][0]["parts"]),
      "存档写盘后回读一致")
root.destroy()

print("\n%s" % ("全部通过 nya~（两个工具都不需要 unicorn）" if not FAILS
                else "失败 %d 项: %s" % (len(FAILS), FAILS)))
raise SystemExit(1 if FAILS else 0)
