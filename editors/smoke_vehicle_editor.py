"""无头冒烟测试：真起 Tk，灌数据，跑完「选车→选零件→改曲线→保存」全流程。

不碰用户真实游戏目录：把一台车的 classes.zip 复制到 scratch 再让编辑器对它操作。
"""
import importlib.util
import shutil
import sys
import time
import tkinter as tk
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

spec = importlib.util.spec_from_file_location("vedit", HERE / "vehicle_editor.pyw")
vedit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vedit)

from lasr_core import flzd, tufa, vdata  # noqa: E402

FAILS = []


def check(cond, label, extra=""):
    print("%s %s %s" % ("✓" if cond else "✗", label, extra))
    if not cond:
        FAILS.append(label)


def pump(root, n=8, dt=0.05):
    for _ in range(n):
        root.update()
        time.sleep(dt)


def main():
    game = vdata.find_game_dir()
    check(game is not None, "找到游戏目录", str(game))
    src_zip = game / "vehicles" / "Phoenix_RS_1997" / "coupe" / "classes.zip"
    scratch = Path(__import__("os").environ.get("TMPDIR",
                                                 r"C:\Users\niko6\AppData\Local\hermes\cache\scratch"))
    scratch.mkdir(parents=True, exist_ok=True)
    work_zip = scratch / "smoke_coupe_classes.zip"
    shutil.copy2(src_zip, work_zip)
    # .bak 只在第一次写时创建、之后不覆盖（工具的设计）：跨轮次复用旧备份会
    # 让「恢复备份后与原始一致」误报，所以每次跑之前先清掉。
    for stale in (Path(str(work_zip) + ".bak"),):
        if stale.exists():
            stale.unlink()

    root = tk.Tk()
    app = vedit.App(root)
    pump(root)
    check(len(app.cars) >= 8, "车辆列表已填充", "%d 台" % len(app.cars))

    # 选中 Phoenix_RS_1997
    names = [app.lb_car.get(i) for i in range(app.lb_car.size())]
    idx = names.index("Phoenix_RS_1997")
    app.lb_car.selection_set(idx)
    app.on_car()
    pump(root)
    check(len(app.parts) > 100, "零件列表已填充", "%d 个" % len(app.parts))

    # 把编辑器指到 scratch 副本（真实游戏目录保持不动）
    app.editor.close()
    app.editor = vdata.ZipPartEditor(game, work_zip)
    app.parts = app.editor.part_entries()
    app.fill_parts()
    pump(root)

    app.var_filter.set("IEngine_stock")
    pump(root)
    check(app.lb_part.size() >= 1, "过滤 IEngine_stock", "%d 行" % app.lb_part.size())
    app.lb_part.selection_set(0)
    app.on_part()
    pump(root)
    st = app.stats
    check(st is not None and st.tufa is not None, "零件已解析", st.class_name if st else "")
    check(len(app.curves) >= 2, "曲线已识别",
          ",".join(c.name for c in app.curves))

    before = dict(app.curves[1].values()) if len(app.curves) > 1 else {}
    # 改一个曲线单元
    tv = app.tree_b
    iid = tv.get_children()[3]
    tv.selection_set(iid)
    app.var_cell.set("777")
    app.set_selected()
    pump(root)
    after = dict(vdata.curves(app._tufa())[1].values())
    changed = [k for k in after if after[k] != before.get(k)]
    check(changed, "单点改值生效", "%s -> %s" % (before.get(changed[0]) if changed else None,
                                                after.get(changed[0]) if changed else None))

    # 行内编辑（双击 -> 输入框 -> 回车）走的是 apply_value/apply_curve
    t_before = app._tufa().tobytes()
    row = app.tree_v.get_children()[0]
    mid, li = vedit._split_iid(row)
    cur = app.tree_v.set(row, "v")
    app.apply_value(app.tree_v, row, "1234")
    t_after = app._tufa()
    m0 = next(x for x in t_after.methods if x.index == mid)
    new0 = dict((i, v) for i, _o, _k, v in t_after.literals(m0))[li]
    check(t_after.tobytes() != t_before and new0 == 1234,
          "全部数值页行内改值生效", "%s -> %s (%s[%d])" % (cur, new0, m0.name, li))
    check(app.tree_v.set(row, "label") is not None, "「作用」列存在",
          repr(app.tree_v.set(row, "label")) or "(表未生成时为空)")
    labs = [app.tree_v.set(r, "label") for r in app.tree_v.get_children()[:40]]
    filled = [x for x in labs if x]
    check(len(filled) >= 20, "「作用」列有实际内容", "%d/40 非空，例: %s"
          % (len(filled), filled[:3]))
    # 按钮路径（用户报「改不了」的那条）也要能改
    app.tree_v.selection_set(row)
    app.var_val.set("2345")
    app.set_val()
    new1 = dict((i, v) for i, _o, _k, v in
                t_after.literals(m0))[li]
    check(new1 == 2345, "「设为该值」按钮生效", "%s -> %s" % (new0, new1))

    # 系数批量：同族全部阶段
    app.var_factor.set("1.10")
    app.scale_curve(whole_family=True)
    pump(root, 20)
    check(len(app.pending) >= 3, "同族批量进了 pending",
          "%d 个 class: %s" % (len(app.pending), sorted(app.pending)[:3]))

    # 保存到 scratch 副本 —— 两种写入格式都测一遍
    for mode in ("flzd", "raw"):
        app.editor.write_mode = mode
        n_pending = len(app.pending)
        edits = {e: t.tobytes() for e, t in app.pending.items()}
        bak = app.editor.save(edits)
        check(bak is not None and Path(bak).exists(), "%s: 备份已生成" % mode,
              str(bak))
        codec = flzd.FlzdCodec(game / "LASR.exe")
        ent = sorted(edits)[0]
        with zipfile.ZipFile(work_zip) as z:
            blob = z.read(ent)
        stored_is_flzd = flzd.is_flzd(blob)
        t2 = tufa.Tufa(codec.unpack(blob) if stored_is_flzd else blob)
        check(t2.tobytes() == edits[ent], "%s: 写回的 zip 里就是改过的字节码"
              % mode, "%s, 条目 %d 字节, 是 FLZD=%s"
              % (ent, len(blob), stored_is_flzd))
        check(stored_is_flzd == (mode == "flzd"),
              "%s: 写入格式符合预期" % mode, "FLZD=%s" % stored_is_flzd)

    app.editor.restore()
    pump(root)
    with zipfile.ZipFile(src_zip) as a, zipfile.ZipFile(work_zip) as b:
        same2 = all(a.read(n) == b.read(n) for n in a.namelist())
    check(same2, "恢复备份后与原始 zip 逐字节一致")

    root.destroy()
    print("\n%s" % ("全部通过 nya~" if not FAILS else "失败 %d 项: %s"
                    % (len(FAILS), FAILS)))
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
