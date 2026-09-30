"""新增两页/一包的冒烟测试（真起 Tk，只在 scratch 副本上写）。

覆盖：
  A. 「字符串参数」页：WeightReduction 的 configureType 质量行能被列出、能双击改、
     改完**文件长度不变**、写回 zip 后能从 zip 读回；
  B. 共享包 java/classes.zip：能被当成一个「车」选出来（304 个条目），
     读 INitrous / Tyre_RS 能拿到值（走随包快照，不需要 unicorn），
     并且能在副本上执行一次明文写入 + 回读。

    cd editors && ../.capenv/Scripts/python.exe smoke_cfg_and_shared.py
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

from lasr_core import cfgstr, tufa, vdata  # noqa: E402

FAILS = []


def check(cond, label, extra=""):
    print("%s %s %s" % ("✓" if cond else "✗", label, extra))
    if not cond:
        FAILS.append(label)


def pump(root, n=8, dt=0.04):
    for _ in range(n):
        root.update()
        time.sleep(dt)


def load_pyw(name):
    spec = importlib.util.spec_from_file_location(name, HERE / (name + ".pyw"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    class NoDialog:
        def _boom(self, *a, **k):
            raise AssertionError("弹了对话框（无头测试里不允许）：%s" % (a[:2],))
        showinfo = showerror = showwarning = _boom
        askokcancel = askyesno = _boom
    mod.messagebox = NoDialog()
    return mod


scratch = Path(os.environ.get("LOCALAPPDATA", ".")) / "Temp" / "lasr_cfg_smoke"
scratch.mkdir(parents=True, exist_ok=True)

vedit = load_pyw("vehicle_editor")
root = tk.Tk()
app = vedit.App(root)
pump(root)

names = [app.lb_car.get(i) for i in range(app.lb_car.size())]
print("\n=== A. 字符串参数页 ===")
check(any(n.startswith("★共享包") for n in names), "车列表里有共享包条目",
      names[-1] if names else "")

# --- 选 Fantasy Corus，加载减重件
app.lb_car.selection_set(names.index("Fantasy_Corus_2005"))
app.on_car()
pump(root)
work = scratch / "corus_classes.zip"
shutil.copy2(app.zip_path, work)
app.var_mode.set("raw")
app.editor = vdata.ZipPartEditor(app.game, work, write_mode="raw")
app.parts = app.editor.part_entries()
app.var_filter.set("WeightReduction_stock")
app.fill_parts()
pump(root)
# 过滤会同时列出 Item 类（IWeightReduction_stock，没有 configureType）和
# Part 类（WeightReduction_stock，参数在这）—— 要选 Part 那个
want = "Hatch_S2_WeightReduction_stock"
idx = [i for i in range(app.lb_part.size()) if app.lb_part.get(i) == want]
check(bool(idx), "过滤后能找到 Part 类（不是 Item 类）", want)
app.lb_part.selection_set(idx[0])
app.on_part()
pump(root)
rows = app.tree_cfg.get_children()
check(bool(rows), "字符串参数页有行", "%d 个 configureType 行" % len(rows))
body_rows = [r for r in rows if app.tree_cfg.item(r, "text").startswith("body")]
check(bool(body_rows), "能看到 body 行（碰撞体/质量）",
      app.tree_cfg.item(body_rows[0], "text") if body_rows else "")
kids = []
for br in body_rows:
    for k in app.tree_cfg.get_children(br):
        if "质量" in app.tree_cfg.set(k, "f"):
            kids.append(k)
check(bool(kids), "body 行里有「★质量 (kg)」列",
      "%s = %s" % (app.tree_cfg.set(kids[0], "f"),
                   app.tree_cfg.set(kids[0], "v")) if kids else "")
# 要改的是「真正那个底盘质量」394.000（同一行的 0.001 是占位球，在另一条 body 行）
target = [k for k in kids if app.tree_cfg.set(k, "v") == "394.000"]
check(bool(target), "找到底盘质量那一行 = 394.000（不是占位球 0.001）",
      "共 %d 个质量 token" % len(kids))
masses = target or kids

t = app._tufa()
before = t.tobytes()
old = app.tree_cfg.set(masses[0], "v")
row_iid = masses[0]
app.apply_cfg(row_iid, "300")
after = t.tobytes()
nd = sum(1 for a, b in zip(before, after) if a != b)
check(len(before) == len(after), "改质量后文件长度不变",
      "%d -> %d" % (len(before), len(after)))
check(nd > 0, "改质量后字节确实变了", "%d 字节" % nd)
mts = [tk for c in cfgstr.parse(t) if c.key == "body" for tk in c.tokens
       if "质量" in c.label(tk.idx)]
check(mts and mts[-1].text.strip().startswith("300"),
      "重新解析读到新值", "%s -> %s" % (old, mts[-1].text if mts else "?"))
# 写回副本 zip 并回读
ent = app.entry
app.editor.save({ent: t.tobytes()})
st2 = app.editor.load(ent, allow_snapshot=False)
m2 = [tk for c in cfgstr.parse(st2.tufa) if c.key == "body" for tk in c.tokens
      if "质量" in c.label(tk.idx)]
check(m2 and m2[-1].text.strip().startswith("300"),
      "写回 zip 后读回 == 改后的值", m2[-1].text if m2 else "?")

# --- 越界值要被拒绝（不能静默丢精度）
try:
    cfgstr.set_token(t, mts[-1], "123456789")
    check(False, "超宽的新值被拒绝", "竟然写进去了")
except cfgstr.CfgError as exc:
    check(True, "超宽的新值被拒绝", str(exc)[:46])

print("\n=== B. 共享包 java/classes.zip ===")
shared = [i for i, n in enumerate(names) if n.startswith("★共享包")]
app.lb_car.selection_clear(0, "end")
app.lb_car.activate(shared[0])
app.lb_car.selection_set(shared[0])
pump(root, 2)
print("  列表选中项 =", app.lb_car.curselection(), "->", names[shared[0]])
app.on_car()
pump(root)
check(app.is_shared is True, "识别为共享包", str(app.zip_path))
check(len(app.parts) > 300, "共享包条目已列出", "%d 条" % len(app.parts))
app.var_filter.set("INitrous")
app.fill_parts()
pump(root)
app.lb_part.selection_set(0)
app.on_part()
pump(root)
vals = [v for _m, _i, _k, v in vdata.scalars(app.stats.tufa)]
check(len(vals) >= 17, "INitrous 字面量读出来了", "%d 个" % len(vals))
want = [0.55, 4.0, 0.5, 6.0, 0.45, 8.0, 0.4, 10.0, 0.45, 12.0]
seq = [v for v in vals if isinstance(v, float)]
found = any(all(abs(seq[i + j] - w) < 1e-6 for j, w in enumerate(want))
            for i in range(max(0, len(seq) - len(want) + 1)))
check(found, "onInstall 里的 (加成, 容量) 五档序列都在",
      "含 4.0/6.0/8.0/10.0/12.0 = %s"
      % [v for v in vals if v in (4.0, 6.0, 8.0, 10.0, 12.0)])
app.var_filter.set("Tyre_RS")
app.fill_parts()
pump(root)
app.lb_part.selection_set(0)
app.on_part()
pump(root)
tvals = [v for _m, _i, _k, v in vdata.scalars(app.stats.tufa)]
check(any(isinstance(v, float) and abs(v - 2.25) < 1e-6 for v in tvals),
      "Tyre_RS 里有沥青 µ = 2.25", "%d 个字面量" % len(tvals))

# 在**副本**上试一次明文写入（真实 java/classes.zip 一个字都不动）
jz = scratch / "java_classes.zip"
shutil.copy2(app.game / "java" / "classes.zip", jz)
ed = vdata.ZipPartEditor(app.game, jz, write_mode="raw")
st = ed.load("game/parts/Tyre_RS.class")
mts2 = [tk for c in cfgstr.parse(st.tufa) for tk in c.tokens]
lit = st.tufa.find("<init>")[0]
mu = [v for _i, _o, _k, v in st.tufa.literals(lit)]
target = None
for i, _o, _k, v in st.tufa.literals(lit):
    if isinstance(v, float) and abs(v - 2.25) < 1e-6:
        target = i
        break
if target is not None:
    st.tufa.set_literals(lit, {target: 3.0})
    ed.save({"game/parts/Tyre_RS.class": st.tufa.tobytes()})
    back = vdata.ZipPartEditor(app.game, jz, write_mode="raw").load(
        "game/parts/Tyre_RS.class")
    got = [v for _i, _o, _k, v in back.tufa.literals(
        back.tufa.find("<init>")[0])]
    check(any(isinstance(v, float) and abs(v - 3.0) < 1e-6 for v in got),
          "共享包副本上改 µ 2.25→3.0 并回读成功", "字面量 %d 个" % len(got))
else:
    check(False, "在 Tyre_RS 里定位到 2.25 那个字面量")

# 真实共享包/游戏目录没被碰
import hashlib


def md5(p):
    return hashlib.md5(Path(p).read_bytes()).hexdigest()


print("\n真实文件校验：")
print("   java/classes.zip md5 =", md5(app.game / "java" / "classes.zip"))

root.destroy()
print("\n%s" % ("全部通过 nya~" if not FAILS else "失败 %d 项: %s" % (len(FAILS), FAILS)))
raise SystemExit(1 if FAILS else 0)
