# 55 — 性能 stat 链 + 槽位系统（零件 → 物理参数 → 性能条；ITEMSLOT ↔ 物理槽）

> 覆盖：`ProgrBarCommon`（性能条 UI 与状态机）+ 原生 `java.game.parts.Chassis.getInfoBlock()`（19 槽 info block）
> + `Vehicle.slotLookupTable`（`fillSLUT` 建表，65 组）+ `java.game.item.SlotMap` + 各零件基类 `attach`（24 个）。
> 本文件关掉 `docs/50 §6.8` 的 #2/#3（`statChanges[]` 谁写 / `STATS_THEORIC_MAX` 矛盾）与 `§9 #7`（`getSlotLookupTable()`）。
> 标注约定：**✓** = 已回原文/反汇编/字节码复核（给出文件行号或 RVA）；**✗** = 未解；**推断** = 由形状/数值域推得。
> 机器可读版：`out_stats_spec.json`（工具 `tools/stat_slots.py`）；重制侧 `remaster/data/stats.json`。
> 复现：`python tools/stat_slots.py --json out_stats_spec.json --report` → `python remaster/tools/build.py --only stats` → `validate.py`。

---

## 0. 结论速览（先看这五条）

1. **零件并不通过 `statChanges[]` 加性能**。`statChanges` 数组长度是 **1**（`IPart.<i>()` 里 `new [F[Vehicle.STATS_THEORIC_MAX]`，
   而 `STATS_THEORIC_MAX = 1` ✓ 字节码真值），`IVehicle.addItem/removeItem` 的循环上界也是它 ⇒
   **Java 层加/卸零件只会改 `statStates[0]`（DURABILITY）**。真正的性能变化走
   **`onInstall()` 把物理参数推给车辆 → 原生 info block 反映出来 → 性能条重新取值**（§1、§3）。
2. **性能条的 7 个值全部来自原生 info block 的固定下标**（0/2/4/12/16/17/18），第 8 个（DURABILITY）来自
   `Vehicle.statStates[0]` —— 这就是 `STATS_THEORIC_MAX = 1` 的由来：**8 项里只有 1 项在 Java 侧存**。✓
3. **info block 是 19 个 float**（原生 `Chassis.getInfoBlock @0x486f20`，`push 0x13` 后分配）✓；
   每个 stat 的**单位与量程**由 `setupSliderRanges` 的字面量钉死（§3.3）：重量 kg(0–2500)、功率 hp(0–600)、
   极速 m/s→km/h(0–350)、加速 = **0-100 km/h 时间** s(2–20)、制动 = **制动距离** m(10–100)、过弯 g(0.5–5)、
   稳定性偏航率 °/s(0–90)、耐久 0–10。
4. **槽位系统有两半**：`slotLookupTable`（**ITEMSLOT → 物理槽**，65 组 / 72 个 `SlotMap`，来自 `fillSLUT` 字节码 ✓）
   + 各零件基类 `attach`（**零件族 → ITEMSLOT**，24 个基类 ✓）。两半合起来才能把一件零件落到车身的物理槽上。
5. **伪码重建在 `fillSLUT` 里丢了 3 个 `SlotMap`**（伪码 69 / 字节码 72）。本表**以字节码为准**重建，
   伪码版只作交叉校验 ⇒ 这是「伪码不等于真相」的又一处实证。✓

---

## 1. 数据流全景

```
                       ┌──────────────── 装/卸零件 ────────────────┐
 零件类 <init>(kind) ──► IPart.statChanges[1]  ← 长度 1，只含 DURABILITY
                       └──────────────────────────────────────────┘
                                  │ attachItem / removeItem
                                  ▼
        Vehicle.statStates[8]（Java 侧唯一被零件改动的 stat：index 0）
                                  │
   IPart.onInstall() ──► 车辆物理参数（torque curve / 质量 / 胎 / 悬挂 …）
                                  │
                                  ▼
   ┌── 原生 java.game.parts.Chassis.getInfoBlock() [F[19]  ◄── @0x486f20（真值来源）
   │        （重量/功率/极速/0-100/制动距离/横向 g/偏航率上限 …）
   ▼
 ProgrBarCommon.refreshSliders(vhc)  ◄── 每帧/每次刷新被调
   ├─ 7 项 ← info_block[0,2,4,12,16,17,18]（取负 + 单位换算）
   └─ DURABILITY ← vehicle.statStates[0]（default 分支）
                                  │
                                  ▼
        8 个进度条 setProgress((act - min) / (max - min)) + "(+x.x)" 增量文案
```

> `statStates / baseStates / newStates / actStates / prevStates / stateDeltas` 六个数组长度都是 `STATS_MAX = 8` ✓
> （`Vehicle.<i>()` 与 `ProgrBarCommon.<i>()` 逐字）。**但只有 index 0 会被零件写**。

---

## 2. 性能 stat 常量（10 个，全部字节码真值）

来源：`out_init.json` ← `tools/lift_expr.py` 从 **TUFA 指令流**抬升（字段类型全匹配、零冲突），
与 `Vehicle.<clinit>` 的原始字面量流 `…5, 0, 1, 1, 2, 3, 4, 5, 6, 7, 8`（按字段序）互为印证。✓

