"""LASR 存档修改器 (GUI)。

双击运行（.pyw 或打包后的 exe）。能改：
  * 生涯档案：昵称、当前车、酒吧档位、司机、声望、总胜负/重试/接单数、AI 强度
  * 车辆：加车 / 删车 / 设为当前车（含宽体版与三台特殊车）
  * 零件：给某台车加减零件、切换「已装车 / 后备箱」
  * 挑战赛（trials 30 项）：单点开关、一键全解锁
  * 比赛记录（chronicles）：逐场的胜负/声望/赌身体车（pinks）

写入前自动把原档备份成 `<存档>.bak`。
"""
import sys
import tkinter as tk
import traceback
import zipfile
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lasr_core import naming, savefile  # noqa: E402

FONT = ("Microsoft YaHei UI", 9)
BIG = ("Microsoft YaHei UI", 10, "bold")
TITLE = "LASR 存档修改器  (=^･ω･^=)"

try:
    from lasr_core import catalog  # 零件目录（case 值 → 类名 / 车名）
except Exception:  # noqa: BLE001
    catalog = None

PART_STATUS = {0: "后备箱", 1: "已装车"}

# VID 10..19 = 宽体(WB)版，零件表要用 Model_<Body>_WB 那一份
WB_RANGE = range(10, 20)


