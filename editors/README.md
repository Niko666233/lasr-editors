# LASR 编辑器两件套（存档修改器 / 车辆数据修改器）

给原版《L.A. Street Racing》(Invictus Games 2006) 用的两个小工具。

```
editors/dist/LASR存档修改器.exe        ← 双击即用（单文件，28 MB，无依赖）
editors/dist/LASR车辆数据修改器.exe    ← 双击即用（单文件，无依赖，不需要游戏之外的任何东西）
editors/vehicle_editor.pyw            ← 车辆修改器本体（源码）
editors/save_editor.pyw               ← 存档修改器本体（源码）
editors/车辆数据修改器.bat             ← 开发用（源码直跑，带 FLZD 压缩器，功能与 exe 相同）
editors/README.md                     ← 本文件
```

两个 exe 都**自带**一份「零件类明文快照」（`editors/data/classes`，2151 个类 / 6.1 MB），
所以不需要装 Python、不需要 unicorn，双击就能用。想连源码一起用就跑 `.bat`。

第一次改之前先看一眼 [安全须知](#安全须知)。

---

## 1. 存档修改器（`dist\LASR存档修改器.exe`，双击）

**干什么**：直接编辑 `C:\Games\LASR\save\career\NNN.sav`。

| 页 | 能改的东西 |
|---|---|
| 生涯数据 | 昵称、当前车、酒吧档位(pub)、司机、声望、**胜场 winSum / 总场次 raceSum**、重试、对手来挑战次数、AI 强度倍率、酒吧档次进度 prestigeValues[15] |
| 车辆与零件 | 加车 / 删车 / 设为当前车（含 10 台宽体版与 3 台车手特供车）；给每台车加零件（下拉框按**零件名**选）、删零件、在「已装车 ↔ 后备箱」之间切换 |
| 挑战赛 | 30 场挑战赛的通过状态，可一键全解锁 |
| 比赛记录 | 每场比赛的胜负/赛道/车/声望，双击一行即可翻胜负 |

**用法**：双击 → 「打开…」选 `001.sav`（默认路径已填好）→ 改 → **保存（自动备份 .bak）**。

**数值含义（来自伪码，不是猜的）**
* `winSum` 只加「赢的场次」，`raceSum` 加「参加过的场次」（含输），胜率 = `winSum/raceSum`。
* `aiLevelMul` 是 AI 强度倍率，越小对手越弱（初始 1.1）。
* 零件记录只有 `(id, status)` 两项：`status=1` = 装在车上，`0` = 后备箱里。
* 零件 id 位域：`31..29 = 类型(1=车辆/零件)`、`28..16 = 车辆索引(VID)`、`15..0 = case 值`；
  `case 值 → 零件类` 的映射由工具现场从 `Model_<Body>.getIPart` 字节码恢复
  （与伪码逐条比对 1057/1057 + 宽体 190/190 全匹配）。
* 出厂自带的零件不写进存档（游戏自己会补），存档里只有**你买过的**。

## 2. 车辆数据修改器（`dist\LASR车辆数据修改器.exe`，双击）

**干什么**：改 `vehicles\<车>\<车身>\classes.zip` 里每个零件类（180–195 个/车体）的数值 ——
也就是**车和零件的真实性能**。

| 页 | 能改的东西 |
|---|---|
| 曲线（扭矩/转速） | `eRPMs`（转速断点）+ `eMuls`（对应扭矩倍率）等 `float[]` 曲线；可单点改、可整条 ×系数，系数还能一次套到**同族全部阶段**（stock/I/II/III/IV/WB） |
| 全部数值 | 该 class 里所有 `INT/FLOAT` 字面量（`initBasics` 的排量/怠速、`initRevCharacter` 的断油转速/惯量…），逐条改或 ×系数 |
| **字符串参数** | `configureType` 字符串里的数值：**★质量(kg)**（`body` 行第 7 个 float —— 减重件/保险杠/引擎盖的重量）、**尾翼气动系数**（`wing`）、零件挂点（`slot`）、损伤系数、悬挂（`spring`）等。**只能填同样字符宽度的值**（同长度就地改，文件长度不变）；填不下会明确拒绝，不会偷偷丢精度 |

**还支持共享包 `java/classes.zip`**（车辆列表最后一项「★共享包 java」）：那里放的是 10 台车通用的类 ——
**氮气容量/喷射加成**（`INitrous.onInstall`，每档一对「加成/容量」= 0.55/4.0、0.5/6.0、0.45/8.0、
0.4/10.0、0.45/12.0，容量刻度 = 干净计时段，1 段 = 1.0、一圈 = 5.0）、**轮胎抓地力**
（`Tyre_<配方>.<init>` 里 6 个接触面数组的第 1 个 float = Pacejka 槽 2 的 µ：NC 1.30 /
SH 1.50 / SM 1.66 / SS 1.85 / RH 2.00 / RS 2.25）、**引擎默认值 / 涡轮开关**
（`IEngine.<i>` 的 `turboPeakP`）。⚠ 这是**核心类**：改前请手动把整个 `java` 目录复制一份；
exe 里只能以「原样 TUFA」写它（尚未实机验证），想稳就用源码模式（`.bat`）跑，它能用 FLZD 原格式重打包。

**改值方式**：表格里**双击一行**直接输入新值（回车生效），或选中后按「设为该值」/
填系数按「×系数」。三个页面都支持双击。

**容易踩的坑**：`I` 开头的类（`IWeightReduction_stock`、`IRims_*`、`ITyres_*`、`IF_Bumper_*`）
是**背包条目**，本身没有数值；真正的参数在同名的 **Part 类**（`WeightReduction_stock` …）。
界面在这时会直接提示你去选哪个。

**「作用」列怎么来的**（不是猜的）：由 `editors/gen_literal_labels.py` 从项目里的
**抬升伪码**（`out_pseudo/…`，即游戏自己的 Java 源码级反编译结果）抓每个字面量在源码里
绑到的字段/数组名，再用字节码逐方法校验（标签个数 == 该方法里 INT/FLOAT 字面量个数）。

当前：**4221 个有字面量的方法里 4202 个有标签（99.5%）、30620 个字面量里 30234 个（98.7%）**，
1768 个类。其中 894 条是构造器（反编译器会吞掉 `super(...)` 的实参）：这些是**从字节码
结构性证明**补出来的（第一条 `invokespecial <init>` 之前的字面量个数、`<init>` 的 owner、
形参类型逐位对照），且每个补出来的值都要跟字节码逐个比对通过才写入 —— 11 条对不上就
宁可不写。

界面里显示成「排量 (engine_volume)」「转速点 第3项」「IEngine 构造参数1」这种人话；
数组下标那种编译器生成的立即数会标「的下标（自动生成，别改）」。

**改动方式**：表格里**双击一行**直接输入新值（回车生效），或选中后按「设为该值」/
填系数按「×系数」。曲线页、全部数值页都支持双击。

**用法**：双击 → 左边选车 → 中间过滤/选零件（例如 `IEngine_stage_II`）→ 右边改 →
**保存到游戏**（原 `classes.zip` 自动备份成 `.bak`）。出问题点「恢复备份」。

**两种写入格式（右下角单选）**
| 模式 | 说明 | 状态 |
|---|---|---|
| 原样 TUFA（exe 里的默认） | 不压缩，直接写明文 TUFA 进 zip。依据：游戏加载器对非 FLZD 数据是「跳过解压、原样交给解析器」（`0x55aead` / `0x4cb089` 两处 `test ebp,ebp; jle skip`） | ✅ **实机实测通过** |
| FLZD（源码跑时可用） | 用游戏自己的压缩器重打包，容器格式与原始条目**逐字节同源**（能把原条目原样复现） | ✅ **实机实测通过** |

exe 里 FLZD 单选会被自动禁用 —— Unicorn（跑游戏压缩器那个模拟器）在 PyInstaller
产物里必崩（见下节），源码运行时才能用。

## 为什么两个工具都能做成单文件 exe

车辆的 class 是自研压缩格式 FLZD，解压原本要靠 Unicorn 模拟执行 `LASR.exe` 的
`flzd_unpack`（`+0x1D50`）。**Unicorn 的 JIT 在 PyInstaller 产物里必让进程
`0xC0000409`**（onefile / onedir 都一样，未打包正常 —— 已定位到就是 `uc.emu_start`），
所以早期车辆修改器只能做成 `.bat`。

现在绕开了：**读值不再解压**。`editors/gen_snapshot.py`（开发机跑一次）把 2151 个类
（10 车包 1850 + `java/classes.zip` 301）解成**明文**存在 `editors/data/classes/`，
随 exe 一起发布（+1.5 MB 压缩后）。工具读取时：

1. 先用 zip 里那条 FLZD 头里的 `uncompressedSize` 跟快照文件大小比对；
2. 一致 ⇒ 直接用快照（**不 import unicorn**，`lasr_core/flzd_head.py` 是纯 Python 的容器头解析）；
3. 不一致（你换过游戏文件 / 用别的工具改过这个类）⇒ 才回退真解压（源码运行时可用）。

写值走「原样 TUFA」，全程不碰压缩器。所以 exe 是干净的单文件，
`--exclude-module unicorn` 打出来还更小（27.8 MB → 约 15 MB）。

**什么时候要重生成快照**：换了游戏版本、或某台车的 `classes.zip` 被别的工具动过。
```
cd editors && ..\.capenv\Scripts\python.exe gen_snapshot.py --force
```

---

## 安全须知

1. **两个工具写盘前都会先备份**：存档 → `<存档>.bak`，车辆包 → `classes.zip.bak`。
   备份**只在第一次写的时候创建，之后不会覆盖**（这样你永远能回到最早那份原版）。
   ⚠ 反过来说：如果你改过好几轮，`.bak` 是最早那次之前的版本 —— 点「恢复备份」会回到那个时刻，
   中间的改动全丢。所以现在**保存/恢复的确认框里都会写明备份的时刻与大小**，看清再点。
2. 改之前**建议整个 `save\career` 与 `vehicles` 目录再手动复制一份**。
   车辆数据的改动是**永久**的，会影响所有存档里的同一台车。
3. 「车辆数据修改器」重打包 `classes.zip` 后，字节流与原始文件不可能逐字节相同 ——
   所以**务必先在游戏里试一次**：改一台车的 `IEngine_stage_IV` 曲线 ×1.5 → 进游戏开车。
4. 程序**不联网、不读注册表**，只碰你指定的 `save\` 和 `vehicles\` 下的文件。

## 自检（怀疑坏了的时候）

```
"editors\dist\LASR存档修改器.exe" --selftest
"editors\dist\LASR车辆数据修改器.exe" --selftest
```

会在**当前目录**写 `selftest_report.txt`（存档：解析 + 零改动回写逐字节比对 + 写盘/备份；
车辆：快照 + 读一个零件类 + 曲线 + 标签表）。也可以指定路径：`--selftest=D:\报告.txt`。

## 复现 / 回归

```
cd editors
..\.capenv\Scripts\python.exe selftest_core.py             # 核心链路：解压→改字面量→两种格式重打包
..\.capenv\Scripts\python.exe smoke_vehicle_editor.py      # 车辆 GUI 无头冒烟（真起 Tk）
..\.capenv\Scripts\python.exe smoke_save_editor.py         # 存档 GUI 无头冒烟（只在副本上写）
..\.capenv\Scripts\python.exe smoke_no_unicorn.py          # ★ 把 unicorn 封掉跑两个工具（= 模拟 exe）
..\.capenv\Scripts\python.exe -m lasr_core.catalog         # 零件目录自检（1057+190 条比对）
..\.capenv\Scripts\python.exe check_label_table.py         # 作用列标签表复核（个数 + 值级，全量 10 车包）
..\.capenv\Scripts\python.exe verify_literal_labels.py     # 标签表独立复算（重读 JSON，从字节码重验）
..\.capenv\Scripts\python.exe gen_snapshot.py              # 重新生成明文快照（需要 unicorn）
..\.capenv\Scripts\python.exe gen_literal_labels.py        # 重新生成作用列标签表
..\.capenv\Scripts\python.exe build_exe.py                 # 重新打包两个 exe
```

## 技术说明（为什么能改得动）

* 游戏的车辆/零件参数不在文本配置里，而是编译进 `classes.zip` 里每个零件类的
  `eRPMs()/eMuls()/initBasics()` 等方法体里（自定义 VM 的 TUFA 字节码）。
  本工具只**原地改 4 字节的字面量载荷**，文件长度与结构完全不变。
* 存档格式逐字复原自 `Gamelogic.save/load`、`Player.save/load`、`RaceChronicle`，
  实测解析 001.sav 恰好消耗完 payload，零改动回写与原文件逐字节一致。
* 曲线识别规则：返回 `float[]` 的方法里，若「第 0 个字面量 == 其余字面量个数 - 1」
  （数组长度），则数据 = 第 2 个字面量之后的全部（eRPMs/eMuls 实测与 docs/14 逐值一致）。