| 常量 | 值 | 备注 |
|---|---|---|
| `STATS_DURABILITY` | 0 | 唯一存在 `statStates[0]` 里的 stat |
| **`STATS_THEORIC_MAX`** | **1** | ⚠ 名字像「8 项理论上限」，**实际值就是 1**（见 §2.1） |
| `STATS_WEIGHT` | 1 | 与 THEORIC_MAX 同值，是历史遗留的重叠 |
| `STATS_POWER` | 2 | |
| `STATS_ACCELERATION` | 3 | |
| `STATS_BRAKING` | 4 | |
| `STATS_CORNERING` | 5 | |
| `STATS_STABILITY` | 6 | |
| `STATS_TOP_SPEED` | 7 | |
| `STATS_MAX` | 8 | 所有「8 项」数组的长度 |

`Vehicle.<clinit>` 里紧接 `STATS_MAX = 8` 之后是 `INVOKESTATIC Vehicle.fillSLUT()` ✓（槽位表在类初始化时建好）。

### 2.1 `STATS_THEORIC_MAX = 1` 是**真的**，不是重建假象（双路证明）

* **路径 A**：`out_init.json` 的 `java/classes/game/Vehicle.class#0`（`<clinit>`）里 `STATS_THEORIC_MAX = 1`。
  该文件由 `tools/lift_expr.py` 直接读 TUFA 指令流抬升，且**字段类型校验为零冲突**。
* **路径 B**：`Vehicle.<clinit>` 的原始字面量序列是 `…, 5, 0, 1, 1, 2, 3, 4, 5, 6, 7, 8`，
  与 `SAVEFILEVERSION_VHC=5` 之后的字段序 `DURABILITY, THEORIC_MAX, WEIGHT, POWER, ACCEL, BRAKE, CORNER, STAB, TOPSPEED, MAX`
  一一对应（11 个字面量 ↔ 11 个字段，无一错位）✓
* **后果（连贯且可验证）**：`IPart.<i>()` 里 `this.statChanges = new [F[java.game.Vehicle.STATS_THEORIC_MAX]` ⇒ 数组长度 1；
  `IVehicle.attachItem/removeItem` 用 `while (i < STATS_THEORIC_MAX) statStates[i] += statChanges[i]` ⇒ 只碰 index 0。
  三处（常量、数组长度、循环上界）自洽 ⇒ **原版就是「零件只在 Java 侧改耐久」**。
* **旁证**：`IVehicle.statChanges` 在**全库没有任何 Java 写入点**（`grep` 只命中声明与那两处累加），
  与「长度 1、只承载耐久增量」的解释一致；8 项性能改动的可见路径只有 info block。✓

> **重制含义**：想做「零件加马力」，不要让零件改 `statStates`；要照原版让零件改**物理参数**，
> 再由你自己的 info block 计算反映到 UI。若重制想给零件做 8 项 stat 增量，那是**新设计**，不是原版行为。

### 2.2 耐久（唯一被零件改的 stat）

* `Model_<Car>.<i>()` / 车辆类里写 `statStates[STATS_DURABILITY] = 6.5`（Hatch_S2 等，各车同值 6.5 ✓）。
* UI 量程 0–10（§3.3），故 6.5 = 65% 耐久条 ✓。
* 装配件（`IEngine` 等）的耐久增量 → `statStates[0]`；`IVehicle.addItem` 加、`removeItem` 减（`if (part.status)` 保护）✓。

---

## 3. 显示链（性能条怎么算出来的）

### 3.1 info block：原生 19 槽

| 项 | 值 | 证据 |
|---|---|---|
| 生产方 | `java.game.parts.Chassis.getInfoBlock() [F` @ `0x486f20`（原生，注册表 `out_native_methods.csv:173`） | ✓ |
| 长度 | **19** | ✓ 反汇编里 `push 0x13` → `call 0x649170` 分配 19 元素数组 |
| 写入模式 | `call 0x6438f0(数组, 槽号, 值)`，槽号 0…18 **顺序**写入；部分槽是 `[chassis+0x20a4]->[偏移] × 浮点参数`（如槽 10 ← `+0x58`、槽 11 ← `+0x2aa8`） | ✓ |
| 取值方 | `ProgrBarCommon.refreshSliders` 里 `local3 = local1.getInfoBlock()` | ✓ |

已定位语义的槽（**由 §3.3 的量程反推 + UI 公式锁定**）：

| 槽 | 含义 | 单位 | 证据 |
|---|---|---|---|
| 0 | 重量 | kg | UI 取负、量程 −2500…0 ⇒ 0…2500 kg ✓ |
| 2 | 功率 | hp（推断） | 量程 0…600 ✓ |
| 4 | 极速 | m/s（UI ×3.6 → km/h） | 量程 0…350 km/h ⇒ 0…97 m/s ✓ |
| 12 | 0-100 km/h 加速时间 | s | UI 取负、量程 −20…−2 ⇒ 2…20 s ✓ |
| 16 | 制动距离 | m | UI 取负、量程 −100…−10 ⇒ 10…100 m ✓ |
| 17 | 过弯横向加速度 | g | 量程 0.5…5.0 ✓ |
| 18 | 稳定性（偏航角速度上限） | rad/s（UI /3.142×180 → °/s） | 量程 0…90 °/s ✓ |
| 其余 12 槽 | ✗ 未逐条追原生函数体 | — | 见 §7 |

