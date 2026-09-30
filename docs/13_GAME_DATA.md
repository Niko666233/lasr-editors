# 13 · 游戏数据（字段初始化器抬升）

> 状态：✅ **1,199 个初始化器全部抬升完成**，7,067 条赋值，**类型判据 99.96% 相符、0 不符**
> 工具：`tools/lift_expr.py`（`--class` / `--dump` / `--report`）
> 产物：`out_init.json`（1.8 MB，机器可读）、`out_init_report.txt`（1.3 MB，可 grep 的全文）
> 相关：`docs/12_STACK.md`（栈高）、`docs/10_CONST_POOL.md`（名字）、`docs/11_CLASS_META.md`（字段/父类）

---

## 1. 为什么先打这里

重制最需要的是**数值与规则**，而数值几乎全在**字段初始化器**里：

| | |
|---|---|
| `<clinit>`（静态初始化器） | 1,058 个 |
| `<i>`（编译器生成的实例初始化器） | 141 个 |
| 合计 | **1,199 个，100% 是直线代码（无分支）** |
| 指令总量 | 32,501 条（中位 22 条） |

直线代码意味着不需要控制流重建：拿 `docs/12` 的栈高走一遍符号栈，每个
`PUTFIELD_STATIC` 就变成一条 `字段 = 表达式` 的赋值。这是「抬升伪码」里最简单、
价值最直接的一块。

---

## 2. 结果

```
初始化器方法            1,199 / 1,199 全部直线
赋值语句                7,067
  类型相符              7,064  = 99.96%
  类型不符              0
  无法判定              3      （<i> 里从局部变量取值的 3 条）
  下溢                  0
另含  new 构造          3,081 处、数组字面量 299 处、NEWARRAY 371 处
```

## 3. 判据：字段类型 vs 表达式类型（与栈无关的第二判据）

栈分析只能保证**弹压数量**对；它看不出「算出来的值放错了字段」。所以抬升时同步做类型推断：

| 表达式来源 | 推断出的类型 |
|---|---|
| `INT/FLOAT/STRING LITERAL` | `I` / `F` / `Ljava.lang.String;` |
| `FIELD_REF_*` | 该字段的声明类型（`out_fields.json`，8,487 条） |
| `NEW` + `<init>` | 池里那个类 |
| `INVOKE*` | 描述符的返回类型 |
| `CAST` / `NEWARRAY` / `INSTANCEOF` | 操作数指向的池条目（类/数组描述符） |
| 二元运算 | `S`（本 VM 的统一数值类型）/ `F` / 比较得 `I` |
| `LOCAL_LOAD n` | **方法描述符给的参数类型**（`local0` = `this`），写回时学习 |

然后要求 `PUTFIELD_* <字段, 声明类型 T>` 的右侧表达式类型与 `T` 相容。
不相容就是抬升错了。

**这条判据当场抓到一个栈分析看不见的真 bug**（见 §6）。

三条相容性放宽，每条都有独立证据：

* **`bool` 就是 `int`**：145 处 `I` 字段收到 `false`/`true`（`this.forceChallenge = false`），
  145 处**同向**、零反例 → 该 VM 只有一种整数表示。
* **向上转型合法**：`Gamelogic.manDriver = new drivers.crcman.Main()` —— 字段声明
  `Ljava.game.Driver;`，实际是子类。用 `docs/11` 的 **`CLSS` 父类链**逐级回溯验证
  `drivers.crcman.Main extends java.game.Driver` ✓（8 个车手全部如此）。
* **`S`（统一数值类型）可流入 `I`/`F`**；`SADD` 遇 `String` 操作数按字符串拼接处理
  （`activeControlFile = (controlSaveDir + "active_control_set")`）。

---

## 4. 顺带验证：`NEWARRAY` 的操作数是**本类池索引**

`NEWARRAY` 的载荷不是「元素个数」也不是全局类型码，而是**本类 `CONS` 池的索引，
指向元素类**。判据：把推出的数组类型与**目标字段的声明类型**对照 ——
**550/550 = 100.00% 相符、0 不符**（同一个数字在不同类里指不同的类，所以任何
「全局类型码」假说都会被这条判据立刻打掉）。

---

## 5. 找到的游戏数据地图

