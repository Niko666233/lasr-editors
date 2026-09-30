# 60 · 编辑器两件套（存档修改器 / 车辆数据修改器）

> 状态：✅ 两个工具可运行并已交付（存档 exe 自检 exit=0；车辆修改器 `.bat`+源码，
> 两种写入格式离线验证通过，**实机生效性待验**）
> 工具：`editors/lasr_core/{savefile,tufa,flzd,vdata,catalog}.py`、`editors/{save_editor,vehicle_editor}.pyw`、
> `editors/build_exe.py`、`editors/{selftest_core,smoke_*}.py`
> 产物：`editors/dist/LASR存档修改器.exe`（27.8 MB，单文件）、`editors/车辆数据修改器.bat`、
> `editors/out_catalog_report.txt`、`editors/README.md`

本轮目标：给原版游戏做两个「双击即用」的改数据工具 —— ① 改车辆/零件的真实性能；
② 改存档（车、零件、胜负、声望…）。**不重写任何游戏算法**：压缩走游戏自己的
`flzd_pack`，格式全部从伪码/字节码逐字复原。

## 1. 交付物与用法

| 文件 | 形态 | 说明 |
|---|---|---|
| `editors/dist/LASR存档修改器.exe` | 单文件 exe，双击即用，无依赖 | 生涯数据 / 车辆与零件 / 挑战赛 / 比赛记录 四页 |
| `editors/车辆数据修改器.bat` | 双击即用 | 拉起项目 venv 的 Python 跑 `vehicle_editor.pyw`（需要 `unicorn`，见 §6） |
| `editors/vehicle_editor.pyw` / `save_editor.pyw` | 源码 | 也可直接 `python xxx.pyw` 跑 |

两者写盘前都自动备份（`<存档>.bak` / `classes.zip.bak`），都带「恢复备份」按钮，
`--selftest` 会写出 `selftest_report.txt`（存档版：解析 + 零改动回写逐字节比对 + 写盘/备份）。

## 2. 存档格式（`save/career/NNN.sav`）

外层容器与 `.rpl`/`options` 同源：`"SDAT" | u32 0x00030100 | u32 fileSize | payload | 12 B 尾`，
`fileSize` = **整个文件**字节数（12+len(payload)+12）。

payload 严格按 `Gamelogic.save()` 的 write 顺序（`out_pseudo/.../Gamelogic.java:1364`）：

| 字段 | 类型 | 语义 / 来源 |
|---|---|---|
| `SAVEFILEID_MAIN=0x97654301`、`SAVEFILEVERSION_MAIN=16` | u32×2 | `Gamelogic.java:24-25` |
| `lastSaveTime`、`nickName` | str（u32 长度含结尾 NUL） | 存档时间 / 玩家名 |
| `lastVehicle` | u32 | **VID 索引**（0..22），不是完整物品 id |
| `carCount` + 每车 `{vehicleId, partCount × {partId, status}}` | u32 | `carId` 是**完整物品 id**；`status` 1=装车 / 0=后备箱（`IVehicle.addItem` 的 `params[0]`） |
| `prestigeValues[15]` | u32×15 | 写盘顺序 index 14→0 |
| `pubIndex`/`driverType`/`tuningPageIndex`/`carsOpen`/`tuningOpen` | u32×5 | `Player.java:704-708` |
| `winSum`/`raceSum`/`retries`/`offeredRaces` | u32×4 | 胜场 / 总场次 / 重试 / 对手来挑战次数 |
| `aiLevelMul` | f32 | AI 强度倍率（初始 1.1，越小越弱） |
| `chronicleCount` + 每场 18 字段 | u32/f32 | `RaceChronicle.save`：splineLeft/crashes/won/rescue/repair/**bestLapTime(f32)**/pushes/trackID/TOD/laps/mycar/mystage/opcar/opstage/pinks/prestige/opstatus/oprank |
| `bastardRaceFinished`/`trialsCompleted`/`trialProgress`/`trials[30]`/`prestige` | u32 | 挑战赛 30 项开关 + 总声望 |