### 3.2 UI 公式（`ProgrBarCommon.refreshSliders(vhc)`，逐行）

```java
local3 = vhc.getInfoBlock();                      // 19 槽
for (i = 0; i < Vehicle.STATS_MAX; i++) {         // 8 项
  switch (vhc.statsUpdateMode) {
    case 0:  /* 预览态 → newStates */
    case 1:  /* 基准态 → baseStates，并 newStates = baseStates、delta = 0 */
      switch (i) {
        case STATS_BRAKING:      X[i] = -local3[16];                    break;  // 146/176
        case STATS_ACCELERATION: X[i] = -local3[12];                    break;  // 149/179
        case STATS_WEIGHT:       X[i] = -local3[0];                     break;  // 152/182
        case STATS_TOP_SPEED:    X[i] =  local3[4] * 3.6;               break;  // 155/185
        case STATS_STABILITY:    X[i] = (local3[18] / 3.142) * 180.0;   break;  // 158/188
        case STATS_CORNERING:    X[i] =  local3[17];                    break;  // 161/191
        case STATS_POWER:        X[i] =  local3[2];                     break;  // 164/194
        default:                 X[i] =  vhc.statStates[i];             break;  // B514/B924（未结构化块）
      }
  }
}
```

* `default` 分支就是 **DURABILITY**（8 项里只有它不在 switch 里）✓ —— 两个未结构化块
  `B514`（case 0）/`B924`（case 1）的指令形态是 `this.<field>[i] = vhc.<field226>[i]`，
  `field226` = `Vehicle.statStates` ✓。
* **`STATS_TOP_SPEED` 的量纲链**：`m/s ×3.6 = km/h`，UI 侧再 ×0.62 → mph；`3.6 × 0.62 = 2.232` 恰是 km/h→mph 的换算 ✓ 自洽。
* **取负的三项**都是「越大越差」的量（重量、0-100 时间、制动距离）✓ 物理自洽。

### 3.3 滑块量程 = 原版对各 stat「单位与量程」的声明（`setupSliderRanges`，字面量逐条）

| stat | sliderMin | sliderMax | 读出的单位/域 |
|---|---|---|---|
| BRAKING | −100.0 | −10.0 | 制动距离 10–100 m ✓ |
| WEIGHT | −2500.0 | 0.0 | 重量 0–2500 kg ✓ |
| STABILITY | 0.0 | 90.0 | 偏航率 0–90 °/s ✓ |
| DURABILITY | 0.0 | 10.0 | 耐久 0–10（6.5 → 65%）✓ |
| ACCELERATION | −20.0 | −2.0 | 0-100 时间 2–20 s ✓ |
| TOP_SPEED | 0.0 | 350.0 | 极速 0–350 km/h ✓ |
| CORNERING | 0.5 | 5.0 | 横向 g 0.5–5.0 ✓ |
| POWER | 0.0 | 600.0 | 功率 0–600 hp ✓ |

方法体里 `local2 = vc.getCarClass()` 被算出来但**没被用**（量程与车级无关）✓ —— 重制可以照抄成常量表。

### 3.4 进度条与增量文案（同一文件）

* 8 个 bar：`setProgress((actStates[i] - sliderMin[i]) / (sliderMax[i] - sliderMin[i]))` ✓（0…1 归一化）。
* `base2newDelta[i] = (int)((newStates[i] - baseStates[i]) * 10) / 10` ✓（保留一位小数），
  UI 用它显示 `(+x.x)` / `(-x.x)`（`updateLabel`）✓。
* **例外：`HandlingProgressBar` 不走 stat 链**，它是 `IVehicle.carConfigurationValue()`（配置完成度 0…1，
  caption 显示百分比）✓ —— 与 `CORNERING` 无关，重制不要混淆（原版「Handling」= 这颗车被配置到什么程度）。

### 3.5 `statsUpdateMode` 状态机

| 值 | 含义 | 置位者（行号 ✓） |
|---|---|---|
| `1` | **基准态**：当前实车状态就是基准（`baseStates` ← info block，delta 归零） | `Vehicle.<i>()`（初值 1）、`Vehicle:467`（`setParent` 取回车：dehibernate+resetdamage）、`ProgrBarCommon:36-40`（日志 `forced by stats bar`）、`MakeBetPopup:460` |
| `0` | **预览态**：算「装上去会变成什么样」（`newStates` ← info block，并算 `base2newDelta`） | `ItemlistComponent:255/277`（仅当当前是 −1 时 → 0，日志 `USERVEHICLE.statsUpdateMode => 0 (#7)`） |
| `-1` | **已消费**：`refreshSliders` 结尾置回；UI 不再自动刷新，直到有人再置 0/1 | `ProgrBarCommon:208` |

⇒ 重制实现顺序：**装件 → 置 0 → 刷新（画预览条 + `(+x.x)`）→ 收尾置 −1 → 回车/取回车时置 1 重建基准**。✓

