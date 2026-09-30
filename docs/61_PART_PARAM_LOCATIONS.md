# 61 — 三类「看着找不到值」的零件参数到底在哪（外观件 / 氮气 / 轮胎 / 减重 / 涡轮）

结论来源：`out_pseudo/**` + `editors/data/classes/**` 明文快照（字节码）+ `LASR.exe` 原生
指令，全部**逐条实测**（2026-09-30）。本文件回答用户的三问，并给出「改哪一行」。

> 关键前提：零件参数有**四种载体**，用户现在用的「全部数值」页只看得到第 1 种。
> 1. **INT/FLOAT 字面量**（现有工具能改）
> 2. **`configureType("…")` 字符串里的数值**（质量 kg、气动点系数、几何…）—— 工具不扫字符串
> 3. **共享包 `java/classes.zip` 里的基类**（氮气容量表、轮胎 Pacejka µ）—— 工具根本没加载这个包
> 4. **运行时算出来的**（轮毂质量 = 密度 × 尺寸，`Rim.CalculatePhysMass`）

## 1. 外观零件（保险杠/尾翼/侧裙/引擎盖/尾门/车门/方向盘/贴纸）

**同一外观族的不同 style：物理数据逐字节相同 ⇒ 换 style 不动性能条。**
实测：`Fantasy_Corus_2005/hatch/Hatch_S2_F_Bumper_stock` 与 `…_style_IV` 的 6 条
`body` 行**逐字符相同**（`0.001 sphere` + `2.0 box` + `1.0 box`×4）；贴纸类连
`configureType` 都没有；方向盘每车只有 1 个 `_stock` 类、没有变体。

**三处例外（真有影响）：**

| 例外 | 实测证据 |
|---|---|
| **尾翼气动点系数** | `Phoenix_RS_1997/coupe/Coupe_RS_R_wing`：stock `0.131 -0.459` → style_I..WB `0.186 -0.807`；`Phoenix_Trend` 0.101/-0.354 → 0.164/-0.712；`Fujin` 仅 WB 0.145/-0.508 → 0.115/-0.423 |
| **前杠会多一条气动点 / 改中前系数** | `Coupe_RS_F_Bumper`：stock 3 条 wing（中前 `0.376 0.376`）→ style_I 4 条（中前 `0.305 0.305` + 新增 `wing 5 … 0.100 -0.445`）；`Coupe_RS_Trunk` 0.743 → 0.697 |
| **原厂没有该件的车**，装第一个 style 才新增碰撞体 | `Hatch_S2_L/R_sideskirt`、`Coupe_RS_L/R_sideskirt`、`Hatch_Trend_L/R_sideskirt`、`Coupe_SD_T5_R_wing` 只有 style_I..WB、**无 stock 类**（原厂由车体网格承担）；侧裙 2.5 kg/侧 |
| **轮毂 WB** | 质量与车轮半径都会变 —— 但见 §4：质量是算出来的 |

**机制**：外观件的质量/几何写在 `configureType("body\t…")` 字符串的第 7 个 float（kg）；
下压力/风阻**全在 native**（原生 `body` handler `0x492d20`，sscanf 格式串
`LASR.exe!0x6eef80 = "%f %f %f %f %f %f %f %s %f %f %f %f"` = pos3+rot3+**mass**+形状+尺寸）。
Java 层**不聚合任何 stat**：`IPart.statChanges[]` 长度 = `Vehicle.STATS_THEORIC_MAX = 1`
且**全库从不被写入**（`IVehicle.java:1092-1097` 的累加循环上界就是 1）⇒ 性能条 7 项全取
原生 info block（`ProgrBarCommon`：WEIGHT ← `-infoBlock[0]`）。

**✗ 未证**：零件自带的 `wing` 数组是否真被并进车级气动（只证到「native 解析并存进零件实体」
+ 车级数组 `0x47bbxx` 的链表消费）。⇒ **换尾翼改操控这条必须实机验**。

## 2. 氮气（为什么「全部数值」看不到容量）

- 车辆包 `<Car>_INitrous_stage_<I..WB>.<init>` 只有 3 个实参：`(kind, gain, minRPMmul)`
  —— 实测 10 车全一致：I `1, 1.0, 0.5`、II `2,1.0,0.5`、III `3,1.0,0.5`、IV `4,1.0,0.5`、WB `5,1.0,0.5`。
- **容量/基础加成写死在共享包** `java/classes.zip!game/item/INitrous.class::onInstall`，
  实测字面量序列 = `[1,2,3,4,5, 0.55, 4.0, 0.5, 6.0, 0.45, 8.0, 0.4, 10.0, 0.45, 12.0, 0, 0, 1.0]`
  ⇒ 每档一对 **(加成, 容量)**：I 0.55/4.0、II 0.5/6.0、III 0.45/8.0、IV 0.4/10.0、WB 0.45/12.0；
  末位 `1.0` = `consumption_nitro`（消耗率）。
- `onInstall` 里是 `nitroGain *= this.gain` ⇒ **车辆包里的第 2 个实参（gain）现成可改**，
  改 1.0 → 2.0 即该档加成翻倍；第 3 个实参 = 最低喷射转速比。
- 容量刻度 = 干净计时段（`GmRace.java:4-5` `CLEAN_SECTOR_NITRO_GAIN=1.0` / `CLEAN_LAP=5.0`），
  `giveNitro()` 把 `getN2OTankLevel()` 归一化到 0..1 再 `command("reload …")`。

## 3. 轮胎（抓地力不在车辆包里）