**实测**：`001.sav` 解析恰好消耗完 1375 字节 payload；零改动 `build()` 回写与原文件
**逐字节一致**（含重算 fileSize、尾 12 字节原样带过）。

## 3. 物品 id 位域与零件槽位

```
 31    29 28                      16 15           0
+--------+--------------------------+--------------+
| type(3)| vehicle index(13)       | case(16)     |
+--------+--------------------------+--------------+
type = IVehicle.VHC_PRID = 1（车辆与零件共用）
车辆 id = (1<<29)|(idx<<16)          零件 id = (1<<29)|(idx<<16)|case
```
来源：`ItemRoot.TYPE_*` / `IPart.PART_BITS=16` / `IVehicle.VHC_BITS=32-3-16=13`
（`out_pseudo/.../IVehicle.java:924` 直接给出 `(idx<<16)|(1<<29)`）。

* **VID 表 0..22**（`IVehicle.java:3-27`）：0..9 = 十台生涯车，10..19 = 对应宽体版（`_WB`），
  20..22 = 三台车手特供车；`VID_default = 0`。
* **零件槽位 `ITEMSLOT_*` 0..64**（`IVehicle.java:34-98`）：0..29 外观类、30..44 传动/轮圈/胎、
  45..59 引擎舱件、60..64 杂项；41 号槽没有对应常量（标 `?`）。
* **`case 值 → 零件类`** 由车体类 `Model_<Body>.getIPart(int)` 的 switch 现场恢复
  （不是读伪码）：字节码 `0x1a JMP_EQ2` 的跳转基址是**指令自身**偏移，目标处 `0x27 NEW`
  的常量池引用即类名；`case 0` 落到共享的「压 null + RETURN」尾巴。

## 4. 车辆数据编辑链路

```
vehicles/<车>/<body>/classes.zip ──zip 条目(deflate)──> FLZD 容器
   │  flzd.FlzdCodec.unpack  (unicorn 跑 LASR.exe+0x1D50)
   ▼
 TUFA 类（自定义 VM：CONS/FILD/MTHD/CLSS/TREE）
   │  只在 TREE 里原地覆写 INT/FLOAT LITERAL 的 4 字节载荷（长度/结构不变）
   ▼
 TUFA'  ── 写回 zip ──> ① flzd_pack（LASR.exe+0x1D00，格式与原版逐字节同源）
                        ② 或原样明文 TUFA（见 §6）
```

* **曲线识别规则**（`lasr_core/vdata.py:curves`）：返回 `float[]` 的方法里，
  若「第 0 个字面量 == 其余字面量个数 − 1」（数组长度自洽），则数据 = 第 2 个字面量之后全部。
  实测 `Coupe_RS_IEngine_stock` 解出的 eRPMs/eMuls 与 `docs/14` **逐值一致**
  （0,129,158,184,255,296,305,303,298,291,266,229,113）；`initBasics`(年份/重量)、
  `initRevCharacter`(断油转速)、`initPowerCharacter`(32 点动力表) 一并可见。
* **安全前提**：任何记录只要宽度表没走到自身末尾（`walk()` 返回 None）就拒绝编辑。
* **FLZD 打包正确性硬证据**：把原始条目喂给 `flzd_pack`，**逐字节复现**出游戏原本存的那份
  容器（byte-identical = True）；改过字面量后 `unpack(pack(x)) == x` 恒成立。

## 5. 零件目录（`editors/lasr_core/catalog.py`）

10 台车 × 180–195 条目，共 1850 条目 / 1527 个零件 / 43 个族；显示名 526 个来自类自身
`getName()`（其余 1304 个父类运行时给名，按设计填 None）。

**验收（与伪码逐条比对）**：`Model_<Body>.getIPart` 恢复结果 **1057/1057 匹配**（10 台车主车体）
+ 宽体 `Model_<Body>_WB` **190/190 匹配**，0 条不匹配；全量 id 索引 1057 条，`id→类名→id` 往返 1057/1057。