---

## 4. 槽位系统（`docs/50 §9 #7` 闭环）

### 4.1 两个数据结构

```java
// java.game.item.SlotMap：一个「物理槽」及其义务
SlotMap(I slot)              → slot=参数, partIndex=0, linkVirtualSlot=-1      // 单参构造
SlotMap(III a, b, c)         → slot=c,    partIndex=b, linkVirtualSlot=a       // 三参：逆序编号（伪码读法规则 1）
//   ↑ 实测调用：new SlotMap(3, 0, 1140) ⇒ linkVirtualSlot=3, partIndex=0, slot=1140 ✓（字节码复核）

// java.util.Vector Vehicle.slotLookupTable：下标 = ITEMSLOT_*（0..64）
//   baseslotcount = slotLookupTable.size() = 65  ✓
// 每项 = SlotMap[]（该 item slot 占用的全部物理槽）
```

**表的用途（消费方 `IVehicle.removeItem`，逐行 ✓）**：要腾出某个虚拟 item 槽 `v` 时，
遍历车上已装件的 `attach`（一件可占多个 ITEMSLOT）→ 用 `attach[k]` 作为下标查表 →
取该组的 `SlotMap[]` → 凡是 `linkVirtualSlot == v` 的物理槽，其对应零件被卸下（进 `spareParts`）。

⇒ 所以 `linkVirtualSlot` 的语义是「**这个物理槽同时算作哪个 item 槽**」（不是某种父级关系）。

### 4.2 全表（65 组；空组见 4.4）

| ITEMSLOT | 名 | 物理槽 | partIndex / link |
|---:|---|---|---|
| 0 | STYL_F_BUMPER | 1000 | 0 |
| 1 | STYL_HOOD | 1010 | 0 |
| 2 | STYL_SIDESKIRTS | 1020, 1021 | 0 |
| 3 | STYL_TRUNK_HATCH | 1030 | 0 |
| 4 | STYL_R_BUMPER | 1040 | 0 |
| 5 | STYL_HEADLIGHTS | 1100, 1101 | 0 |
| 6 | STYL_F_DOORS | 1110, 1111 | 0 |
| 7 | STYL_R_DOORS | 1120, 1121 | 0 |
| 8 | STYL_TAILLIGHTS | 1130, 1131 | 0 |
| 9 | STYL_R_WING | 1140 | link→3（尾翼装到尾门那个槽）|
| 10 | STYL_F_GUARD_RAIL | 1200 | 0 |
| 11 | STYL_S_GUARD_RAILS | 1210, 1211 | 0 |
| 12 | STYL_ROLLCAGE | 1220 | 0 |
| 13 | STYL_R_GUARD_RAIL | 1230 | 0 |
| 14 | STYL_F_WING | 1240 | 0 |
| 15 | STYL_F_MIRRORS | 2000, 2001 | 0/1, link→6（后视镜占据前门槽）|
| 20 | STYL_F_SEATS | 2100, 2101 | 0 |
| 21 | STYL_R_SEATS | 2110, 2111, 2112 | 0 |
| 22 | STYL_STEER_WHEEL | 2120 | 0 |
| 23 | STYL_SHIFT_KNOB | 2130 | 0 |
| 26 | STYL_ENTERTAINMENT | 2210 | 0 |
| 27 | STYL_INTERIOR_TRIM | 2220 | 0 |
| 28 | STYL_GAUGES | 2230 | 0 |
| 35 | RGER_TYRES | **3240, 3241, 3140, 3141** | 0/1/2/3, link→36 ×4（四条胎各占一个轮毂槽）|
| 36 | RGER_RIMS | 101, 102, 103, 104 | 0（四个轮毂挂点）|
| 38 | DRIV_R_RIMS | 103, 104 | 0 |
| 39 | DRIV_R_TYRES | 3140, 3141 | 0/1, link→38 |
| 40 | RGER_SUSPENSION | 3100,3101,3102, 3200,3201,3202, 3110,3111, 3210,3211 | 0（10 个槽：前后桥 × 左右 × 3 件）|
| 42 | RGER_BRAKES | 3120, 3121, 3220, 3221 | 0 |
| 43 | DRIV_F_RIMS | 101, 102 | 0 |
| 44 | DRIV_F_TYRES | 3240, 3241 | 0/1, link→43 |
| 45 | EBAY_ENGINE | 4000 | 0 |
| 49 | EBAY_RADIATOR | 4040 | 0 |
| 53 | EBAY_MUFFLER | 4130 | 0 |
| 54 | EBAY_INTERCOOLER | 4140 | 0 |
| 59 | EBAY_N20 | 4240 | 0 |
| 61 | STYL_ROOF_WING | 10000 | 0 |
| 62 | STYL_CHASSIS_R_WING | 1140 | 0（与 9 共用物理槽，故 62 无需 link）|
| 63 | MISC_WEIGHT_REDUCTION | 9999 | 0 |
| 64 | MISC_LIGHTBAR | 9998 | 0 |