按「一个重制需要什么」排：

### 5.1 车表 —— `java.game.item.IVehicle.<clinit>`

**23 辆车**（`VID_MAX = 23`，与条目数**恰好闭合**）：

| 赛道/生涯可解锁（`VID_CAREER_MAX = 10`） | 宽体版（`_WB`，10–19） | NPC 专属（20–22） |
|---|---|---|
| 0 `97_Phoenix_RS` ← **默认车** (`VID_default`) | 10 `97_Phoenix_RS_WB` | 20 `06_Fujin_MX_Matt_Peacock` |
| 1 `83_Phoenix_Trend` | 11 `83_Phoenix_Trend_WB` | 21 `06_Hornet_Wega_Stan_Karew` |
| 2 `05_Invictus_Corus_S2` | 12 `05_Invictus_Corus_S2_WB` | 22 `97_Raptor_ZX_Ted_Cutter` |
| 3 `06_Fujin_MX` | 13 `06_Fujin_MX_WB` | |
| 4 `94_Invictus_Quaddro_SD_T5` | 14 `94_Invictus_Quaddro_SD_T5_WB` | |
| 5 `97_Raptor_ZX` | 15 `97_Raptor_ZX_WB` | |
| 6 `06_Hornet_Wega` | 16 `06_Hornet_Wega_WB` | |
| 7 `04_Takura_Cyclone_R` | 17 `04_Takura_Cyclone_R_WB` | |
| 8 `02_Takura_Tornado_R` | 18 `02_Takura_Tornado_R_WB` | |
| 9 `03_NSR_Dragon_S` | 19 `03_NSR_Dragon_S_WB` | |

车名里的两位数字 = 车型年份。另有 `VHC_SHFT`/`VHC_BITS`/`VHC_MASK`
（车辆 id 在复合键里的位段）、`MAX_PERFORMANCE_PARTS = 28`。

### 5.2 车辆状态位 —— `java.game.Vehicle`

* `TRANSMISSION_*`：`MANUAL 0` / `AUTO 1` / `MANUALCLUTCH 2` / `SEMIAUTO 5` / `HANDBRAKECLUTCH 8`
* `STATS_*`（性能评分下标）：`DURABILITY 0`、`THEORIC_MAX 1`、`WEIGHT 1`、
  `POWER 2`、`ACCELERATION 3`、`BRAKING 4`、`CORNERING 5`、`STABILITY 6`、
  `TOP_SPEED 7`、`MAX 8`
* **`NUMBERS = 43`** = 整车参数数组长度；具名索引 `VPV_*` 21 项（0–20）：

  | | |
  |---|---|
  | 0 | `SUSP_INSTANT_CENTER_F_L` |
  | 1 | `ENGN_IDLE_REDLINE_CUTBACK` |
  | 2/3 | `SUS_F/R_ROLLBAR` |
  | 4/5 | `SUS_F/R_GEOMETRY` |
  | 6/7 | `SUS_F/R_IC_LONG` |
  | 8/9 | `SUS_F/R_IC_HORZ` |
  | 10/11 | `SUS_F/R_IC_TORQ` |
  | 12/13 | `SUS_F/R_COILOVER_FORC` |
  | 14/15 | `SUS_F/R_COILOVER_LENS` |
  | 16–19 | `TYRE_FL/FR/RL/RR_INFL`（4 轮独立胎压/充气量） |
  | 20 | `BRAK_F_R_H` |

  标志位 `VPF_*` 6 项：`CDIFF_FRONT_DRIVE_RATE`、`ENGN_BRAKE_THROTTLE_P1..P4`、`ENGN_INERTIA`。
  存盘：`SAVEFILEID_VHC = -2006563806`、`SAVEFILEVERSION_VHC = 5`。

### 5.3 底盘物理默认值 —— `java.game.parts.Chassis`

* 槽位：`SLOT_HOOD = 601`、`SLOT_WHEEL_FL/FR/RL/RR = 101/102/103/104`
* 车辆能力位 `CF_*`：`STOPPED 4`、`AUTOTRANSMISSION 16`、`SEMIAUTOTRANSMISSION 32`、
  `AUTOCLUTCH 64`、`ABS 128`、`ASR 256`、`BRAKED 262144`、`GHOST 134217728`
