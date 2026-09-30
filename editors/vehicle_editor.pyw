"""LASR 车辆数据修改器 (GUI).

双击运行（.pyw 或打包后的 exe）。功能：
  * 选车辆 / 选零件（含发动机各阶段）
  * 看并改「发动机扭矩曲线 eRPMs/eMuls」等 float[] 曲线
  * 看并改任意 class 里的 INT/FLOAT 字面量（重量、声望、限转…）
  * 系数批量改：本件 / 同族全部阶段
  * 保存回游戏的 classes.zip（自动备份 .bak，可一键恢复）

所有改动只改 TUFA 里既有的 4 字节字面量，文件长度不变；写回 zip 前用游戏
自己的 FLZD 压缩器重新打包（editors/lasr_core/flzd.py）。
"""
import subprocess
import sys
import tkinter as tk
import traceback
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lasr_core import cfgstr, labels, tufa, vdata  # noqa: E402

FONT = ("Microsoft YaHei UI", 9)
TITLE = "LASR 车辆数据修改器  (=^･ω･^=)"
# 「字符串参数」页默认只显示这些会进物理/性能的 key
PHYS_KEYS = ("body", "wing", "damage", "flexible", "maxsteer", "spring",
             "steerhelp", "steerspeed", "slot")
STAGES = ("stock", "stage_I", "stage_II", "stage_III", "stage_IV", "stage_V",
          "style_I", "style_II", "style_III", "style_IV", "WB", "custom",
          "track")