* **前/后轮归属（推断）**：`101/102 = 前`、`103/104 = 后`（由 `DRIV_F_RIMS = 101,102`、`DRIV_R_RIMS = 103,104` 推）✓；
  同理 `32xx = 前`、`31xx = 后`（由 `DRIV_F_TYRES = 3240,3241`、`DRIV_R_TYRES = 3140,3141` 推）✓ —— 注意这与「31 在 32 前」的直觉相反。
* 物理槽 id 共 **63 个不同值**（100..10000），全部由车辆/地图 Model 的 `configureType("slot\t\t<pos>\t<rot>\t<id>")` 声明（§4.5）。

### 4.3 校验（`validate.py` 已断言）

「65 组 / 下标 0..64 齐全」「SlotMap 共 72 条」「`linkVirtualSlot` 落在 ITEMSLOT 值域」「物理槽 id ∈ 100..10000」
「无物理槽的 item 槽恰好 25 个」「`RGER_TYRES` 恰好 4 个槽 = 前 3240/3241 + 后 3140/3141」「四条胎 link→36」✓

### 4.4 没有物理槽的 25 个 item 槽（非网格族）

`16/17/18/19/37`（贴纸：STICKER / _DOOR / _F_QUARTER / _R_QUARTER / _ROOF，整族共用 `STICKER + placement_`）、
`24`(HORN)、`25`(WINDOW_TINT)、`29`(PAINTJOB)、`30/31/32/33/34`(TRANSMISSION/CLUTCH/F·C·R DIFF)、
`41`(id 空洞，无常量)、`46/47/48/50/51/52/55/56/57/58`(EBAY_FUEL_SYSTEM/CYLINDER_HEAD/LUBRICATION/INTAKE/CHARGER/EXHAUST/ECU/TCS/ABS/ESP)、
`60`(DUMMIESOFTHEDUMMIES)。

⇒ 这些是**纯逻辑件**（涂装/贴纸是贴图，变速箱/差速器/电控在车体内不可见）✓ —— 与 §4.5 的 `attach` 互证：
它们出现在 `attach` 里却查不到物理槽，正是「装得上但看不见」的设计。

### 4.5 零件族 → ITEMSLOT（`attach`，24 个基类逐条 ✓）

| 基类 | attach | 基类 | attach |
|---|---|---|---|
| `IF_Bumper` | `STYL_F_BUMPER` | `IR_Bumper` | `STYL_R_BUMPER` |
| `IHood` | `STYL_HOOD` | `ISideskirts` | `STYL_SIDESKIRTS` |
| `IHatchDoor` | `STYL_TRUNK_HATCH` | `ITrunkLid` | `STYL_TRUNK_HATCH` |
| `IF_Doors` | `STYL_F_DOORS` | `ISet` | 由形参给出（门/内饰等复用族的基类）|
| `ITrunkRWing` | `STYL_R_WING` | `IChassRWing` | `STYL_CHASSIS_R_WING` |
| `IEngine` | `EBAY_ENGINE` | `IMuffler` | `EBAY_MUFFLER` |
| `INitrous` | `EBAY_N20` | `ITransmission` | `DRIV_TRANSMISSION` |
| `IRunningGear` | `RGER_SUSPENSION` | `ITyres` | `RGER_TYRES`（四条胎一套）|
| `IRims` | `RGER_RIMS`（四只轮毂一套）| `IWeightReduction` | `MISC_WEIGHT_REDUCTION` |
| `ISteeringWheel` | `STYL_STEER_WHEEL` | `IInterior` | `STYL_INTERIOR_TRIM` |
| `IPaintjob` | `STYL_PAINTJOB` | `ICTF_Lightbar` | `MISC_LIGHTBAR` |
| `ISticker` | `STYL_STICKER + this.placement_`（表达式，故覆盖 16–19/37）| `IPart` | `DUMMIESOFTHEDUMMIES`（基类默认，另有形参版供 `ISet` 族复用）|

**算法**：零件装在车上时，`attach` 里的每个 ITEMSLOT 经 `slotLookupTable` 展开成物理槽；
`partIndex` 指明「同一件 multi-mesh 的第几块」（如四条胎：`partIndex 0..3`）✓。

### 4.6 物理槽 id 与车辆 Model 的关系

* 车辆/地图 Model 用 `configureType("slot\t\t<x y z>\t<r p y>\t<id>")` 声明物理槽的**位置与 id** ✓
  （例：`Model_Hatch_S2` 里 `…\t9998`、`…\t1000`）。
* 全部 `Model_*.java` 共声明 **37 个不同 id**；与表里 63 个 id 的交集 **26 个** ✓。
* 表里有、Model 里没声明的那些（如 4000/4040/4140/4240 引擎舱、31xx/32xx 桥与轮、1200–1240 护杠/防滚架）
  ⇒ **✅ 已闭环（`docs/56`）**：位姿有**两类**声明者——车 Model（骨架槽 + 默认件）与**零件类自身**（造型件自带 `slot` 行，换 `style_*` 即换位姿）；
  而 31 个「无人声明」的槽中，**12 个是有零件但无网格的逻辑槽**（引擎/悬挂/氮气：类的 `configureType` 调用数为 0），**19 个是游戏从未出货的死槽**（护栏/防滚架/后排座椅/刹车/散热器…）。