* 更新掩码 `FLAG_UPDATE_*`：`WHEELS 1`、`DRIVETRAIN 2`、`SUSPENSION 4`、`HELPERS 8`、
  `PERFORMANCE1 16`、`PERFORMANCE2 32`、`STYLING 64`、`PAINTJOB 128`
* 物理默认值：`max_steer = 0.7`、`maxRPM = 7000.0`、`engine_inertia = 0.2`、
  `engineRPMdownscale = 1.0`、`stickerDensity = 1.0`
* 改装阶段（0 起步）：`tyre/body/suspension/engine/turbo/transmission/brake/drivetrain Stage`
* 车轮位置：`WH_FRONT = 0`、`WH_REAR = 2`

### 5.4 全局状态机与规则 —— `java.game.Gamelogic`

* `GST_*`：`START 0`、`USERLOGIN 1`、`USERINIT 2`、`SERVERLOGIN 3`、`MENU 4`、
  `LOBBY 5`、`ROOM 6`、`INGAME 7`、`PUB 8`、`SETTINGS 10`（**注意 9 缺号**）
* 模式：`SINGLE 1`、`TEST 2`、`DEMO 3`、`MULTI 4`、`GUITEST 5`、`REPLAY 6`、
  `TESTERBOT 7`、`SETTINGS 8`
* **AI 难度倍率：`aiLevelMul = 1.1`、`aiLevelMul2 = 1.5`、`aiLevelMul3 = 0.5`**
* 赛道/路面条件 `CO_*`：`TRACK 1`、`OFFROAD 2`、`WINTER 4`（位组合）
* 竞赛过滤 `GMFILTER_*`：`RACE 1`、`FUN 2`
* 存盘 `SAVEFILEID_MAIN = -1754971391`、`SAVEFILEVERSION_MAIN = 16`
* 联机：`serverName = "LASR server"`、
  `MGSaddress = "matchmaking.lastreetracinggame.com:443"`（原服务器，早已下线）
* 车手槽位 `manDriver1..4` / `girlDriver1..4`（对应 `drivers.crcman*` / `crcgirl*`）

### 5.5 引擎默认配置 —— `java.util.Config`

**`version = "v0.5.2"`**、`acceptBuild = 1000`、`startupClass = "java.game.Init"`、
`language = "en"`、`videoMode = new VideoMode(800, 600, 32, 0)`、`video_gamma = 1.0`、
`postFX = 15`、`shadow_size = 512`、`shadow_specular_factor = 0.7`、
`texture_save_quality = 0.95`、`object_detail = 0.01345`、`blur_factor = 1.0`

### 5.6 其它密度高的类（可直接从 `out_init_report.txt` 查）

| 类 | 赋值数 | 内容 |
|---|---|---|
| `java.net.MetaServer` | 292 | 联机协议/元服务器 |
| `java.io.Input` | 199 | 输入绑定（`activeControlFile = controlSaveDir + "active_control_set"`） |
| `java.game.frontend.controlOptions` | 142 | 按键设置 UI |
| `java.game.item.IVehicle` | 130 | 车表 + 槽位枚举（`ITEMSLOT_STYL_*` 38 项 / `ITEMSLOT_DRIV_*`） |
| `java.game.frontend.gameOptions` / `videoOptions` | 114 / 86 | 选项菜单默认值 |
| `java.game.Track` | 69 | 赛道类基础参数 |
| `java.gfx.GfxEngine` | 31 | 渲染参数 |

---

## 6. 抬升期抓到的两个真 bug（都记在案）

1. **`ARRAY_INIT` 的元素切片错位**：数组字面量里元素先压栈、`NEWARRAY` 最后把数组
   压在**栈顶**，所以元素是 `stack[-n-1:-1]`；我写成 `stack[-n:]` 会把数组自己当成
   最后一个元素（渲染成 `{a, new X[2]}`）。**栈高度完全自洽，是字段类型判据逮住的**
   —— 16 处数组字面量（含 10 张赛道的 `visualisationBounds`）。
2. **构造函数描述符 `()` 没有返回类型**：`(({None})...)` / 类型丢失 2,884 处。
   同一个坑在 `docs/12` 的栈分析里已经踩过一次（那次表现为下溢）；这次是表达式类型
   丢失。**凡是从描述符推类型的地方都要对空尾特判**。