## 6. 打包：两个环境坑（都实测过）

1. **PyInstaller 打包出的 exe 里，unicorn 的 JIT 必崩**：任何 frozen 产物（onefile / onedir
   都一样）一进 `uc.emu_start` 就 `0xC0000409`（STATUS_STACK_BUFFER_OVERRUN / fastfail），
   而同样的代码在未打包的 Python 里正常（已二分到「mem_map 192 MB + hook_add 都 OK，
   只有 emu_start 崩」）。CFG 标志检查过，不是 CFG。
   ⇒ **车辆修改器因此做成 `.bat`**（拉起 venv 的 Python）；存档修改器不需要压缩器，仍是干净单文件 exe。
2. **非 FLZD 数据的回退行为**：游戏加载器对不带 `FLZD` 魔数的缓冲区是
   「跳过解压、原样交给解析器」而不是报错 —— 两处实测：
   `0x55aead` 与 `0x4cb089` 都是 `flzd_size()` 返回负数后 `test ebp,ebp; jle skip`，
   `flzd_size`（`0x401640`）只在魔数不符时返回 −1。
   **实机已验证成立**：把改过的类以**明文 TUFA**（zip 只做 deflate）写回 `classes.zip`，
   游戏照常加载、改动生效（见 §7）。安装里原本没有一个明文 `.class` 先例，所以这条
   走的是「代码证据 → 实机确认」的路子。⇒ 车辆修改器可以做到**零压缩依赖**。

## 7. 验证清单

**✓ 离线实测（有输出为证）**
* 存档：解析消耗字节数==payload、零改动回写逐字节一致（源码与 exe 内各一次）、写盘+`.bak`。
* 车辆：解压→改→两种格式重打包→从 zip 回读字节相等；「恢复备份」后 zip 与原始逐字节一致。
* 曲线值与 `docs/14` 逐值一致；记录宽度不稳的类拒绝编辑。
* 零件目录 1057+190 条逐条比对 100%；GUI 无头冒烟（真起 Tk）车辆 16/16、存档 21/21。
* 用户真实存档 md5 前后均为 `8482def5e7f0eccd21e51743ee6c8dec`（全程只在副本上写）。

**✗ 需实机（只有这些没验）**
1. ~~重打包（FLZD）后的 `classes.zip` 游戏能否正常加载、性能是否真的生效。~~ ✅ **已实测通过**
   （2026-09-30，改 `Phoenix_RS_1997/coupe` 的引擎曲线后进游戏，动力正常生效）。
2. ~~明文 TUFA 写入是否被游戏接受~~ ✅ **已实测通过**（同上，两种写入格式都能被游戏读进来）
   ⇒ 车辆修改器可以摆脱 unicorn，做成纯 Python 单文件 exe（见 §6 与 ROADMAP 下一步）。
3. 存档加车/加零件后游戏内表现：**加车/删车已实测正常**；加零件已改成「零件目录窗口
   双击即加 + 中文说明」，待复测（`listAllParts()` 只收展示优先级 ≤6 的件仍需注意）。
4. 新车/新零件的零件名与图标在游戏里的显示（2026-09-30 待测）。

## 8. 复现

```bash
cd editors
../.capenv/Scripts/python.exe selftest_core.py           # 核心链路（两种写入格式）
../.capenv/Scripts/python.exe smoke_vehicle_editor.py    # 车辆 GUI 冒烟（只碰 scratch 副本）
../.capenv/Scripts/python.exe smoke_save_editor.py       # 存档 GUI 冒烟（只碰 scratch 副本）
../.capenv/Scripts/python.exe smoke_no_unicorn.py        # ★ 封掉 unicorn 跑完整流程（= 模拟 exe）
../.capenv/Scripts/python.exe smoke_cfg_and_shared.py       # 字符串参数页 + 共享包（只在副本上写）
../.capenv/Scripts/python.exe -m lasr_core.catalog       # 零件目录自检（1057+190 比对）
../.capenv/Scripts/python.exe check_label_table.py       # 作用列标签表复核（个数 + 值级，全量）
../.capenv/Scripts/python.exe verify_literal_labels.py   # 标签表独立复算（重读 JSON + 字节码重验）
../.capenv/Scripts/python.exe gen_snapshot.py            # 重新生成 data/classes 明文快照
../.capenv/Scripts/python.exe gen_literal_labels.py      # 重新生成作用列标签表
../.capenv/Scripts/python.exe build_exe.py               # 重新打两个 exe
"dist/LASR车辆数据修改器.exe" --selftest                  # 打包产物自检（不需要 unicorn）
"dist/LASR存档修改器.exe" --selftest
```