* Model 有、表不引用的 11 个（`131..134`、`402..405`、`911/912`、`9997`）⇒ 非 item 物理槽（默认件/挂点），✗ 未逐一命名。
* 单看 `Model_Hatch_S2`：36 条 slot 声明 / 34 个 id，其中 23 个落在表里 ✓ —— 其余 40 个表内 id 是别的车型才有的件（同车型系差异，不是漏抓）。

---

## 5. 重制落地清单（引擎侧）

1. **物理参数是唯一真源**：零件 `onInstall()` 改车辆物理参数；info block 由物理状态算出（19 槽）。
2. **性能条**：照 §3.2 的 7 项映射 + §3.3 的量程做归一化；耐久单独由「耐久值/10」出条。
3. **装件预览**：装件后算一份「预期 info block」→ 画预览条 + `(+x.x)`；离开预览恢复基准（§3.5 状态机）。
4. **装配系统**：`attach`（零件族 → ITEMSLOT）+ `slotLookupTable`（ITEMSLOT → 物理槽）+ Model 的 `slot` 行（几何）三者合参；
   物理槽被占则先卸（按 `linkVirtualSlot` 找冲突件）。
5. **Handling 条**单独实现（配置完成度），别接 `CORNERING`。

---

## 6. info block 逐槽（★ 本轮新增：19 槽全部对位）

**结构**：info block **不是**「物理量数组」，而是原生填充器 `0x4544a0`（stdcall，2 参 / `ret 8`）写出的一块
**≥0x220 字节**结构的**前 28 个 float**（`+0x00…+0x6c`）；`Chassis.getInfoBlock() @0x486f20` 只挑其中 19 个搬进
Java `float[19]`，顺序固定 0…18。

**偏移怎么来的**（可复现，工具 `tools/native_frame_trace.py`）：反汇编里逐槽是
`mov reg,[esp+X] → push reg → push 槽号 → push 数组 → call 0x6438f0`，而 `push` 会让后续 `[esp+X]` 漂移，
肉眼对不上号。工具跟踪「未清理 push 字节数 D」把每次读取换算成**栈帧内固定偏移**，以最低读偏移为结构起点
（槽 0 的来源 = 结构 `+0x00`）——这个锚点被**独立证据**钉住：槽 0 的值 = `1.0 / [动力总成+0x14]`（倒数质量），
而 UI 的 `WEIGHT` 正是 `-infoBlock[0]`（kg）✓。

| 槽 | 结构偏移 | 名字 | 单位 | 置信 | 依据 |
|---|---|---|---|---|---|
| 0 | `+0x00` | 重量 | kg | ✓ | `0x454614`：`1.0/[动力总成+0x14]`（倒数质量）；UI `WEIGHT ← -infoBlock[0]`；★ **原版日志字符串坐实**：`">>> Total mass:\t\t"+block[0]+" kg"` |
| 1 | `+0x1c` | 内部质量尺度量 | ? | ✗ | `0x454781`：`[栈+0x8c] × 2e-4`，后被 min/max 反复更新；输入是 `0x4bb760` 取的 vec3 分量 |
| 2 | `+0x48` | **功率** | hp? | ✓ | `0x454c1e`：`[[引擎+0x24d4]+0xfd4][+0x1b0] × [底盘+0x2298]`；UI `POWER ← infoBlock[2]` |
| 3 | `+0x50` | 扭矩类 | ? | 推断 | `0x454c54`：同源 `+0x1ac` × 同一尺度 `[底盘+0x2298]`（与功率同族） |
| 4 | `+0x40` | **极速** | m/s | ✓ | `0x454bf1` 写哨兵 `-1` → `0x454edc` 起 `comiss` 取最大（引擎曲线族极大值）；UI ×3.6 → km/h |
| 5 | `+0x0c` | 前轴荷比例 | 0..1 | ✓ | `0x45463b`：`d_a/(d_a+d_b)`；★ 原版等价实现 `(CM.z − w0.z)/(w2.z − w0.z)`（`Vehicle.updatevariables`）|
| 6 | `+0x10` | 后轴荷比例 | 0..1 | ✓ | `0x454644`：`1 − 槽 5` |
| 7 | `+0x24` | 内部几何量 A | ? | ✗ | `0x4547c0`：`−(前轴荷比·v.x + v.z/[+0x04]) × 4e-4`（v = `0x4bb760` 取的 vec3）|
| 8 | `+0x28` | 内部几何量 B | ? | ✗ | `0x4547d6`：`(v.z/[+0x08] − 后轴荷比·v.x) × 4e-4` |
| 9 | `+0x38` | 轴荷比 | ? | ✓ | `0x454b0b`：`[轮0+0xb8]+[轮1+0xb8]` = **前轴和**、`[轮3+0xb8]+[轮2+0xb8]` = **后轴和**（`0x15e0=0x1528+0xb8` ⇒ 配对算术自证）；`0x454b49` 再按比例分配 |
| 10 | — | 前轴代表轮系数 × 1/质量 | 1/kg? | ✓ | 调用方 `0x4870a1`：`[轮数组+0x58] × (1/质量)`，轮 0 = **前轴代表轮** |
| 11 | — | 后轴代表轮系数 × 1/质量 | 1/kg? | ✓ | 调用方 `0x4870c5`：`[轮数组+0x2aa8]`（= 轮 2 的 `+0x58`）× 1/质量 |
| 12 | `+0x5c` | **0-100 km/h 用时** | s | ✓ | `0x4551f4/0x45520e/0x455215`：累积量 + 门限 `[0x6ed6b8]=27.7778 m/s`（**恰为 100 km/h**）；UI `ACCELERATION ← -infoBlock[12]`（量程 2–20 s） |
| 13 | `+0x4c` | 动力总成原值 A | ? | ✗ | `0x454c35`：`[动力总成+0x1c4]` 原值 |
| 14 | `+0x54` | 动力总成原值 B | ? | ✗ | `0x454c6b`：`[动力总成+0x1c0]` 原值 |
| 15 | `+0x60` | 加速度类量 | m/s²? | 推断 | `0x455485`：`Δ × 1/质量`；仅在 `([+0x2c]+[+0x30]) > 100` 时算，否则置 0 |
| 16 | `+0x64` | **制动减速度** | m/s² | ✓ | `0x45548a`：`Δ × 1/质量`；UI `BRAKING ← -infoBlock[16]`（量程 10–100 m） |
| 17 | `+0x68` | **过弯** | g? | ✓ | `0x455607` `fstp [esi+0x68]`（**x87**）：`(a+b)/(2·f+c)` 比值；UI `CORNERING ← infoBlock[17]`（0.5–5 g） |
| 18 | `+0x6c` | **稳定** | rad/s | ✓ | `0x455689` `fstp [esi+0x6c]`（**x87**）：四轮 `+0x4c/+0x58/+0x64/+0x68` 平均（×`[0x6ecd94]=0.25`）后过 `fptan`；UI ÷π×180 → °/s |