---

## 7. 已知限制

* **非直线方法**：`--class` 只对直线方法给结构化语句；带分支的方法目前是
  「各路径指令按地址顺序线性罗列」并在标题标 `⚠ 有分支`（如 `CarComponent.run()V` 的
  循环体会出现 `local4[local3].enterGarage()` 这种语义错位的行）。
  **本阶段的产物 `out_init.json` 只收录 100% 直线的初始化器，不受影响。**
* **3 条未判定**：`<i>` 里从局部变量取值、变量类型无法从描述符推出。
* **表达式里的 `S`**：统一数值类型，无法区分 int/float——要看具体操作码或字段声明。

## 8. 用法

```bash
python tools/lift_expr.py --class extracted/java/classes/game/Bet.class
python tools/lift_expr.py --dump      # -> out_init.json
python tools/lift_expr.py --report    # -> out_init_report.txt（可 grep 的全文）
```

`out_init.json` 结构：

```json
{"java/classes/game/Bet.class#0":
  {"method": "<clinit>", "class": "java.game.Bet", "linear": true,
   "stmts": [{"target": "java.game.Bet.BET_TYPE_Prestige", "expr": "1",
              "expr_type": "I", "field_type": "I", "match": true}, ...]}}
```

`match` 为 `true`/`false`/`null`（不可判定）三态 —— 这就是类型判据的原始记录。

---

## 9. 下一步

数值与规则的**地图**已经拿到。车表那一块**已核实到这一步**：

* 车参数**不在类初始化器里**：全库 1,199 个初始化器中，只有 `java.game.item.IVehicle`
  自己给 `minPrestige`/`maxPrestige`/`carGroup`/`presetFlags` 等字段写了默认值
  （`-1`/`false`/`9` 之类的占位），没有任何一个具体车型类填真值。
* 每个车型的类（`extracted/vehicles/classes/classes/{Phoenix,Raptor,Fujin,Hornet,
  Invictus,NSR,Takura}.class` 与 `vehicles/<车型>_<年份>/<body>/classes/...`）里只有
  **品牌信息**：`BrandName = "Phoenix"`、`LongBrandName = "Phoenix Motor Corporation"`、
  `BrandLogoTexture = "vehicles\\logos\\Phoenix\\Phoenix.png"`、`BrandLogoTextureUV`。
* `vehicles/<车型>_<年份>.rpk` 抽出来是 **183 张 DDS + 115 个 ISCX 网格 + 2 个 `.bin`**，
  其中的 `.bin`（如 `gap00_00000208.bin`）是**资源目录**（`glosspaint_0` 这类命名的记录表），
  不含性能数值；车辆 rpk 里**没有 RSD 块**。
* 数据加载路径（全库字符串字面量普查 6,032 种）：`vehicles.rpk`（370 次）、
  每个车型的 `vehicles/<车型>.rpk`（各 252–268 次）、`save/career/00`、
  `Tuning\BodySpoilers.evt`、`Pub\ItemMale.evt`，以及
  `java.game.frontend.DEBUG_CarSetupVector` / `DEBUG_CarSetupFloat`
  —— 即**车辆配置（CarSetup）**这条线。

**所以下一步的落点是明确的**：跟 `CarSetup` / `DEBUG_CarSetup*` 这条线走，
找出车型基线参数是从哪个资源记录读出来的（大概率是 `vehicles/<车型>.rpk` 里那个
还没解码的二进制段，或 `Tuning\*.evt`）。

其余按价值排序：

1. **规则方法（P2.7b）**：`Gamelogic` / `Bet` / `Challenge` / `Race` 的**非直线**方法
   需要控制流结构化（`docs/09` 的 CFG + `docs/12` 的栈高已就位）。
2. **赛道几何 ↔ 数值对表**：`maps/*/classes/*_track_*.class` 的
   `visualisationBounds` 等已能读，可与 `docs/05`/`docs/06` 的地形数据核对。
3. **`.evt` 文件**：`Tuning\BodySpoilers.evt` / `Pub\ItemMale.evt` 是新出现的文件类型，
   格式未知（先用 `docs/00` 的手法做一次 magic 普查）。