class App:
    def __init__(self, root):
        self.root = root
        root.title(TITLE)
        root.geometry("1080x700")
        root.minsize(900, 560)
        self.game = None
        self.editor = None          # ZipPartEditor for the current zip
        self.cars = []              # [(car_dir_name, [(body, zip_path)])]
        self.parts = []             # current zip entries
        self.stats = None           # PartStats of the selected entry
        self.pending = {}           # entry -> Tufa (modified)
        self.changed_marks = {}     # entry -> {(method_index, lit_index)}
        self.curves = []
        self.entry = None
        self.zip_path = None
        self.editor = None
        self.is_shared = False      # 当前选的是共享包 java/classes.zip
        self._cfg_marks = {}        # entry -> {字符串 token 的文件偏移}
        self._shown = []
        self.class_short = None
        self.car = None
        self.body = None
        self._build()
        self.probe_codec()
        self.autodetect()

    def probe_codec(self):
        """探测 FLZD 压缩器能不能用（打包 exe 里 unicorn 的 JIT 会 0xC0000409）。

        所以用**子进程**试探：崩了也只崩子进程，主界面照常起来，并把 FLZD 选项禁用。
        """
        ok = False
        try:
            if getattr(sys, "frozen", False):
                r = subprocess.run([sys.executable, "--emutest"],
                                   capture_output=True, timeout=120)
                ok = (r.returncode == 0)
            else:
                g = vdata.find_game_dir()
                ok = bool(g) and vdata.codec_available(g / "LASR.exe")
        except Exception:  # noqa: BLE001
            ok = False
        self.codec_ok = ok
        if ok:
            self.var_mode.set("flzd")
            self.rb_flzd.config(text="FLZD（与原版一致）")
            self.rb_raw.config(text="原样 TUFA（已实测可用）")
        else:
            self.var_mode.set("raw")
            self.rb_flzd.config(state="disabled",
                                text="FLZD（本机不可用：unicorn 在 frozen exe 里崩）")
            self.rb_raw.config(text="原样 TUFA（已实测可用，推荐）")

    # ------------------------------------------------------------- UI 构建
    def _build(self):
        self.root.columnconfigure(0, weight=0, minsize=250)
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(2, weight=1)

        top = ttk.Frame(self.root, padding=(8, 6))
        top.grid(row=0, column=0, columnspan=2, sticky="ew")
        top.columnconfigure(1, weight=1)
        ttk.Label(top, text="游戏目录:", font=FONT).grid(row=0, column=0)
        self.var_game = tk.StringVar()
        ttk.Entry(top, textvariable=self.var_game, font=FONT).grid(
            row=0, column=1, sticky="ew", padx=4)
        ttk.Button(top, text="检测", width=6, command=self.autodetect).grid(
            row=0, column=2)
        ttk.Button(top, text="浏览…", width=7, command=self.browse).grid(
            row=0, column=3, padx=4)

        ttk.Separator(self.root).grid(row=1, column=0, columnspan=2,
                                      sticky="ew")

        left = ttk.Frame(self.root, padding=(8, 4))
        left.grid(row=2, column=0, sticky="nsew")
        left.columnconfigure(0, weight=1)
        left.rowconfigure(2, weight=1)
        left.rowconfigure(5, weight=2)
        ttk.Label(left, text="车辆", font=FONT).grid(row=0, column=0, sticky="w")
        self.lb_car = tk.Listbox(left, font=FONT, exportselection=False,
                                 height=8)
        self.lb_car.grid(row=1, column=0, sticky="nsew")
        self.lb_car.bind("<<ListboxSelect>>", self.on_car)
        ttk.Label(left, text="零件（双击表格编辑）", font=FONT).grid(
            row=3, column=0, sticky="w", pady=(8, 0))
        f = ttk.Frame(left)
        f.grid(row=4, column=0, sticky="ew")
        f.columnconfigure(1, weight=1)
        ttk.Label(f, text="过滤:", font=FONT).grid(row=0, column=0)
        self.var_filter = tk.StringVar()
        self.var_filter.trace_add("write", lambda *a: self.fill_parts())
        ttk.Entry(f, textvariable=self.var_filter, font=FONT).grid(
            row=0, column=1, sticky="ew")
        self.lb_part = tk.Listbox(left, font=FONT, exportselection=False)
        self.lb_part.grid(row=5, column=0, sticky="nsew")
        self.lb_part.bind("<<ListboxSelect>>", self.on_part)

        right = ttk.Frame(self.root, padding=(4, 4))
        right.grid(row=2, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)
        self.lb_head = ttk.Label(right, text="选一个零件…", font=("Microsoft YaHei UI", 10, "bold"))
        self.lb_head.grid(row=0, column=0, sticky="w")

        self.nb = ttk.Notebook(right)
        self.nb.grid(row=1, column=0, sticky="nsew", pady=4)
        self.tab_curve = ttk.Frame(self.nb)
        self.tab_vals = ttk.Frame(self.nb)
        self.tab_cfg = ttk.Frame(self.nb)
        self.nb.add(self.tab_curve, text="曲线（扭矩/转速）")
        self.nb.add(self.tab_vals, text="全部数值")
        self.nb.add(self.tab_cfg, text="字符串参数（质量/气动/挂点）")
        self._build_curve_tab()
        self._build_vals_tab()
        self._build_cfg_tab()

        bottom = ttk.Frame(self.root, padding=(8, 6))
        bottom.grid(row=3, column=0, columnspan=2, sticky="ew")
        bottom.columnconfigure(5, weight=1)
        ttk.Button(bottom, text="保存到游戏", command=self.save).grid(
            row=0, column=0)
        ttk.Button(bottom, text="恢复备份", command=self.restore).grid(
            row=0, column=1, padx=6)
        ttk.Button(bottom, text="撤销本件改动", command=self.revert_part).grid(
            row=0, column=2)
        ttk.Label(bottom, text="写入格式:", font=FONT).grid(row=0, column=3,
                                                           padx=(10, 2))
        self.var_mode = tk.StringVar(value="raw")
        self.rb_flzd = ttk.Radiobutton(bottom, text="FLZD（与原版一致）",
                                       value="flzd", variable=self.var_mode)
        self.rb_flzd.grid(row=0, column=4)
        self.rb_raw = ttk.Radiobutton(bottom, text="原样 TUFA（推荐）",
                                      value="raw", variable=self.var_mode)
        self.rb_raw.grid(row=0, column=5, sticky="w")
        self.var_status = tk.StringVar(value="就绪")
        ttk.Label(bottom, textvariable=self.var_status, font=FONT).grid(
            row=0, column=6, sticky="w", padx=10)

    def _build_curve_tab(self):
        self.tab_curve.columnconfigure(0, weight=1)
        self.tab_curve.rowconfigure(1, weight=1)
        bar = ttk.Frame(self.tab_curve, padding=4)
        bar.grid(row=0, column=0, sticky="ew")
        ttk.Label(bar, text="统一乘系数:", font=FONT).grid(row=0, column=0)
        self.var_factor = tk.StringVar(value="1.25")
        ttk.Entry(bar, textvariable=self.var_factor, width=8, font=FONT).grid(
            row=0, column=1, padx=4)
        ttk.Button(bar, text="乘（仅本件）", command=lambda: self.scale_curve(False)).grid(
            row=0, column=2)
        ttk.Button(bar, text="乘（同族全部阶段）",
                   command=lambda: self.scale_curve(True)).grid(
            row=0, column=3, padx=4)
        ttk.Button(bar, text="曲线翻倍", command=lambda: self.set_factor("2")).grid(
            row=0, column=4)
        ttk.Button(bar, text="还原原值", command=self.reload_part).grid(
            row=0, column=5, padx=4)

        body = ttk.Frame(self.tab_curve)
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(1, weight=1)
        ttk.Label(body, text="常数/转速断点 (eRPMs 等)", font=FONT).grid(
            row=0, column=0, sticky="w")
        ttk.Label(body, text="倍率 (eMuls 等)", font=FONT).grid(
            row=0, column=1, sticky="w")
        self.tree_a = ttk.Treeview(body, columns=("i", "v"), show="headings",
                                   height=14)
        self.tree_b = ttk.Treeview(body, columns=("i", "v"), show="headings",
                                   height=14)
        for tv, hdr in ((self.tree_a, "序号"), (self.tree_b, "序号")):
            tv.heading("i", text=hdr)
            tv.heading("v", text="值")
            tv.column("i", width=60, anchor="center", stretch=False)
            tv.column("v", width=120, anchor="e", stretch=True)
        self.tree_a.grid(row=1, column=0, sticky="nsew", padx=(0, 4))
        self.tree_b.grid(row=1, column=1, sticky="nsew")
        for tv in (self.tree_a, self.tree_b):
            tv.bind("<Double-1>", lambda e, t=tv: self.begin_inline(t, "v"))
            tv.bind("<Return>", lambda e, t=tv: self.begin_inline(t, "v"))
        self.curve_hint = ttk.Label(body, text="", font=FONT)
        self.curve_hint.grid(row=2, column=0, columnspan=2, sticky="w",
                             pady=(4, 0))

        edit = ttk.LabelFrame(self.tab_curve, text="改选中行的值", padding=6)
        edit.grid(row=2, column=0, sticky="ew", pady=6)
        ttk.Label(edit, text="新值:", font=FONT).grid(row=0, column=0)
        self.var_cell = tk.StringVar()
        ttk.Entry(edit, textvariable=self.var_cell, width=16, font=FONT).grid(
            row=0, column=1, padx=4)
        ttk.Button(edit, text="设为该值", command=self.set_selected).grid(
            row=0, column=2)
        ttk.Label(edit, text="（先在左边/右边表格里点一行）", font=FONT).grid(
            row=0, column=3, padx=8)
        ttk.Button(edit, text="选中行×系数",
                   command=self.scale_selected).grid(row=0, column=4)

    def _build_vals_tab(self):
        self.tab_vals.columnconfigure(0, weight=1)
        self.tab_vals.rowconfigure(1, weight=1)
        ttk.Label(self.tab_vals,
                  text="class 里全部 INT/FLOAT 字面量。**双击任意一行的「值」单元格直接改**，"
                       "回车生效（Esc 取消）；也可以选中后用下面的输入框。"
                       "「作用」列来自抬升伪码（如 engine_volume / turboTable[4]）。",
                  font=FONT, wraplength=760, justify="left").grid(
            row=0, column=0, sticky="w", padx=4, pady=4)
        cols = ("m", "i", "k", "v", "label", "mark")
        self.tree_v = ttk.Treeview(self.tab_vals, columns=cols,
                                   show="headings")
        for c, t, w, st in (("m", "方法", 170, False), ("i", "序号", 45, False),
                            ("k", "类型", 55, False), ("v", "值", 100, False),
                            ("label", "作用", 200, True),
                            ("mark", "已改", 45, False)):
            self.tree_v.heading(c, text=t)
            self.tree_v.column(c, width=w, stretch=st,
                               anchor="e" if c == "v" else "w")
        self.tree_v.grid(row=1, column=0, sticky="nsew", padx=4)
        self.tree_v.bind("<<TreeviewSelect>>", self.on_val_select)
        self.tree_v.bind("<Double-1>", lambda e: self.begin_inline(self.tree_v,
                                                                   "v"))
        self.tree_v.bind("<Return>", lambda e: self.begin_inline(self.tree_v,
                                                                 "v"))

        edit = ttk.LabelFrame(self.tab_vals, text="改选中行的值", padding=6)
        edit.grid(row=2, column=0, sticky="ew", padx=4, pady=6)
        ttk.Label(edit, text="新值:", font=FONT).grid(row=0, column=0)
        self.var_val = tk.StringVar()
        self.entry_val = ttk.Entry(edit, textvariable=self.var_val, width=16,
                                   font=FONT)
        self.entry_val.grid(row=0, column=1, padx=4)
        ttk.Button(edit, text="设为该值", command=self.set_val).grid(
            row=0, column=2)
        ttk.Button(edit, text="选中行×系数",
                   command=self.scale_val).grid(row=0, column=3, padx=8)
        ttk.Button(edit, text="还原本件",
                   command=self.reload_part).grid(row=0, column=4)

    def set_factor(self, v):
        self.var_factor.set(v)

    def _build_cfg_tab(self):
        """字符串参数页：configureType 里的数值（质量/气动/挂点/损伤…）。"""
        self.tab_cfg.columnconfigure(0, weight=1)
        self.tab_cfg.rowconfigure(2, weight=1)
        head = ttk.Frame(self.tab_cfg, padding=4)
        head.grid(row=0, column=0, sticky="ew")
        head.columnconfigure(0, weight=1)
        self.lb_cfg_hint = ttk.Label(head, text="", font=FONT, wraplength=740,
                                     justify="left")
        self.lb_cfg_hint.grid(row=0, column=0, sticky="w")
        bar = ttk.Frame(self.tab_cfg, padding=(4, 0))
        bar.grid(row=1, column=0, sticky="ew")
        self.var_cfg_phys = tk.IntVar(value=1)
        ttk.Checkbutton(bar, text="只看物理相关（质量/气动/悬挂/损伤）",
                        variable=self.var_cfg_phys,
                        command=self.refresh_tables).grid(row=0, column=0)
        ttk.Button(bar, text="还原原值", command=self.reload_part).grid(
            row=0, column=1, padx=6)
        ttk.Label(bar, text="（双击「值」直接改；只能填得下同样字符宽度的值）",
                  font=FONT).grid(row=0, column=2, padx=8)
        cols = ("k", "f", "v", "note", "mark")
        self.tree_cfg = ttk.Treeview(self.tab_cfg, columns=cols,
                                     show="tree headings")
        self.tree_cfg.heading("#0", text="configureType 行")
        for c, t, w, st in (("k", "键", 70, False), ("f", "参数", 110, False),
                            ("v", "值", 90, False), ("note", "作用", 330, True),
                            ("mark", "已改", 45, False)):
            self.tree_cfg.heading(c, text=t)
            self.tree_cfg.column(c, width=w, stretch=st,
                                 anchor="e" if c == "v" else "w")
        self.tree_cfg.column("#0", width=150, stretch=False)
        self.tree_cfg.grid(row=2, column=0, sticky="nsew", padx=4, pady=4)
        self.tree_cfg.bind("<Double-1>",
                           lambda e: self.begin_inline(self.tree_cfg, "v"))
        self.tree_cfg.bind("<Return>",
                           lambda e: self.begin_inline(self.tree_cfg, "v"))

    # ------------------------------------------------------------ 目录/选择
    def autodetect(self):
        g = vdata.find_game_dir(self.var_game.get() or None)
        if g:
            self.var_game.set(str(g))
            self.load_game()
        else:
            self.status("没找到游戏目录，请手动选")

    def browse(self):
        d = filedialog.askdirectory(title="选择 LASR 游戏目录（含 LASR.exe）")
        if d:
            self.var_game.set(d)
            self.load_game()

    def load_game(self):
        g = vdata.find_game_dir(self.var_game.get())
        if not g:
            messagebox.showerror("错误", "该目录里没有 LASR.exe / vehicles\\")
            return
        self.game = g
        self.cars = []
        for car in sorted((g / "vehicles").iterdir()):
            if not car.is_dir():
                continue
            bodies = []
            for body in sorted(car.iterdir()):
                zp = body / "classes.zip"
                if zp.is_file():
                    bodies.append((body.name, zp))
            if bodies:
                self.cars.append((car.name, bodies))
        jz = g / "java" / "classes.zip"
        if jz.is_file():
            self.cars.append(("★共享包 java（氮气容量/轮胎抓地力/引擎默认）",
                              [("java", jz)]))
        self.lb_car.delete(0, "end")
        for name, _b in self.cars:
            self.lb_car.insert("end", name)
        self.status("找到 %d 台车%s" % (
            len(self.cars) - (1 if jz.is_file() else 0),
            "＋共享包" if jz.is_file() else ""))

    def on_car(self, _ev=None):
        sel = self.lb_car.curselection()
        if not sel:
            return
        name, bodies = self.cars[sel[0]]
        self.is_shared = name.startswith("★共享包")
        if len(bodies) > 1:
            # 极少见：一台车多个车身 -> 取第一个，剩下的写在状态栏
            self.status("%s: 多个车身 %s，用 %s"
                        % (name, [b for b, _ in bodies], bodies[0][0]))
        if self.is_shared:
            # 共享包是核心类：能不用明文就别用（明文写 java 包尚未实机验证）
            if self.codec_ok:
                self.var_mode.set("flzd")
            self.status("共享包：10 台车通用。氮气容量在 INitrous，抓地力在 Tyre_*，"
                        "引擎默认在 IEngine。写入前请务必确认已备份 java 目录！")
        self.zip_path = bodies[0][1]
        self.editor = vdata.ZipPartEditor(self.game, self.zip_path,
                                          write_mode=self.var_mode.get())
        self.parts = self.editor.part_entries()
        self.pending.clear()
        self.changed_marks.clear()
        self._cfg_marks.clear()
        self.stats = None
        self.fill_parts()

    def fill_parts(self):
        flt = self.var_filter.get().lower()
        self.lb_part.delete(0, "end")
        shown = []
        for e in self.parts:
            short = e.split("/")[-1][:-6]
            if flt and flt not in short.lower():
                continue
            shown.append((short, e))
        shown.sort()
        self._shown = shown
        for short, _e in shown:
            self.lb_part.insert("end", short)
        self.status("%d / %d 个零件" % (len(shown), len(self.parts)))

    def on_part(self, _ev=None):
        sel = self.lb_part.curselection()
        if not sel or not hasattr(self, "_shown"):
            return
        entry = self._shown[sel[0]][1]
        self.load_part(entry)

    def load_part(self, entry, quiet=False):
        try:
            self.status("正在解压/解析 %s …" % entry.split("/")[-1])
            self.root.update_idletasks()
            st = self.editor.load(entry)
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            messagebox.showerror("解析失败", "%s\n%s" % (exc, entry))
            return
        self.entry = entry
        self.stats = st
        if entry in self.pending:
            self.stats.tufa = self.pending[entry]
        self.changed_marks.setdefault(entry, set())
        name = st.display_name() or st.class_name.split(".")[-1]
        self.lb_head.config(text="%s   [%s]" % (name, st.class_name))
        # 供「作用」列查表：vehicles.<Car>.<body>.classes.<Class>
        parts = st.class_name.split(".")
        self.class_short = parts[-1]
        self.car = parts[1] if len(parts) > 3 else None
        self.body = parts[2] if len(parts) > 3 else None
        self.refresh_tables()
        if not quiet:
            self.status("%s：%d 个方法" % (entry.split("/")[-1],
                                          len(st.tufa.methods)))

    # ------------------------------------------------------------ 表格刷新
    def refresh_tables(self):
        for tv in (self.tree_a, self.tree_b, self.tree_v, self.tree_cfg):
            tv.delete(*tv.get_children())
        if not self.stats:
            return
        t = self.stats.tufa
        self.curves = vdata.curves(t)
        for c in self.curves:
            tv = self.tree_a if c.name != "eMuls" else self.tree_b
            if c.name not in ("eRPMs", "eMuls"):
                tv = self.tree_a if "RPM" in c.name.upper() else self.tree_b
            for i, v in c.values():
                tv.insert("", "end", iid="%s|%d" % (c.method.index, i),
                          values=(i, fmt(v)))
        self.curve_hint.config(
            text="曲线: " + ", ".join("%s(%d点)" % (c.name, c.count)
                                      for c in self.curves)
            if self.curves else "本 class 没有可识别的 float[] 曲线")
        self.changed = self.changed_marks.get(self.entry, set())
        for m, i, k, v in vdata.scalars(t):
            iid = "m%d|%d" % (m.index, i)
            self.tree_v.insert(
                "", "end", iid=iid,
                values=(m.name, i, k, fmt(v),
                        labels.label_for(self.class_short, m.name, i,
                                         self.car, self.body)
                        or labels.shared_label(self.class_short, m.name, i)
                        or "",
                        "●" if (m.index, i) in self.changed else ""))
        self.fill_cfg()

    def fill_cfg(self):
        """填「字符串参数」页：configureType 里的数值（质量/气动/挂点/损伤…）。"""
        tv = self.tree_cfg
        hint = cfgstr.hint_for(self.class_short or "")
        self.lb_cfg_hint.config(
            text=hint or
            "configureType 字符串里的数值。★=会进物理的量（质量 kg / 气动系数 / "
            "悬挂 / 损伤）。它们不在「全部数值」页，因为它们是字符串不是字面量。")
        if not self.stats:
            return
        t = self._tufa()
        phys = bool(self.var_cfg_phys.get())
        marks = self._cfg_marks.get(self.entry, set())
        n_rows = 0
        for ci, c in enumerate(cfgstr.parse(t)):
            if phys and c.key not in PHYS_KEYS:
                continue
            note = cfgstr.NOTE.get(c.key, "")
            head = c.key + ("  ; " + c.comment if c.comment else "")
            parent = tv.insert("", "end", iid="c%d" % ci, text=head,
                               values=("", "", "", note, ""),
                               open=(len(c.tokens) <= 12))
            for tk in c.tokens:
                tv.insert(parent, "end", iid="c%d|%d" % (ci, tk.idx),
                          values=(c.key, c.label(tk.idx), tk.text,
                                  note if tk.idx == 0 else "",
                                  "●" if tk.off in marks else ""))
            n_rows += 1
        if not n_rows:
            self.lb_cfg_hint.config(
                text="本 class 没有 configureType 数据。提示：`I` 开头的类是"
                     "**背包条目**，真正的参数在同名的 Part 类里 —— 例如 "
                     "`IWeightReduction_stage_I` 的减重质量在 "
                     "`WeightReduction_stage_I`；`IRims_*` / `ITyres_*` / "
                     "`IF_Bumper_*` 同理。")

    def on_val_select(self, _ev=None):
        sel = self.tree_v.selection()
        if not sel:
            return
        vals = self.tree_v.item(sel[0], "values")
        self.var_val.set(vals[3])
        self.var_cell.set(vals[3])

    # ---------------------------------------------------- 双击就地改值（行内编辑）
    def begin_inline(self, tree, col):
        """双击/回车：在该单元格上叠一个输入框，回车提交、Esc 取消。"""
        sel = tree.selection()
        if not sel:
            return
        iid = sel[0]
        try:
            bbox = tree.bbox(iid, col)
        except tk.TclError:
            bbox = None
        if not bbox:
            return                      # 行不在可视区（滚一下再点）
        x, y, w, h = bbox
        cur = tree.set(iid, col)
        ent = ttk.Entry(tree, font=FONT, justify="right")
        ent.insert(0, cur)
        ent.place(x=x, y=y, width=max(w, 90), height=h)
        ent.focus_set()
        ent.select_range(0, "end")

        def done(save):
            txt = ent.get()
            ent.destroy()
            tree.focus(iid)
            if not save:
                return
            try:
                if tree is self.tree_v:
                    self.apply_value(tree, iid, txt)
                elif tree is self.tree_cfg:
                    self.apply_cfg(iid, txt)
                else:
                    self.apply_curve(tree, iid, txt)
            except ValueError:
                messagebox.showerror("无效", "请输入数字：%r" % txt)

        ent.bind("<Return>", lambda e: done(True))
        ent.bind("<Escape>", lambda e: done(False))
        ent.bind("<FocusOut>", lambda e: done(True))

    def apply_value(self, tree, iid, txt):
        """全部数值页提交：iid = 'm<method>|<literal>'。"""
        val = float(txt)
        mid, li = _split_iid(iid)
        t = self._tufa()
        m = next((x for x in t.methods if x.index == mid), None)
        if m is None:
            return
        kinds = dict((i, k) for i, _o, k, _v in t.literals(m))
        if kinds.get(li) == "int":
            val = int(round(val))
        t.set_literals(m, {li: val})
        self._mark(self.entry, mid, li)
        self.refresh_tables()
        self.status("%s[%d] = %s" % (m.name, li, fmt(val)))

    def apply_curve(self, tree, iid, txt):
        """曲线页提交：iid = '<method>|<literal>'。"""
        val = float(txt)
        mid, li = _split_iid(iid)
        c = next((c for c in self.curves if c.method.index == mid), None)
        if c is None:
            return
        self._tufa().set_literals(c.method, {li: val})
        self._mark(self.entry, mid, li)
        self.refresh_tables()
        self.status("%s[%d] = %s" % (c.name, li, fmt(val)))

    def apply_cfg(self, iid, txt):
        """字符串参数页提交：iid = 'c<行>|<token>'（同长度就地改）。"""
        if "|" not in iid:
            return                       # 父行（configureType 行本身）不可编辑
        ci, ti = (int(x) for x in iid[1:].split("|"))
        t = self._tufa()
        cs = cfgstr.parse(t)
        if ci >= len(cs) or ti >= len(cs[ci].tokens):
            return
        c = cs[ci]
        tk = c.tokens[ti]
        try:
            written = cfgstr.set_token(t, tk, txt)
        except cfgstr.CfgError as exc:
            messagebox.showerror("这个值写不下", str(exc))
            return
        self._cfg_marks.setdefault(self.entry, set()).add(tk.off)
        self.refresh_tables()
        self.status("%s 的「%s」= %s（同长度就地改，文件长度不变）"
                    % (c.key, c.label(ti), written))

    # ------------------------------------------------------------- 编辑动作
    def _tufa(self):
        if not self.stats:
            return None
        entry = self.entry
        t = self.pending.get(entry) or self.stats.tufa
        self.pending[entry] = t
        return t

    def _mark(self, entry, method_index, lit_index):
        self.changed_marks.setdefault(entry, set()).add((method_index, lit_index))

    def _factor(self):
        try:
            return float(self.var_factor.get())
        except ValueError:
            messagebox.showerror("系数无效", "请输入数字")
            return None

    def curve_from_selection(self):
        """(curve, lit_index) of the currently selected curve cell."""
        for tv in (self.tree_a, self.tree_b):
            sel = tv.selection()
            if sel:
                mid, li = sel[0].split("|")
                mid, li = int(mid), int(li)
                for c in self.curves:
                    if c.method.index == mid:
                        return c, li
        return None, None

    def set_selected(self):
        c, li = self.curve_from_selection()
        if c is None:
            messagebox.showinfo("提示", "先在曲线表格里点一行")
            return
        try:
            val = float(self.var_cell.get())
        except ValueError:
            messagebox.showerror("无效", "请输入数字")
            return
        t = self._tufa()
        t.set_literals(c.method, {li: val})
        self._mark(self.entry, c.method.index, li)
        self.refresh_tables()
        self.status("已改 %s[%d] = %s" % (c.name, li, val))

    def scale_selected(self):
        c, li = self.curve_from_selection()
        f = self._factor()
        if c is None or f is None:
            return
        t = self._tufa()
        old = dict(c.values()).get(li)
        t.set_literals(c.method, {li: (old or 0) * f})
        self._mark(self.entry, c.method.index, li)
        self.refresh_tables()
        self.status("%s[%d]: %s × %s" % (c.name, li, old, f))

    def scale_curve(self, whole_family=False):
        f = self._factor()
        if f is None or not self.stats:
            return
        if not self.curves:
            messagebox.showinfo("提示", "本 class 没有可识别的曲线")
            return
        # 系数是相对值：每种曲线乘自己的基准（eMuls 用 1 倍，其它也是乘）
        base = self.entry.split("/")[-1][:-6]
        targets = [self.entry]
        if whole_family:
            fam = family_of(base)
            targets = [e for e in self.parts
                       if family_of(e.split("/")[-1][:-6]) == fam]
        n = 0
        for entry in targets:
            if entry == self.entry:
                st = self.stats
                t = self._tufa()
            else:
                try:
                    st = self.editor.load(entry)
                except Exception:  # noqa: BLE001
                    continue
                t = st.tufa
                self.pending[entry] = t
            for c in vdata.curves(t):
                edits = {}
                for i, v in c.values():
                    edits[i] = v * f
                    self._mark(entry, c.method.index, i)
                t.set_literals(c.method, edits)
                n += len(edits)
        self.refresh_tables()
        self.status("已对 %d 个 class 的曲线乘 %s（共 %d 个数值）"
                    % (len(targets), f, n))

    def set_val(self):
        sel = self.tree_v.selection()
        if not sel:
            messagebox.showinfo("提示", "先在表格里点一行")
            return
        try:
            val = float(self.var_val.get())
        except ValueError:
            messagebox.showerror("无效", "请输入数字")
            return
        mid, li = _split_iid(sel[0])
        t = self._tufa()
        m = next((x for x in t.methods if x.index == mid), None)
        if m is None:
            return
        kind = dict((i, k) for i, _o, k, _v in t.literals(m)).get(li, "float")
        if kind == "int":
            val = int(round(val))
        t.set_literals(m, {li: val})
        self._mark(self.entry, mid, li)
        self.refresh_tables()
        self.status("已改 %s[%d] = %s" % (m.name, li, val))

    def scale_val(self):
        f = self._factor()
        sel = self.tree_v.selection()
        if f is None or not sel:
            return
        mid, li = _split_iid(sel[0])
        t = self._tufa()
        m = next((x for x in t.methods if x.index == mid), None)
        if m is None:
            return
        old = dict((i, v) for i, _o, _k, v in t.literals(m)).get(li, 0)
        new = old * f
        if dict((i, k) for i, _o, k, _v in t.literals(m)).get(li) == "int":
            new = int(round(new))
        t.set_literals(m, {li: new})
        self._mark(self.entry, mid, li)
        self.refresh_tables()
        self.status("%s[%d]: %s → %s" % (m.name, li, old, new))

    def revert_part(self):
        if self.entry in self.pending:
            del self.pending[self.entry]
            self.changed_marks.pop(self.entry, None)
            self._cfg_marks.pop(self.entry, None)
            self.load_part(self.entry, quiet=True)
            self.status("已撤销 %s 的未保存改动" % self.entry.split("/")[-1])

    def reload_part(self):
        self.pending.pop(self.entry, None)
        self.changed_marks.pop(self.entry, None)
        self._cfg_marks.pop(self.entry, None)
        self.load_part(self.entry, quiet=True)

    # --------------------------------------------------------------- 保存
    def save(self):
        if not self.pending:
            messagebox.showinfo("提示", "还没有改动")
            return
        self.editor.write_mode = self.var_mode.get()      # 允许中途换格式
        mode = self.var_mode.get()
        edits = {e: t.tobytes() for e, t in self.pending.items()}
        n_cls = len(edits)
        warn = ""
        bak = Path(str(self.zip_path) + ".bak")
        if bak.is_file():
            import datetime
            mt = datetime.datetime.fromtimestamp(bak.stat().st_mtime)
            if self.is_shared:
                warn += ("\n\n⚠ 这是**共享包 java\\classes.zip**：10 台车通用的核心类，"
                         "改坏了可能连游戏都起不来。\n"
                         "建议先手动把整个 java 目录复制一份。\n")
            warn += ("\n注：已存在旧备份（%s，%.1f KB），**不会**被覆盖 —— "
                     "「恢复备份」会回到那个时刻的版本。"
                     % (mt.strftime("%m-%d %H:%M"), bak.stat().st_size / 1024))
        else:
            warn += "\n\n将新建备份：%s" % bak
        if self.is_shared and mode == "raw":
            warn += ("\n\n⚠ 现在是「原样 TUFA」写入 —— 这条路在车辆包里已验证可用，"
                     "但**在 java 包上还没实机验证过**。想稳一点就关掉这个窗口，"
                     "用「车辆数据修改器.bat」（源码模式）跑，它能用 FLZD 原格式重打包。")
        if not messagebox.askokcancel(
                "确认写入",
                "将改写：\n%s\n共 %d 个 class（原 zip 备份为 .bak）\n"
                "写入格式：%s%s\n继续？"
                % (self.zip_path, n_cls,
                   "FLZD（与原版一致）" if mode == "flzd" else "原样 TUFA",
                   warn)):
            return
        try:
            self.status("正在用游戏自己的 FLZD 压缩器重打包…")
            self.root.update_idletasks()
            bak = self.editor.save(edits)
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            messagebox.showerror("写入失败", str(exc))
            return
        self.pending.clear()
        self.changed_marks.clear()
        self._cfg_marks.clear()
        self.load_part(self.entry, quiet=True)
        self.status("已写入 %d 个 class，备份：%s" % (n_cls, bak))

    def restore(self):
        bak = Path(str(self.zip_path) + ".bak")
        info = ""
        if bak.is_file():
            import datetime
            mt = datetime.datetime.fromtimestamp(bak.stat().st_mtime)
            info = ("\n备份时刻：%s（%.1f KB）\n这一步会丢掉那之后的全部改动！"
                    % (mt.strftime("%Y-%m-%d %H:%M:%S"),
                       bak.stat().st_size / 1024))
        else:
            info = "\n没有找到 .bak"
        if not messagebox.askokcancel(
                "恢复备份", "用 %s\n覆盖当前\n%s ？%s"
                % (bak.name, self.zip_path, info)):
            return
        ok = self.editor.restore()
        self.load_part(self.entry, quiet=True) if self.entry else None
        self.status("已恢复备份" if ok else "没有找到 .bak 备份")

    def status(self, s):
        self.var_status.set(s)