## 9. 未解清单（✗）

1. **实机三项**（§7）—— 这是唯一的硬缺口，需要用户按 README 的「测试 1/2/3」跑一遍。
2. **unicorn-in-frozen-exe 的根因**只定位到 `uc.emu_start` 一步，没查到底是哪条 fastfail
   （可能是 PyInstaller 引导器改变了线程/SEH 环境，使 unicorn 的访客异常处理失效）。
   **已绕过**（§10 快照方案，两个工具都不再需要 unicorn），根因未查。
3. **纯 Python 的 FLZD 编解码**没做。已有可用 oracle（游戏自己的函数跑在 unicorn 里）：
   单字节输入的输出给出「每个字面量的码长 ≈ 11–12 bit」，说明字面量表可能固定
   ⇒ 值得试「只发字面量」的编码器（不用理解匹配器），一旦成立则**写值**也能零依赖
   （现在写值是明文 TUFA，已经能用，所以不急）。
4. `ITEMSLOT 41` 槽语义未知；3 个中文槽位译名存疑（`STYL_F_WING`、
   `STYL_STICKER_F/R_QUARTER`）。
5. `TYPE_IPART=1<<29` 的**取值**只有伪码位宽支撑，没有字节码直接印证。
6. 存档里零件的 `status` 只有 0/1 两态；游戏内部 `changeAttachStatus(int)` 允许负值
   （<0 = 拆下），未找到把它写进存档的路径。

## 10. 让两个工具都变成「双击即用单文件 exe」

**问题**：车辆类的读值要解 FLZD，而解压要跑游戏自己的机器码（unicorn 模拟），
unicorn 的 JIT 在 PyInstaller 产物里必 0xC0000409（§6）⇒ 车辆修改器一度只能做成 `.bat`
拉起 venv 的 Python；存档修改器的零件目录（VID 表 / `getIPart`）同样要解压缩，
**打包后一打开「车辆与零件」页就会整个进程消失**（同一根因，早期版本侥幸没打包进 catalog）。

**方案：明文快照 + 明文写入，运行时完全不需要压缩器。**

| 件 | 作用 |
|---|---|
| `editors/gen_snapshot.py` | 开发机跑一次：用 unicorn 把 2151 个类（10 车包 1850 + `java/classes.zip` 301）解成明文，存 `editors/data/classes/<Car>/<body>/<Class>.tufa`（6.1 MB）+ `classes_manifest.json` |
| `editors/lasr_core/flzd_head.py` | **纯 Python** 的容器头读写（魔数/level/`uncompressedSize`），让「判断是不是 FLZD、校验快照」不拖进 unicorn |
| `vdata.snapshot_hit()` | 用 zip 里那条 FLZD 头的 `uncompressedSize` 跟快照文件大小比对；一致就用快照，不一致才回退真解压。定位方式：先按 `vehicles/<Car>/<body>/` 推路径，推不出来（zip 被复制到别处）再用类名索引兜底 |
| `vdata.read_zip_entry()` / `catalog.read_class()` | 统一的「读一个 zip 条目 → 明文 TUFA」入口，两个工具共用 |
| `build_exe.py` | 两个工具都打包，`--add-data data;data` 带快照，`--exclude-module unicorn`（+capstone） |