- `Tyre_F_ST/R_ST/U_ST_<stage>` 的 **14 个字面量全是尺寸/几何**：`<clinit>` = 胎宽 mm、
  扁平比 %、轮辋 in、轮辋宽 in + `new float[4]` 的 4；`staticinit` = `configureVisual` 6 个 0、
  `def_style=0`、`0.0005`（碰撞圆柱半径系数）、下标 0。
- **抓地力 = Pacejka 槽 2 的 µ**，在共享包 `java/classes.zip!game/parts/Tyre_<配方>.class::<init>`
  的 6 个 `Ref_pacVars[接触面]` 数组第 1 个 float。实测 `<init>` 第 10 个字面量：
  **NC 1.30 / SH 1.50 / SM 1.66 / SS 1.85 / RH 2.00 / RS 2.25**（冰面另算 0.10–0.30）。
  ⚠ **`Tyre_SS` 的 µ 在第 9 位**（它没设 `SpringRate`，编译器把 µ 排到前面）——
  批量改 µ 必须先解析数组构造顺序，不能盲取固定下标。
- 「某档用哪条配方」= 零件类的**父类名**（stock `Tyre_NC/SH` → I `SH` → II `SM` → III `SS` → IV/WB `RH`，个别 WB 用 `RM`），不是数字。

## 4. 减重 / 轮毂质量（值在字符串里或算出来的）

- `WeightReduction_<stage>` **唯一的字面量是 `staticinit` 的 `return 0`**（无意义）；
  真正质量 = 该类 `configureType("body…")` **第 2 行**的第 7 个 float（kg）。实测：

| 车 | stock | I | II | III | IV |
|---|---|---|---|---|---|
| Hatch_S2 (Corus) | 394 | 250 | 203 | 147 | 113 |
| Coupe_RS (Phoenix_RS) | 225 | 188 | 143 | 112 | 80 |
| Coupe_ZX (Raptor) | 386 | 202 | 106 | 36 | 5 |

  ⇒「减了多少」= stock − 当前档（Corus: −144 kg；Raptor: −381 kg）。悬挂预载有配套补偿
  （`Model_*` 的 `axleLoadDegradationAtBodyStage[档][前/后]`，如 `{0,0}/{79,65}/{105,86}/{135,112}/{154,127}`）。
- **轮毂质量不是静态值**：常量池里的 `body` 串只有前缀
  （`body\t\t0.000 0.000 0.000\t1.571 0.000 0.000\t` 就断了），质量由
  `Rim.CalculatePhysMass(sizes, rimDensity, spikeDensity)` 运行时拼出来
  （`out_pseudo/java/classes/game/parts/Rim.java:37-40`，桶身 `宽*2.54*r*2π*ρ*0.001` + 盘面 `r²π*ρ*0.001`）。
  ⇒ 想改轮毂重量：改**两个密度字面量**（`getRimDensity`/`getSpikeDensity`，如 2.3/1.7）或尺寸，
  这两个**是普通 float 字面量，现有工具能改**。

## 5. 涡轮（能不能给没有涡轮的车加）

- **涡轮不是零件**，是引擎类自带的 6 个常量：`initPowerCharacter` 写
  `turboTable[0..31] / turboLag / turboWGLimit / turboBOVLimit / turboPeakP / turboFlags`
  → `IEngine.onInstall` 抄到车（槽标记 `ITEMSLOT_EBAY_CHARGER`=51）
  → `Vehicle.doUpdatePerformance1` 调 native `Chassis.setTurboParams([FI)V@0x486100`
  （36 个 float 落到引擎子对象 `+0xc34..+0xcc0`，flags → `+0xc20`）。
- **判据**：native `peakP>0.01` 是整段增压的总开关（`0x480615-0x480620 jbe` 跳过），
  增量 ∝ `turboTable` 线性插值；Java 侧 `charged = turboPeakP>0.01` 只决定 HUD 涡轮表显不显示。
- **10 台车 5 有 5 无**：有 = Quaddro / Fujin_MX / Hornet_Wega / Phoenix_RS / Raptor_ZX；
  无 = Corus / NSR_Desert / Phoenix_Trend / Cyclone / Tornado。
- **实测**：非涡轮车的 `initPowerCharacter` 只有 **2 个字面量**（`ClutchF = 1.4 × 700`），
  连 `turboTable` 字样都没有 ⇒ **「改非涡轮车的 turbo 值」在文件里没有落点**。
- **存档里加涡轮件：不可行** —— 全库 1850 类里没有任何 charger/turbo 零件族，
  10 台车 case→类表（1052 条）里没有涡轮件，`updateNeededByItemSlot(ITEMSLOT_EBAY_CHARGER)`
  是**空 case**（`Vehicle.java:779-780`）。原版像是把这族砍了（残留：默认值 + 槽常量）。
- **真要装**：在目标车引擎类里**插入**那 36 组写入指令（照抄 Quaddro 的表），
  需要 TUFA 重序列化（改 TREE 记录长度 + 重打包 FLZD）—— 现有工具只支持**原地覆写 4 字节**，
  这是唯一工程量，且未验证。

## 6. 给工具的两条改造建议（按价值排序）

1. **「字符串型参数」页**：扫 `configureType` 串里的数值（`body` 质量、`wing` 系数、几何…），
   让用户能改减重/外观件质量/尾翼系数。`out_config_dump.csv` 已按 key 抽好字段（`nums[]`）。
2. **支持共享包 `java/classes.zip`**：打开氮气容量表、轮胎 Pacejka µ、`IEngine.<i>` 默认值。
   注意该包条目是 FLZD，写回要么跑 unicorn（exe 里不行），要么走 `write_mode="raw"`（**未实机验证**）。
3. （小）轮毂密度字面量现成可改，可在界面上加一句提示说明「轮毂质量 = 密度×尺寸，运行时算」。