def family_of(short):
    """`Coupe_RS_IEngine_stage_II` -> `IEngine`（用公共的族名猜测规则）。"""
    parts = short.split("_")
    for i, p in enumerate(parts):
        if p.startswith("I") and len(p) > 1 and p[1].isupper():
            return p
    for i, p in enumerate(parts):
        if p in STAGES:
            return "_".join(parts[:i])
    return short


def fmt(v):
    if isinstance(v, float):
        if abs(v - round(v)) < 1e-6:
            return "%.1f" % v
        return ("%.6g" % v)
    return str(v)


def _split_iid(iid):
    """'m<method>|<literal>' 或 '<method>|<literal>' -> (method, literal)。

    方法行的 iid 带 `m` 前缀（为了跟曲线行区分）；早期直接 int() 会抛
    ValueError，而窗口化程序里异常被吞掉 -> 表现成「改了没反应」。
    """
    m, _, lit = str(iid).partition("|")
    return int(m.lstrip("m") or 0), int(lit or 0)


def selftest():
    """打包后的 exe 也能跑的自检：不弹窗，直接验证核心链路。

    **不需要 unicorn**：读值走随工具发布的明文快照，写值走明文 TUFA。
    """
    ok = True
    game = vdata.find_game_dir()
    print("game dir      :", game)
    ok &= game is not None
    if not game:
        return 1
    snaps = list(vdata.SNAPSHOT_DIR.rglob("*.tufa"))
    print("明文快照      : %d 个类, %.1f MB (%s)"
          % (len(snaps), sum(s.stat().st_size for s in snaps) / 1e6,
             vdata.SNAPSHOT_DIR))
    ok &= len(snaps) > 1000
    zp = game / "vehicles" / "Phoenix_RS_1997" / "coupe" / "classes.zip"
    ed = vdata.ZipPartEditor(game, zp, write_mode="raw")
    st = ed.load("classes/Coupe_RS_IEngine_stock.class")
    cs = vdata.curves(st.tufa)
    print("读一个零件    : %s（%d 个方法, 曲线 %s）"
          % (st.class_name.split(".")[-1], len(st.tufa.methods),
             ",".join(c.name for c in cs)))
    ok &= len(cs) >= 2
    m = st.tufa.find("eMuls")[0]
    vals = [v for _i, _o, _k, v in st.tufa.literals(m)][2:6]
    print("eMuls 前 4 值 :", vals)
    ok &= vals[:3] == [0, 129, 158]
    # 字符串参数页（configureType 里的质量/气动/挂点）
    zp2 = game / "vehicles" / "Fantasy_Corus_2005" / "hatch" / "classes.zip"
    ed2 = vdata.ZipPartEditor(game, zp2, write_mode="raw")
    st2 = ed2.load("classes/Hatch_S2_WeightReduction_stock.class")
    cfgs = cfgstr.parse(st2.tufa)
    mts = [tk for c in cfgs if c.key == "body" for tk in c.tokens
           if "质量" in c.label(tk.idx)]
    print("字符串参数    : %d 行, body 质量 = %s"
          % (len(cfgs), [tk.text for tk in mts]))
    ok &= bool(mts) and mts[-1].text == "394.000"
    before = st2.tufa.tobytes()
    cfgstr.set_token(st2.tufa, mts[-1], "300")
    after = st2.tufa.tobytes()
    nd = sum(1 for a, b in zip(before, after) if a != b)
    print("同长度就地改  : 394.000 → 300.000，长度 %d→%d，差异 %d 字节"
          % (len(before), len(after), nd))
    ok &= len(before) == len(after) and nd > 0
    print("标签表        :", "已装 %d 条" % labels.count()
          if labels.available() else "未生成（作用列留空）")
    print("结果          : %s" % ("全部通过 ✓" if ok else "有失败 ✗"))
    return 0 if ok else 1