关键点：**`lasr_core` 里任何模块级 `import flzd` 都会毁掉 exe**（`catalog.py` 犯过，
已改成懒加载）；读**明文**类时也不能顺手 import flzd（`vdata.load` 犯过，已修）。

**验证**：`editors/smoke_no_unicorn.py` 用 import 钩子把 unicorn/capstone 封成
`ModuleNotFoundError`（= exe 里的情形），然后跑完两个 GUI 的真实流程 —— 21 项全通过
（车辆：选车→选件→改曲线→写明文→从 zip 回读→恢复备份逐字节一致；存档：解析→
VID/`getIPart` 走快照→零件目录窗口→加零件→写盘回读）。两个 exe 的 `--selftest` 均 exit 0
（车辆报告：快照 2151 类 6.1 MB，从 `_MEI…/data/classes` 读出，无 unicorn）。

**exe 侧行为**：启动时探测压缩器可用性（frozen 时用**子进程** `--emutest` 试探，
崩也只崩子进程），不可用就把 FLZD 单选禁用、默认「原样 TUFA」—— 不会再出现
「点一下进程没了」。

## 11. 「全部数值」页的可读性与编辑（用户 A9/A10 反馈）

**① 改不动（真 bug）**：方法行的 Treeview iid 带 `m` 前缀（`m12|3`），
`set_val/scale_val/apply_value` 却直接 `int(iid.split("|")[0])` ⇒ `int("m12")` 抛
ValueError；windowed 程序没有 stderr，Tk 把回调异常静默吞掉 ⇒ 表现成「点了没反应」。
已修（`_split_iid()` 统一解析）并加测试；另外给两个 GUI 都挂了
`root.report_callback_exception` → 弹框 + 写 `*_editor_error.txt`，这类 bug 以后不会再隐身。

**② 每一行的实际意义**：见 README §2「作用」列 —— 标签来自 `out_pseudo` 抬升伪码里
字面量绑定的字段/数组名，逐方法用字节码校验个数。**4221 个有字面量的方法里 4202 个有标签
（99.5%）、30620 个字面量里 30234 个（98.7%）、1768 个类**（`data/literal_labels.json`，709 KB）。
`labels._pretty()` 再把 `local0[0]#下标` 这种反编译残留整成「转速点 第3项」/
「的下标（自动生成，别改）」，字段名加中文注解（「排量 (engine_volume)」），构造器实参
渲染成「IEngine 构造参数1」。

**构造器那 894 条是怎么补的**（原 913 条失败里 908 条是构造器：反编译器把 `super(...)`
的实参吞掉了，个数差 +1 / +3）：不靠猜，靠**从字节码结构性证明 + 值级闸门**——
① 第一条 `invokespecial <init>(0x11)` 之前的字面量个数必须恰好是 k；
② 那个 `<init>` 的 owner 必须等于类里记的父类（`this(...)` 委托时是本类）；
③ 描述符前 k 个形参类型与字面量类型逐位一致（`I/S/B/C/Z`↔int、`F`↔float）；
④ 位置 2..k 的**预测值**取自「同一父类构造器在别的车体里的常量」（leave-one-group-out，
需 ≥3 条且众口一致），位置 1 用类名层级记号（`*_stage_I/II/III/IV/WB`=1..5、`*_stock`=0）；
⑤ 预测值与字节码逐个比对，一条不符就整条丢弃 —— 实测 894 条全部通过（`+3` 那 50 条
由跨车体表预测出 `(stage, 1.0, 0.5)` 并 50/50 命中），11 条被闸门挡下、宁可不写。
**仍失败的 19 条**（0.45%）：11 条构造器被闸门拒绝、5 条 `static_getBoneAssigns`
（反编译 `unreachable`，差 +31）、2 条乘数编在 `0x1C` payload 里、1 条乱码伪码。