**顺带取回的常量真值**（`.rdata`，本轮解出）：

| VA | 值 | 含义 |
|---|---|---|
| `0x6ec138` | 97.2222 | `350/3.6` = 350 km/h 的 m/s 值（极速上界；与 UI 量程 0–350 km/h 自洽 ✓）|
| `0x6ed6b8` | 27.7778 | `100/3.6` = 100 km/h 门限（槽 12）|
| `0x6ebd94` | 100.0 | 百公里门（槽 15/16）|
| `0x6ec6a0` | 9.5493 | `60/2π` = RPM ↔ rad/s |
| `0x6ecd94` | 0.25 | 四轮平均系数（槽 18）|
| `0x6ec27c` / `0x6ed444` | π/2 / 2/π | 弧度↔度 |
| `0x6e7668` / `0x6e766c` | −1.0 / 1.0 | 极速搜索哨兵 / 单位 |

**两处订正**：
1. `docs/44 §2.4` 把 `0x4BB760` 记为「标志查询」——实测是 **thiscall 的 3-float vec3 取值器**（`push &vec3` 后被调用，
   槽 5/6 的几何量即由它取得）。
2. 本文件上一版把槽 12 记作「疑为 0-100 时间」、槽 16「疑为制动距离」——本轮由**门限常量**与**力/质量量纲**坐实（去掉「疑」）。

### 6.1 轮序、轴荷与「原版自己给的注释」（★ 本轮第二跳）

**轮序 = `FL, FR, RL, RR`（0/1 = 前轴，2/3 = 后轴）**，三条独立证据：

1. **Java 侧属性顺序**：`Vehicle.VPV_TYRE_FL_INFL=16 / FR=17 / RL=18 / RR=19`（`Vehicle.java:48-51`）。
2. **填充器里的轴和配对（算术自证，最硬）**：槽 9 的式子写的是
   `[轮数组+0xb8] + [轮数组+0x15e0]` 与 `[轮数组+0x4030] + [轮数组+0x2b08]`；而
   `0x15e0 = 0x1528 + 0xb8`（轮 1 的同一字段）、`0x4030 = 3×0x1528 + 0xb8`（轮 3）、`0x2b08 = 2×0x1528 + 0xb8`（轮 2）
   ⇒ 两组分别是 **轮0+轮1 = 前轴和** 与 **轮3+轮2 = 后轴和**。
3. **原版自己的用法**：`Vehicle.updatevariables` 用 `getWheelPos(0)` 与 `getWheelPos(2)` 算轴距
   （`(w2.z − w0.z)`）⇒ 轮 0 与轮 2 是前后轴各自的代表轮 —— 而 info block 的槽 10/11 取的**正是轮 0 与轮 2** ✓。

**★ 原版调试日志直接给出了字段语义与单位**（`Vehicle.java:1180-1198`，`if (true)` ⇒ 死代码但在跑）：

```java
local2 = local0.getInfoBlock();
local3 = local2[0];
log(">>> Total mass:\t\t" + local3 + " kg");                    // ⇒ 槽 0 = 总质量 kg（单位由字符串坐实）
local4 = local0.getWheelPos(0); local5 = local0.getWheelPos(2);
log(">>> Wheelbase:\t\t" + (local5.z - local4.z) + " m");       // ⇒ 轴距定义 = (w2.z − w0.z)
local9 = ((cm.z - local4.z) / (local5.z - local4.z)) * local3;   // ⇒ 原版轴荷公式
log(">>> Axle load (front): " + (local3 - local9) + " kg (" + ((1 - local9/local3)*100) + "%)");
log(">>> Axle load (rear):  " + local9 + " kg (" + (local9/local3*100) + "%)");
```

