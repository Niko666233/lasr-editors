"""存档修改器的无头冒烟测试：真起 Tk，走完 载入→改→保存→回读 全流程。

只在 scratch 里的副本上操作，绝不动用户真实存档。
"""
import importlib.util
import shutil
import sys
import time
import tkinter as tk
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

spec = importlib.util.spec_from_file_location("sedit", HERE / "save_editor.pyw")
sedit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sedit)

from lasr_core import savefile  # noqa: E402

FAILS = []


def check(cond, label, extra=""):
    print("%s %s %s" % ("✓" if cond else "✗", label, extra))
    if not cond:
        FAILS.append(label)


def pump(root, n=6):
    for _ in range(n):
        root.update()
        time.sleep(0.04)


def main():
    src = Path(r"C:\Games\LASR\save\career\001.sav")
    scratch = Path(__import__("os").environ.get(
        "TMPDIR", r"C:\Users\niko6\AppData\Local\hermes\cache\scratch"))
    scratch.mkdir(parents=True, exist_ok=True)
    work = scratch / "smoke_career_001.sav"
    shutil.copy2(src, work)
    bak = Path(str(work) + ".bak")
    if bak.exists():
        bak.unlink()

    root = tk.Tk()
    app = sedit.App(root)
    pump(root)
    app.var_path.set(str(work))
    app.load()
    pump(root)
    check(app.s is not None, "存档已解析", app.lb_info.cget("text"))
    check(app.tv_cars.get_children(), "车辆列表已填充",
          "%d 行" % len(app.tv_cars.get_children()))

    # 改生涯字段
    app.career_vars["winSum"][0].set("42")
    app.career_vars["raceSum"][0].set("50")
    app.career_vars["nickName"][0].set("NekoTest")
    app.career_vars["prestige"][0].set("1234")
    app.career_vars["aiLevelMul"][0].set("0.5")
    app.set_trials(1)
    # 加一台车 + 两个零件（用**相对**断言：用户的真实存档会一直在变）
    n_cars0 = len(app.s["cars"])
    p0 = len(app.s["cars"][0]["parts"])
    app.var_add_car.set("0 = %s" % savefile.vehicle_name(0))
    app.add_car()
    pump(root)
    check(len(app.s["cars"]) == n_cars0 + 1, "加车生效",
          "%d -> %d 台" % (n_cars0, len(app.s["cars"])))
    app.tv_cars.selection_set(app.tv_cars.get_children()[0])
    pump(root)
    app.var_case.set("1")
    app.add_part(1)
    app.var_case.set("2048")
    app.add_part(0)
    pump(root)
    check(len(app.s["cars"][0]["parts"]) == p0 + 2, "加零件生效",
          "%d -> %d 个" % (p0, len(app.s["cars"][0]["parts"])))
    app.tv_parts.selection_set(app.tv_parts.get_children()[0])
    app.toggle_part()
    pump(root)
    check(app.s["cars"][0]["parts"][0][1] == 0, "切换装车状态",
          app.s["cars"][0]["parts"])

    # 零件目录（catalog）接线
    idx0 = savefile.vehicle_index_of(app.s["cars"][0]["vehicle"])
    m = app.case_map(idx0)
    check(len(m) > 50, "零件目录 case 映射已建",
          "VID %d -> %d 项" % (idx0, len(m)))
    eng = [c for c, cls in m.items() if cls and "IEngine" in cls]
    check(eng, "映射里有 IEngine", "case=%s" % eng[:3])
    check(app.part_short(idx0, eng[0]).startswith("IEngine"),
          "case→短名可用", app.part_short(idx0, eng[0]))
    check(app.tv_cars.item(app.tv_cars.get_children()[0], "values")[1]
          .startswith("%d " % idx0), "车标签用目录名",
          app.tv_cars.item(app.tv_cars.get_children()[0], "values")[1])
    check(len(app.cb_addpart.cget("values")) > 50, "加零件下拉框已填",
          "%d 项" % len(app.cb_addpart.cget("values")))
    check("引擎" in app.part_desc(idx0, eng[0]), "零件有人话说明",
          app.part_desc(idx0, eng[0]))
    # 零件目录窗口
    app.open_part_browser()
    pump(root)
    wins = [w for w in app.root.winfo_children() if isinstance(w, tk.Toplevel)]
    check(wins, "零件目录窗口已打开", "%d 个" % len(wins))
    if wins:
        tvs = [c for c in wins[0].winfo_children()
               if c.winfo_class() == "Treeview"]
        n_rows = len(tvs[0].get_children()) if tvs else 0
        check(n_rows > 50, "目录窗口列出零件", "%d 行" % n_rows)
        wins[0].destroy()
        pump(root)

    errs = app._collect()
    check(not errs, "collect 无错误", str(errs))
    app.path = work
    app.s and sedit.savefile.save(app.s, work, backup=True)
    check(bak.exists(), "备份已生成", str(bak))

    back = savefile.load(work)
    check(back["nickName"] == "NekoTest", "昵称已写入", back["nickName"])
    check(back["winSum"] == 42 and back["raceSum"] == 50, "胜负已写入",
          "%d/%d" % (back["winSum"], back["raceSum"]))
    check(abs(back["aiLevelMul"] - 0.5) < 1e-6, "AI 倍率已写入",
          back["aiLevelMul"])
    check(back["prestige"] == 1234, "声望已写入", back["prestige"])
    check(all(back["trials"]), "挑战赛全解锁")
    check(len(back["cars"]) == n_cars0 + 1, "车辆数保持", len(back["cars"]))
    # 未改字段应逐字节保持
    orig = savefile.load(src)
    check(back["lastSaveTime"] == orig["lastSaveTime"], "未改字段保持",
          back["lastSaveTime"])
    check(back["chronicles"] == orig["chronicles"], "比赛记录保持")

    # 记录页翻胜负
    app.fill_chronic()
    app.tv_chronic.selection_set("0")
    before_won = app.s["chronicles"][0]["won"]
    app.flip_chronic()
    check(app.s["chronicles"][0]["won"] != before_won, "记录翻胜负")

    root.destroy()
    print("\n%s" % ("全部通过 nya~" if not FAILS
                    else "失败 %d 项: %s" % (len(FAILS), FAILS)))
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