**独立复核（不是采信子代理自述）**：`editors/check_label_table.py` 全量 10 车包 / 1850 类
（我实跑 4 车包 733 类 1655 方法）**个数不符 0、值级不符 0**；
`editors/verify_literal_labels.py`（重读 JSON、从字节码复算，不复用生成器抽取）
**4202 条目 / 30234 标签 / 0 不符 / 0 歧义**；与改动前的 JSON 逐条目 diff
**0 条消失、0 条被改动、894 条纯新增**。两个脚本都已入库，换游戏版本时可一键复验。

**③ 行内编辑**：两个页面的表格都支持双击改值（`apply_value` / `apply_curve`）。

## 12. 「字符串参数」页 + 共享包（2026-09-30，回应用户三问）

用户问「外观件影不影响性能 / 氮气轮胎减重为什么没有值 / 能不能加涡轮」，三路并行查证
（结论落盘 `docs/61_PART_PARAM_LOCATIONS.md`），并据此把工具补到能改到那些值。

**根因**：零件参数有四种载体，工具原来只看得见第 1 种 ——
① INT/FLOAT 字面量（原工具支持）；② `configureType("…")` **字符串里的数值**（质量/气动/几何）；
③ **共享包** `java/classes.zip` 里的基类（氮气容量表、轮胎 Pacejka µ）；④ 运行时算出来的（轮毂质量）。

**新增 1：字符串参数页**（`editors/lasr_core/cfgstr.py` + GUI 第三页）
- 解析常量池里所有 `key\t…` 形态字符串 → 数值 token（带**文件内绝对偏移**），
  按 key 给字段中文名（`body` 第 7 个 float = ★质量 kg、`wing` 的系数、`slot` 的物理槽 id…）
  和行尾注释（`; FL_door` 这种零件名直接显示出来）。
- **只做同长度原地替换**：新值短了就补空格（游戏的解析器是 sscanf 风格会跳过空白），
  所以文件长度、池条目数、所有偏移都不变 —— 不需要重序列化容器。
- 新值装不进原宽度就**明确拒绝**，绝不静默丢精度（例：3 字符位置写 `0.05` 只能写成 `0.1`，差 100% → 报错）。
- `Pool` 加了 `offsets`（utf8 字节偏移）；`cfgstr.parse` **每次从 `t.data` 重读**，改完立刻能读到新值
  （和 `Tufa.literals()` 一致）。
- 默认只显示物理相关的 key（`body/wing/damage/flexible/maxsteer/spring/steerhelp/steerspeed/slot`），
  可切换看全部；`I` 开头的背包条目类会直接提示「参数在同名的 Part 类里」。
- 实测（`smoke_cfg_and_shared.py`）：`Hatch_S2_WeightReduction_stock` 底盘质量 394.000 → 300.000，
  **文件长度 1137 不变、只差 2 字节**，写回 zip 后回读一致；超宽值被拒。

**新增 2：共享包 `java/classes.zip`**（车辆列表最后一项「★共享包 java」，304 个条目）
- 读：走随包明文快照（`data/classes/_java/`），不需要 unicorn ✓。
- 写：能跑 unicorn 时自动切 FLZD（字节级与原版同源）；exe 里只能明文，**会明确警告**
  「java 包上尚未实机验证 + 这是核心类，改坏可能连游戏都起不来」并要求确认。
- 「作用」列补了共享类的手写标注（`labels.shared_label`）：`INitrous.onInstall` 的
  5 组「加成/容量」（0.55/4.0、0.5/6.0、0.45/8.0、0.4/10.0、0.45/12.0）+ 消耗率；
  `IEngine.<i>` 的 turboLag/WGLimit/BOVLimit/**turboPeakP（增压总开关）**/flags。
- 实测：INitrous 的容量序列、`Tyre_RS` 的沥青 µ=2.25 都能在界面里看到/改到；
  在**副本**上改 µ 2.25→3.0 后回读成功，真实 `java/classes.zip` 的 md5 全程未变。

**回归**：`smoke_vehicle_editor` / `smoke_save_editor` / `smoke_no_unicorn` / `selftest_core` /
新的 `smoke_cfg_and_shared` 全部通过；两个 exe 的 `--selftest` 里也加了字符串参数的检查。