class _Tee:
    """--selftest 用：同时写 stdout 和文件（windowed exe 没有控制台）。"""
    def __init__(self, *streams):
        self.streams = [s for s in streams if s is not None]

    def write(self, s):
        for st in self.streams:
            try:
                st.write(s)
                st.flush()
            except Exception:  # noqa: BLE001
                pass

    def flush(self):
        for st in self.streams:
            try:
                st.flush()
            except Exception:  # noqa: BLE001
                pass


def _run_selftest(fn):
    """跑自检并把报告写进文件，返回 exit code。"""
    import contextlib
    out = Path.cwd() / "selftest_report.txt"
    for i, a in enumerate(sys.argv):
        if a.startswith("--selftest="):
            out = Path(a.split("=", 1)[1])
    with open(out, "w", encoding="utf-8", errors="replace") as f:
        with contextlib.redirect_stdout(_Tee(sys.stdout, f)):
            print("=== LASR 车辆数据修改器 自检 ===")
            rc = fn()
            print("报告文件:", out)
    return rc


def _hook_errors(root, logname):
    """把回调里的异常暴露出来。

    windowed 程序没有 stderr，回调异常会被 Tk 静默吞掉（「点了没反应」就是这么来的），
    所以统一弹框 + 落盘。
    """
    def handler(exc, val, tb):
        txt = "".join(traceback.format_exception(exc, val, tb))
        try:
            (Path.cwd() / logname).write_text(txt, encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
        try:
            messagebox.showerror("出错了（已写 %s）" % logname, txt[-1200:])
        except Exception:  # noqa: BLE001
            pass
    root.report_callback_exception = handler


def emutest():
    """子进程用：unicorn 能不能跑（打包 exe 里会 0xC0000409，主进程据此禁用 FLZD）。"""
    game = vdata.find_game_dir()
    if not game:
        return 1
    try:
        from lasr_core import flzd
        c = flzd.FlzdCodec(game / "LASR.exe")
        return 0 if c.table[11] == 2053 else 1
    except Exception:  # noqa: BLE001
        return 1


def main():
    if "--emutest" in sys.argv:
        raise SystemExit(emutest())
    if any(a.startswith("--selftest") for a in sys.argv):
        raise SystemExit(_run_selftest(selftest))
    root = tk.Tk()
    _hook_errors(root, "vehicle_editor_error.txt")
    try:
        ttk.Style().theme_use("vista")
    except tk.TclError:
        pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