⇒ ① 槽 0 单位 = kg **被原版字符串钉死**；② 槽 5/6 的「前后轴荷比例」有一个**原版参考实现**（重心相对前后轴位置），
重制时照抄即可；③ 这是**唯一的实机对照钩子**：游戏日志里这三行可直接与重制侧的 info block 数值比对。

**消费者只有两个**（`grep getInfoBlock` ⇒ 2 处）：`ProgrBarCommon.refreshSliders`（UI，取 7 槽）与上述调试块。
⇒ **其余 11 槽（1/3/5..11/13/14/15）没有任何 Java 消费者**，是填充器内部的中间量 ⇒ 未命名**不影响**重制。
（槽 2/3 同源 `[[引擎+0x24d4]+0xfd4]` 的 `+0x1b0/+0x1ac`，× 同一尺度 `[底盘+0x2298]`；槽 13/14 = 同一块的
`+0x1c4/+0x1c0` 原值 —— 该块 = **安装的发动机数据块**，✗ 具体字段名未定。）

---

## 7. 未决（✗，纯离线可继续）

| # | 项 | 状态 |
|---|---|---|
| 1 | info block 剩余 5 个 ✗ 槽（1/7/8/13/14） | ✗ **不影响重制**（无 Java 消费者）。槽 1/7/8 的输入 = `0x4bb760` 取的两个 vec3（callee 经 `lea` 指针填充）；追法：`tools/native_frame_locals.py 0x4544a0 0x4556b8 --read 0x454762`（帧内槽图）|
| 2 | 槽 2/3/13/14 所在数据块（`[[引擎+0x24d4]+0xfd4]` = 安装的发动机数据块）的字段名 | ✗ 需查它的写入方（`+0x1ac/+0x1b0/+0x1c0/+0x1c4`）|
| 3 | ~~轮序~~ → **✅ 已闭环**（`FL,FR,RL,RR`；见 §6.1 三证）| — |
| 4 | 表里那 37 个「Model 未声明」的物理槽由谁给位置 | ✗（疑零件侧 `configureType` 或原生）|
| 5 | `linkVirtualSlot` 之外的冲突判定（同一物理槽被两组同时 claim 时谁赢） | ✗ 未找到第二处消费方 |
| 6 | `IVehicle.slotParts[65]` 之外是否还有别的占用账本（`spareParts` 只记拆下的件）| ✗ |
| 7 | `ISticker.placement_` 的取值范围与 37(ROOF) 的来历 | ✗（16+placement_ 只能解释 16–19）|
| 8 | `ISet` 族 `attach` 形参的实际取值（门/内饰共用族的运行时实参） | ✗ 需看具体零件类调用点 |
| 9 | 轮数组 `+0xb8`/`+0x58` 两个字段的物理定义（前者喂轴荷比、后者喂槽 10/11）| ✗ 需读 `[车+0x20a4]` 轮对象的这两槽写入方 |

---

## 8. 产出与校验

| 文件 | 内容 |
|---|---|
| `tools/stat_slots.py` | 提取器：字节码常量 + `fillSLUT` 字节码重建 + 滑块量程 + 24 个基类 `attach` + **info block 逐槽（偏移现算）** |
| `tools/native_frame_trace.py` | **新**：原生 getter 的栈缓冲槽追踪器（跟 push 漂移，解「填充器→返回值」对位）|
| `tools/native_field_writes.py` | **新**：原生填结构函数的字段写入扫描器（含 **x87** 写点 + 浮点常量真值解析）|
| `tools/native_frame_locals.py` | **新**：原生函数的「帧内局部量访问图」（`[esp±X]` 全换算成帧内固定偏移 + 读写方向 + 写点上下文）|
| `out_stats_spec.json` | 机器可读规格（含伪码↔字节码差分：`slot_table_bytecode_vs_pseudo`、`info_block.slots[19]`、`wheel_order`、`consumers`）|
| `remaster/data/stats.json` | 重制数据层（`stats` / `info_block` / `ui` / `slots`，schema `stats.schema.json`）|
| `remaster/tools/validate.py` | 性能 stat + 槽位 + info block 共 **20** 项断言（**61** 项总数全通过）|

复现：
```bash
python tools/stat_slots.py --json out_stats_spec.json --report     # info block 逐槽表在此命令的输出里
python tools/native_frame_trace.py --fn 0x486f20:0x487150         # 槽 → 填充器结构偏移（现算）
python tools/native_field_writes.py 0x4544a0 0x4556b8 --reg esi --slice   # 填充器 54 个字段写点
python tools/native_frame_locals.py 0x4544a0 0x4556b8 --read 0x454762     # 帧内槽图（追某个输入量的写入者）
python remaster/tools/make_schemas.py && python remaster/tools/build.py --only stats
python remaster/tools/validate.py
```