class App:
    def __init__(self, root):
        self.root = root
        root.title(TITLE)
        root.geometry("1040x680")
        root.minsize(900, 560)
        self.s = None
        self.path = None
        self.car_rows = []
        self.part_rows = []
        self.trial_vars = []
        # 零件目录（懒加载）
        self.cat = None
        self._cat_ready = False
        self._cat_by_car = {}
        self._idx_to_car = {}
        self._case_maps = {}
        self._car_display = {}
        self._build()

    # ------------------------------------------------------------- UI 骨架
    def _build(self):
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(2, weight=1)

        top = ttk.Frame(self.root, padding=(8, 6))
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(1, weight=1)
        ttk.Label(top, text="存档文件:", font=FONT).grid(row=0, column=0)
        self.var_path = tk.StringVar(
            value=str(Path(r"C:\Games\LASR\save\career") / "001.sav"))
        ttk.Entry(top, textvariable=self.var_path, font=FONT).grid(
            row=0, column=1, sticky="ew", padx=4)
        ttk.Button(top, text="打开…", command=self.pick).grid(row=0, column=2)
        ttk.Button(top, text="载入", command=self.load).grid(
            row=0, column=3, padx=4)

        self.lb_info = ttk.Label(self.root, text="未载入", font=BIG)
        self.lb_info.grid(row=1, column=0, sticky="w", padx=10)

        self.nb = ttk.Notebook(self.root)
        self.nb.grid(row=2, column=0, sticky="nsew", padx=8)
        self.tab_career = ttk.Frame(self.nb, padding=8)
        self.tab_cars = ttk.Frame(self.nb, padding=8)
        self.tab_trials = ttk.Frame(self.nb, padding=8)
        self.tab_chronic = ttk.Frame(self.nb, padding=8)
        self.nb.add(self.tab_career, text="生涯数据")
        self.nb.add(self.tab_cars, text="车辆与零件")
        self.nb.add(self.tab_trials, text="挑战赛")
        self.nb.add(self.tab_chronic, text="比赛记录")
        self._build_career()
        self._build_cars()
        self._build_trials()
        self._build_chronic()

        bottom = ttk.Frame(self.root, padding=(8, 6))
        bottom.grid(row=3, column=0, sticky="ew")
        bottom.columnconfigure(4, weight=1)
        ttk.Button(bottom, text="保存（自动备份 .bak）",
                   command=self.save).grid(row=0, column=0)
        ttk.Button(bottom, text="另存为…", command=self.save_as).grid(
            row=0, column=1, padx=6)
        ttk.Button(bottom, text="放弃改动重新载入",
                   command=self.load).grid(row=0, column=2)
        ttk.Button(bottom, text="校验", command=self.check).grid(
            row=0, column=3, padx=6)
        self.var_status = tk.StringVar(value="就绪")
        ttk.Label(bottom, textvariable=self.var_status, font=FONT).grid(
            row=0, column=4, sticky="w", padx=10)

    # --------------------------------------------------------------- 生涯页
    CAREER_FIELDS = (
        ("nickName", "昵称", "str"),
        ("lastVehicle", "当前车", "vehicle"),
        ("pubIndex", "酒吧档位 pub", "int"),
        ("driverType", "司机 driverType", "int"),
        ("prestige", "声望 prestige", "int"),
        ("winSum", "胜场 winSum", "int"),
        ("raceSum", "总场次 raceSum", "int"),
        ("retries", "重试 retries", "int"),
        ("offeredRaces", "对手来挑战次数 offeredRaces", "int"),
        ("aiLevelMul", "AI 强度倍率 aiLevelMul", "float"),
        ("trialsCompleted", "已通过挑战赛 trialsCompleted", "int"),
        ("trialProgress", "当前挑战赛序号 trialProgress", "int"),
        ("bastardRaceFinished", "bastardRaceFinished(0/1)", "int"),
        ("carsOpen", "车库页 home 状态(0/1)", "int"),
        ("tuningOpen", "改装页状态(0/1)", "int"),
        ("tuningPageIndex", "改装页索引", "int"),
    )

    def _build_career(self):
        self.tab_career.columnconfigure(1, weight=1)
        self.career_vars = {}
        for r, (key, label, kind) in enumerate(self.CAREER_FIELDS):
            ttk.Label(self.tab_career, text=label, font=FONT).grid(
                row=r, column=0, sticky="w", pady=2)
            v = tk.StringVar()
            if kind == "vehicle":
                w = ttk.Combobox(self.tab_career, textvariable=v, font=FONT,
                                 width=34, state="readonly",
                                 values=[str(i) for i in range(23)])
            else:
                w = ttk.Entry(self.tab_career, textvariable=v, font=FONT,
                              width=18)
            w.grid(row=r, column=1, sticky="w", padx=6)
            self.career_vars[key] = (v, kind, w)
        r = len(self.CAREER_FIELDS) + 1
        ttk.Label(self.tab_career,
                  text="⚠ 胜/负是累加值：winSum=胜场，raceSum=总场次（含败）。"
                       "改完进游戏里的档案页/酒吧看是否生效。",
                  font=FONT, wraplength=700, justify="left").grid(
            row=r, column=0, columnspan=2, sticky="w", pady=(10, 2))
        ttk.Label(self.tab_career, text="prestigeValues[15]（酒吧档次进度，逗号分隔）",
                  font=FONT).grid(row=r + 1, column=0, sticky="w", pady=6)
        self.var_prestiges = tk.StringVar()
        ttk.Entry(self.tab_career, textvariable=self.var_prestiges, font=FONT,
                  width=64).grid(row=r + 2, column=0, columnspan=3, sticky="w")

    # --------------------------------------------------------------- 车辆页
    def _build_cars(self):
        self.tab_cars.columnconfigure(0, weight=0, minsize=330)
        self.tab_cars.columnconfigure(1, weight=1)
        self.tab_cars.rowconfigure(1, weight=1)

        left = ttk.LabelFrame(self.tab_cars, text="我的车", padding=6)
        left.grid(row=0, column=0, rowspan=3, sticky="nsew", padx=(0, 8))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(1, weight=1)
        self.tv_cars = ttk.Treeview(left, columns=("id", "name"), show="headings",
                                    height=12, selectmode="browse")
        self.tv_cars.heading("id", text="id")
        self.tv_cars.heading("name", text="车")
        self.tv_cars.column("id", width=90, anchor="e", stretch=False)
        self.tv_cars.column("name", width=200, stretch=True)
        self.tv_cars.grid(row=1, column=0, columnspan=2, sticky="nsew")
        self.tv_cars.bind("<<TreeviewSelect>>", lambda e: self.fill_parts())

        bar = ttk.Frame(left)
        bar.grid(row=2, column=0, columnspan=2, sticky="ew", pady=6)
        ttk.Label(bar, text="加车:", font=FONT).grid(row=0, column=0)
        self.var_add_car = tk.StringVar()
        self.cb_add_car = ttk.Combobox(bar, textvariable=self.var_add_car,
                                       font=FONT, width=26, state="readonly",
                                       values=[])
        self.cb_add_car.grid(row=0, column=1, padx=4)
        ttk.Button(bar, text="加", width=3, command=self.add_car).grid(
            row=0, column=2)
        ttk.Button(bar, text="删", width=3, command=self.del_car).grid(
            row=0, column=3, padx=4)
        ttk.Button(bar, text="设为当前车", command=self.set_current).grid(
            row=1, column=1, pady=4)

        right = ttk.LabelFrame(self.tab_cars, text="该车的零件（已买/已装）",
                               padding=6)
        right.grid(row=0, column=1, rowspan=3, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)
        self.tv_parts = ttk.Treeview(right, columns=("pid", "case", "case2",
                                                     "status"),
                                     show="headings", height=12,
                                     selectmode="extended")
        for c, t, w in (("pid", "零件 id", 130), ("case", "case", 55),
                        ("case2", "零件", 190), ("status", "状态", 80)):
            self.tv_parts.heading(c, text=t)
            self.tv_parts.column(c, width=w, anchor="e" if c != "case2" else "w",
                                 stretch=(c == "case2"))
        self.tv_parts.grid(row=1, column=0, sticky="nsew")
        pbar = ttk.Frame(right)
        pbar.grid(row=2, column=0, sticky="ew", pady=6)
        ttk.Label(pbar, text="加零件:", font=FONT).grid(row=0, column=0)
        self.var_addpart = tk.StringVar()
        self.cb_addpart = ttk.Combobox(pbar, textvariable=self.var_addpart,
                                       font=FONT, width=34)
        self.cb_addpart.grid(row=0, column=1, padx=4)
        ttk.Button(pbar, text="加（已装车）",
                   command=lambda: self.add_part(1)).grid(row=0, column=2)
        ttk.Button(pbar, text="加（后备箱）",
                   command=lambda: self.add_part(0)).grid(row=0, column=3,
                                                          padx=4)
        ttk.Button(pbar, text="浏览零件目录…",
                   command=self.open_part_browser).grid(row=0, column=4,
                                                        padx=(10, 0))
        ttk.Label(pbar, text="手动 case 值:", font=FONT).grid(
            row=1, column=0, pady=(4, 0))
        self.var_case = tk.StringVar()
        ttk.Entry(pbar, textvariable=self.var_case, width=10, font=FONT).grid(
            row=1, column=1, sticky="w", padx=4, pady=(4, 0))
        ttk.Button(pbar, text="切换装车状态",
                   command=self.toggle_part).grid(row=2, column=1, pady=4)
        ttk.Button(pbar, text="删零件", command=self.del_part).grid(
            row=2, column=2)
        self.lb_partlist = ttk.Label(
            right, text="", font=FONT, wraplength=420, justify="left")
        self.lb_partlist.grid(row=3, column=0, sticky="w")

    # ------------------------------------------------------------- 挑战赛页
    def _build_trials(self):
        self.tab_trials.columnconfigure(0, weight=1)
        ttk.Label(self.tab_trials,
                  text="30 场挑战赛（每场 3 连赛，共 10 组）。",
                  font=FONT).grid(row=0, column=0, sticky="w")
        wrap = ttk.Frame(self.tab_trials)
        wrap.grid(row=1, column=0, sticky="nsew", pady=6)
        self.trial_vars = []
        for i in range(30):
            v = tk.IntVar()
            cb = ttk.Checkbutton(wrap, text="%02d" % (i + 1), variable=v)
            cb.grid(row=i // 10, column=i % 10, sticky="w", padx=6, pady=3)
            self.trial_vars.append(v)
        ttk.Button(self.tab_trials, text="全部标记完成",
                   command=lambda: self.set_trials(1)).grid(row=2, column=0,
                                                            sticky="w")
        ttk.Button(self.tab_trials, text="全部取消",
                   command=lambda: self.set_trials(0)).grid(row=3, column=0,
                                                            sticky="w", pady=4)

    def set_trials(self, v):
        for var in self.trial_vars:
            var.set(v)
        self.status("已把 30 项挑战赛标记为 %s（记得保存）" % v)

    # ------------------------------------------------------------- 记录页
    def _build_chronic(self):
        self.tab_chronic.columnconfigure(0, weight=1)
        self.tab_chronic.rowconfigure(1, weight=1)
        self.lb_chronic = ttk.Label(self.tab_chronic, text="", font=FONT)
        self.lb_chronic.grid(row=0, column=0, sticky="w")
        cols = ("n", "won", "track", "tod", "laps", "mycar", "opcar",
                "prestige", "pinks")
        heads = ("#", "结果", "赛道 id", "时段", "圈", "我的车", "对手车",
                 "声望", "赌车")
        self.tv_chronic = ttk.Treeview(self.tab_chronic, columns=cols,
                                       show="headings")
        for c, t in zip(cols, heads):
            self.tv_chronic.heading(c, text=t)
            self.tv_chronic.column(c, width=80, anchor="e" if c != "won" else "w",
                                   stretch=(c == "won"))
        self.tv_chronic.grid(row=1, column=0, sticky="nsew")
        self.tv_chronic.bind("<Double-1>", self.flip_chronic)
        ttk.Label(self.tab_chronic,
                  text="双击一行 = 切换该场胜负（won 0/1）。",
                  font=FONT).grid(row=2, column=0, sticky="w", pady=4)

    def flip_chronic(self, _ev=None):
        sel = self.tv_chronic.selection()
        if not sel or not self.s:
            return
        i = int(sel[0])
        rec = self.s["chronicles"][i]
        rec["won"] = 0 if rec.get("won") else 1
        self.fill_chronic()
        self.status("第 %d 场结果改为 %s" % (i + 1,
                                      "胜" if rec["won"] else "败"))

    # --------------------------------------------------------------- 载入
    def pick(self):
        p = filedialog.askopenfilename(
            title="选择生涯存档", initialdir=r"C:\Games\LASR\save\career",
            filetypes=[("LASR 存档", "*.sav"), ("全部", "*.*")])
        if p:
            self.var_path.set(p)
            self.load()

    def load(self):
        p = Path(self.var_path.get())
        if not p.is_file():
            messagebox.showerror("找不到存档", str(p))
            return
        try:
            self.s = savefile.load(p)
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            messagebox.showerror("解析失败", "%s\n\n%s" % (exc, p))
            return
        self.path = p
        s = self.s
        self.lb_info.config(
            text="%s ｜ 昵称 %s ｜ 存档时间 %s ｜ 声望 %d ｜ 胜 %d / 场 %d"
                 % (p.name, s["nickName"], s["lastSaveTime"], s["prestige"],
                    s["winSum"], s["raceSum"]))
        for key, _label, kind in self.CAREER_FIELDS:
            v, _k, w = self.career_vars[key]
            if kind == "vehicle":
                v.set(str(s[key]))
                w.config(values=["%d = %s" % (i, savefile.vehicle_name(i))
                                 for i in range(23)])
                v.set("%d = %s" % (s[key], savefile.vehicle_name(s[key])))
            else:
                v.set(str(s[key]))
        self.var_prestiges.set(", ".join(str(x) for x in s["prestigeValues"]))
        for i, var in enumerate(self.trial_vars):
            var.set(1 if s["trials"][i] else 0)
        self.fill_cars()
        self.fill_chronic()
        self.status("已载入：%d 台车 / %d 条比赛记录 / payload %d 字节"
                    % (len(s["cars"]), len(s["chronicles"]), s["payload_size"]))

    # --------------------------------------------------------------- 刷新
    def car_label_of(self, idx):
        """车标签：优先用目录名（可读），没有目录映射时退回 VID 常量名。"""
        if not self._idx_to_car and self.ensure_catalog():
            pass
        return self.car_label(idx)

    def fill_cars(self):
        self.tv_cars.delete(*self.tv_cars.get_children())
        self.car_rows = []
        if not self.s:
            return
        for i, c in enumerate(self.s["cars"]):
            idx = savefile.vehicle_index_of(c["vehicle"])
            self.tv_cars.insert("", "end", iid=str(i),
                                values=("0x%08X" % c["vehicle"],
                                        self.car_label_of(idx)))
            self.car_rows.append(c)
        self.cb_add_car.config(
            values=["%d = %s" % (i, self.car_label_of(i)) for i in range(23)])
        self.fill_parts()

    def car_index_of_selection(self):
        sel = self.tv_cars.selection()
        return int(sel[0]) if sel else None

    # ---------------------------------------------------- 零件目录（懒加载）
    def ensure_catalog(self):
        """建 VehicleCatalog 并读 VID 表（首次约 1 秒，之后全程复用）。"""
        if self._cat_ready:
            return True
        if catalog is None:
            return False
        self._cat_ready = True
        if self.cat is None:
            try:
                self.status("正在读车辆目录（IVehicle VID 表）…")
                self.root.update_idletasks()
                cat = catalog.VehicleCatalog()
                cat.load_vid_table()
                cat.match_car_index()
                self.cat = cat
                self._idx_to_car = {i: c for c, i in cat.car_index.items()}
                for car, body, zp in catalog.scan_vehicles(cat.game_root):
                    v = catalog.Vehicle(car, body, zp)
                    with zipfile.ZipFile(zp) as zf:
                        stems = [Path(n).stem for n in zf.namelist()]
                    v.models = sorted(s for s in stems if s.startswith("Model_"))
                    self._cat_by_car[car] = v
                    base = [s[len("Model_"):] for s in v.models
                            if not s.endswith("_WB")]
                    v.prefix = min(base, key=len) if base else None
            except Exception:  # noqa: BLE001
                traceback.print_exc()
                self.cat = None
        return self.cat is not None

    def car_label(self, idx):
        car = self._idx_to_car.get(idx)
        tail = " 宽体(WB)" if idx in WB_RANGE else ""
        if car:
            return "%d %s%s" % (idx, car, tail)
        return "%d %s%s" % (idx, savefile.vehicle_name(idx), tail)

    def case_map(self, idx):
        """{case 值: 零件类名}（宽体用 Model_*_WB 那一份）。"""
        if idx in self._case_maps:
            return self._case_maps[idx]
        m = {}
        if self.ensure_catalog():
            car = self._idx_to_car.get(idx) or self._idx_to_car.get(idx - 10)
            v = self._cat_by_car.get(car) if car else None
            if v is not None:
                wb = idx in WB_RANGE
                cands = [n for n in v.models if n.endswith("_WB") == wb]
                stem = (cands or v.models or [None])[0]
                if stem:
                    try:
                        with zipfile.ZipFile(v.zip_path) as zf:
                            for n in zf.namelist():
                                if Path(n).stem == stem:
                                    t = self.cat.read_class(zf, n)
                                    m = catalog.getipart_map(t)
                                    disp, _src = catalog.class_display_name(t)
                                    if disp:
                                        self._car_display[car] = disp
                                    break
                    except Exception:  # noqa: BLE001
                        traceback.print_exc()
        self._case_maps[idx] = m
        return m

    def part_short(self, idx, case):
        cls = self.case_map(idx).get(case)
        if not cls:
            return ""
        short = cls.split(".")[-1]
        car = self._idx_to_car.get(idx)
        pfx = (self._cat_by_car.get(car).prefix if car in self._cat_by_car
               else None) or ""
        for p in (pfx + "_", pfx[:-3] + "_" if pfx.endswith("_WB") else pfx):
            if p and short.startswith(p):
                return short[len(p):]
        return short

    def part_desc(self, idx, case):
        """'引擎 · 四阶 (IEngine_stage_IV)'—— 给用户看的人话。"""
        s = self.part_short(idx, case)
        if not s:
            return ""
        d = naming.describe(s)
        return d if d == s else "%s (%s)" % (d, s)

    # ------------------------------------------------------- 零件目录浏览器
    def open_part_browser(self):
        """列出该车全部可加零件（case / 说明 / 类名 / 是否已拥有），双击即加装。"""
        i = self.car_index_of_selection()
        if i is None or not self.s:
            messagebox.showinfo("提示", "先在左边选一台车")
            return
        idx = savefile.vehicle_index_of(self.s["cars"][i]["vehicle"])
        m = self.case_map(idx)
        if not m:
            messagebox.showwarning(
                "零件目录不可用",
                "没能从游戏目录读到这台车的零件表。\n"
                "检查：游戏目录是否正确（%s）、"
                "lasr_core/catalog.py 是否在。" % self._game_dir_hint())
            return
        owned = {pid & 0xFFFF for pid, _st in self.s["cars"][i]["parts"]}
        win = tk.Toplevel(self.root)
        win.title("零件目录 - %s" % self.car_label(idx))
        win.geometry("720x520")
        win.transient(self.root)
        win.columnconfigure(0, weight=1)
        win.rowconfigure(2, weight=1)
        ttk.Label(win, text="双击一行 = 装到车上；选中后可点下面的按钮加入后备箱。"
                            "「已拥有」= 存档里已经有这个 case。",
                  font=FONT).grid(row=0, column=0, sticky="w", padx=8, pady=6)
        f = ttk.Frame(win)
        f.grid(row=1, column=0, sticky="ew", padx=8)
        ttk.Label(f, text="过滤:", font=FONT).grid(row=0, column=0)
        var_f = tk.StringVar()
        ttk.Entry(f, textvariable=var_f, font=FONT, width=30).grid(row=0,
                                                                  column=1)
        tv = ttk.Treeview(win, columns=("case", "desc", "cls", "own"),
                          show="headings")
        for c, t, w, st in (("case", "case", 60, False),
                            ("desc", "说明", 230, True),
                            ("cls", "类名", 280, True),
                            ("own", "已拥有", 60, False)):
            tv.heading(c, text=t)
            tv.column(c, width=w, stretch=st,
                      anchor="e" if c in ("case", "own") else "w")
        tv.grid(row=2, column=0, sticky="nsew", padx=8)
        bar = ttk.Frame(win)
        bar.grid(row=3, column=0, sticky="ew", padx=8, pady=8)

        rows = sorted((c, cls) for c, cls in m.items() if cls)

        def refill(*_a):
            tv.delete(*tv.get_children())
            flt = var_f.get().lower()
            for c, cls in rows:
                short = cls.split(".")[-1]
                desc = self.part_desc(idx, c)
                if flt and flt not in (desc + short).lower():
                    continue
                tv.insert("", "end", iid=str(c),
                          values=(c, desc, short, "是" if c in owned else ""))

        def add(status):
            sel = tv.selection()
            if not sel:
                return
            for x in sel:
                c = int(x)
                pid = savefile.make_part_id(idx, c)
                if any(p[0] == pid for p in self.s["cars"][i]["parts"]):
                    continue
                self.s["cars"][i]["parts"].append([pid, status])
                owned.add(c)
            self.fill_parts()
            refill()
            self.status("已加 %d 个零件到 0x%08X"
                        % (len(sel), self.s["cars"][i]["vehicle"]))

        var_f.trace_add("write", refill)
        tv.bind("<Double-1>", lambda e: add(1))
        ttk.Button(bar, text="加（已装车）", command=lambda: add(1)).grid(
            row=0, column=0)
        ttk.Button(bar, text="加（后备箱）", command=lambda: add(0)).grid(
            row=0, column=1, padx=6)
        ttk.Button(bar, text="关闭", command=win.destroy).grid(row=0, column=2)
        refill()
        self.status("零件目录：%s 共 %d 项" % (self.car_label(idx), len(rows)))

    def _game_dir_hint(self):
        try:
            from lasr_core import vdata
            g = vdata.find_game_dir()
            return str(g) if g else "没找到 LASR.exe"
        except Exception:  # noqa: BLE001
            return "未知"

    def fill_parts(self):
        self.tv_parts.delete(*self.tv_parts.get_children())
        self.part_rows = []
        i = self.car_index_of_selection()
        if i is None or not self.s:
            return
        idx = savefile.vehicle_index_of(self.s["cars"][i]["vehicle"])
        for j, (pid, st) in enumerate(self.s["cars"][i]["parts"]):
            case = pid & 0xFFFF
            short = self.part_short(idx, case)
            desc = self.part_desc(idx, case) if short else \
                "（目录里没有这个 case）"
            self.tv_parts.insert(
                "", "end", iid=str(j),
                values=("0x%08X" % pid, "%d" % case, desc,
                        PART_STATUS.get(st, str(st))))
            self.part_rows.append((pid, st))
        m = self.case_map(idx)
        vals = ["case=%-5d %s" % (c, self.part_desc(idx, c) or cls)
                for c, cls in sorted(m.items()) if cls]
        self.cb_addpart.config(values=vals[:400])
        if vals and not self.var_addpart.get():
            self.var_addpart.set(vals[0])
        self.lb_partlist.config(
            text="这台车可用零件 %d 项（case 值 = 零件 id 的低 16 位）。"
                 "选中下拉框里的零件再点「加」。%s"
                 % (len(vals),
                    ("车名: " + self._car_display[
                        self._idx_to_car.get(idx, "")])
                    if self._car_display.get(self._idx_to_car.get(idx, ""))
                    else ""))

    def fill_chronic(self):
        self.tv_chronic.delete(*self.tv_chronic.get_children())
        if not self.s:
            return
        n_won = 0
        for i, rec in enumerate(self.s["chronicles"]):
            won = rec.get("won", 0)
            n_won += 1 if won else 0
            self.tv_chronic.insert(
                "", "end", iid=str(i),
                values=(i + 1, "胜" if won else "败", rec.get("trackID", 0),
                        rec.get("TOD", 0), rec.get("laps", 0),
                        rec.get("mycar", 0), rec.get("opcar", 0),
                        rec.get("prestige", 0),
                        "是" if rec.get("pinks") else "否"))
        self.lb_chronic.config(
            text="共 %d 场记录，其中胜 %d 场（存档里的 winSum=%d）"
                 % (len(self.s["chronicles"]), n_won, self.s.get("winSum", 0)))

    # ------------------------------------------------------------ 车辆编辑
    def add_car(self):
        if not self.s:
            return
        txt = self.var_add_car.get()
        if not txt:
            return
        idx = int(txt.split(" ")[0])
        if any(savefile.vehicle_index_of(c["vehicle"]) == idx
               for c in self.s["cars"]):
            if not messagebox.askokcancel("已拥有", "这台车已在列表里，再加一份？"):
                return
        self.s["cars"].append({"vehicle": savefile.make_vehicle_id(idx),
                               "parts": []})
        self.fill_cars()
        self.status("已加车 %d %s" % (idx, savefile.vehicle_name(idx)))

    def del_car(self):
        i = self.car_index_of_selection()
        if i is None or not self.s:
            return
        c = self.s["cars"][i]
        if messagebox.askokcancel("确认", "删掉 0x%08X？" % c["vehicle"]):
            self.s["cars"].pop(i)
            self.fill_cars()
            self.status("已删车")

    def set_current(self):
        i = self.car_index_of_selection()
        if i is None or not self.s:
            return
        idx = savefile.vehicle_index_of(self.s["cars"][i]["vehicle"])
        self.s["lastVehicle"] = idx
        v, _k, w = self.career_vars["lastVehicle"]
        v.set("%d = %s" % (idx, savefile.vehicle_name(idx)))
        self.status("当前车 = %d %s" % (idx, savefile.vehicle_name(idx)))

    def add_part(self, status):
        i = self.car_index_of_selection()
        if i is None or not self.s:
            messagebox.showinfo("提示", "先在左边选一台车")
            return
        txt = (self.var_case.get() or "").strip()
        if not txt:
            txt = (self.var_addpart.get() or "").strip()
            if txt.startswith("case="):
                txt = txt.split("=", 1)[1].split()[0]
        try:
            case = int(txt, 0)
        except ValueError:
            messagebox.showerror("无效", "请在下拉框里选一个零件，或填十进制 case 值"
                                        "（也可写 0x 开头）")
            return
        idx = savefile.vehicle_index_of(self.s["cars"][i]["vehicle"])
        pid = savefile.make_part_id(idx, case)
        self.s["cars"][i]["parts"].append([pid, status])
        self.fill_parts()
        self.status("已加零件 case=%d %s → 0x%08X"
                    % (case, self.part_short(idx, case), pid))

    def del_part(self):
        i = self.car_index_of_selection()
        sel = self.tv_parts.selection()
        if i is None or not sel or not self.s:
            return
        for j in sorted((int(x) for x in sel), reverse=True):
            self.s["cars"][i]["parts"].pop(j)
        self.fill_parts()
        self.status("已删零件")

    def toggle_part(self):
        i = self.car_index_of_selection()
        sel = self.tv_parts.selection()
        if i is None or not sel or not self.s:
            return
        for x in sel:
            j = int(x)
            p = self.s["cars"][i]["parts"][j]
            p[1] = 0 if p[1] else 1
        self.fill_parts()
        self.status("已切换装车状态")

    # --------------------------------------------------------------- 保存
    def _collect(self):
        """把界面上的值写回 dict；返回错误列表。"""
        errs = []
        s = self.s
        for key, label, kind in self.CAREER_FIELDS:
            v, _k, _w = self.career_vars[key]
            raw = v.get().strip()
            try:
                if kind == "str":
                    s[key] = raw
                elif kind == "vehicle":
                    s[key] = int(raw.split(" ")[0])
                elif kind == "float":
                    s[key] = float(raw)
                else:
                    s[key] = int(raw)
            except ValueError:
                errs.append("%s 不是合法数值：%r" % (label, raw))
        try:
            vals = [int(x.strip()) for x in self.var_prestiges.get().split(",")
                    if x.strip()]
            if len(vals) != len(s["prestigeValues"]):
                errs.append("prestigeValues 要 %d 个数，现在 %d 个"
                            % (len(s["prestigeValues"]), len(vals)))
            else:
                s["prestigeValues"] = vals
        except ValueError:
            errs.append("prestigeValues 里有非数字")
        s["trials"] = [int(v.get()) for v in self.trial_vars]
        return errs

    def check(self):
        if not self.s:
            return
        errs = self._collect()
        warns = list(errs) + list(savefile.validate(self.s) or [])
        if warns:
            messagebox.showwarning("校验", "\n".join(str(w) for w in warns[:20]))
        else:
            messagebox.showinfo("校验", "没发现问题 ✓")
        self.status("校验：%d 条提示" % len(warns))

    def save(self):
        if not self.s or not self.path:
            messagebox.showinfo("提示", "先载入一个存档")
            return
        errs = self._collect()
        if errs:
            messagebox.showerror("有字段不合法", "\n".join(errs))
            return
        if not messagebox.askokcancel(
                "确认写入", "改写 %s（原档备份为 .bak）\n继续？" % self.path):
            return
        try:
            savefile.save(self.s, self.path, backup=True)
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            messagebox.showerror("写入失败", str(exc))
            return
        self.status("已写入 %s（备份 %s.bak）" % (self.path, self.path))

    def save_as(self):
        if not self.s:
            return
        errs = self._collect()
        if errs:
            messagebox.showerror("有字段不合法", "\n".join(errs))
            return
        p = filedialog.asksaveasfilename(
            title="另存为", defaultextension=".sav",
            initialfile=Path(self.path).name if self.path else "001.sav",
            filetypes=[("LASR 存档", "*.sav")])
        if not p:
            return
        Path(p).write_bytes(savefile.build(self.s))
        self.path = Path(p)
        self.var_path.set(str(self.path))
        self.status("已另存为 %s" % p)

    def status(self, s):
        self.var_status.set(s)


def selftest():
    """打包后的 exe 自检：解析 → 零改动回写 → 逐字节比对。"""
    import tempfile
    src = Path(r"C:\Games\LASR\save\career\001.sav")
    print("存档      :", src, src.exists())
    if not src.exists():
        return 1
    s = savefile.load(src)
    print("昵称      : %s | 声望 %d | 胜 %d / 场 %d"
          % (s["nickName"], s["prestige"], s["winSum"], s["raceSum"]))
    print("车辆      : %d 台, 比赛记录 %d 条, payload %d 字节"
          % (len(s["cars"]), len(s["chronicles"]), s["payload_size"]))
    blob = savefile.build(s)
    orig = src.read_bytes()
    same = blob == orig
    print("零改动回写: %d -> %d 字节, 逐字节一致 = %s"
          % (len(orig), len(blob), same))
    if not same:
        d = savefile.first_diff(orig, blob)
        print("首个差异 :", d)
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td) / "001.sav"
        tmp.write_bytes(orig)
        savefile.save(s, tmp, backup=True)
        ok = tmp.read_bytes() == orig and (Path(str(tmp) + ".bak")).exists()
        print("写盘+备份 :", ok)
    # 零件目录（决定「浏览零件…」能不能用）
    cat_ok = False
    try:
        print("零件目录  : catalog 模块 =", catalog is not None)
        if catalog is not None:
            c = catalog.VehicleCatalog()
            vid = c.load_vid_table()
            ci = c.match_car_index()
            print("            VID 表 %d 条, 车目录→索引 %d 台 (%s)"
                  % (len(vid), len(ci),
                     ", ".join("%s=%d" % (k, v) for k, v in list(ci.items())[:3])))
            v = c.load_vehicle(*[x for x in catalog.scan_vehicles(c.game_root)
                                 if x[0] == "Phoenix_RS_1997"][0])
            mp, mn = c.getipart_map_for(v)
            print("            %s 的 %s: case 映射 %d 项"
                  % (v.car, mn, len(mp)))
            cat_ok = len(mp) > 50
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        print("零件目录  : 失败 %r" % (exc,))
    print("结果      : %s" % ("全部通过 ✓" if (same and ok and cat_ok)
                              else "有失败 ✗（存档=%s 写盘=%s 目录=%s）"
                              % (same, ok, cat_ok)))
    return 0 if (same and ok and cat_ok) else 1


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
    import contextlib
    out = Path.cwd() / "selftest_report.txt"
    for a in sys.argv:
        if a.startswith("--selftest="):
            out = Path(a.split("=", 1)[1])
    with open(out, "w", encoding="utf-8", errors="replace") as f:
        with contextlib.redirect_stdout(_Tee(sys.stdout, f)):
            print("=== LASR 存档修改器 自检 ===")
            rc = fn()
            print("报告文件:", out)
    return rc


def _hook_errors(root, logname):
    """回调异常必须可见（windowed 程序没有 stderr，Tk 会静默吞掉）。"""
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


def main():
    if any(a.startswith("--selftest") for a in sys.argv):
        raise SystemExit(_run_selftest(selftest))
    root = tk.Tk()
    _hook_errors(root, "save_editor_error.txt")
    try:
        ttk.Style().theme_use("vista")
    except tk.TclError:
        pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
