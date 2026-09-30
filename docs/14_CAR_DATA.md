# 14 · 车辆数据（车参数全解）

> 状态：✅ **10 台车 / ~1,800 个部件类 / 5,276 个参数全部抽出**，引擎扭矩曲线、调校表、
> 经济数值、兼容件表、贴图路径全部可读
> 工具：`tools/car_params.py`（`--list` / `--dump` / `--engine`）
> 产物：`out_car_params.json`（1.0 MB）、`out_engine_curves.md`（168 行，全部曲线）

## 1. 车参数在哪 —— 从「类里没有」追到「就在这里」

上一阶段（`docs/13_GAME_DATA.md`）确认了车参数**不在** `java.game.item.IVehicle` 的
初始化器里（那里只有 `-1`/`false` 之类的默认值）。追踪路径：

| 步骤 | 判断 | 结果 |
|---|---|---|
| 1 | `java/game/item/vehicles/*.class` 存在吗 | ✗ 不存在 |
| 2 | `vehicles/<车>.rpk` 里有 RSD 块吗 | ✗ 0 个（只有 183 DDS + 115 ISCX + 2 个资源目录 `.bin`） |
| 3 | 全库字符串字面量找目录 | ✓ `vehicles/<车>.rpk`、`Tuning\*.evt`、`DEBUG_CarSetup*` |
| 4 | **`extracted/vehicles/<车>/<body>/classes/classes/*.class`** | ✅ **每车 192 个部件类** |

```
extracted/vehicles/Phoenix_RS_1997/coupe/classes/classes/
    Coupe_RS_IEngine_stock.class     ← 引擎曲线（stock / I / II / III / IV / WB）
    Coupe_RS_IGearbox_stock.class    Coupe_RS_IDiffs_track.class
    Coupe_RS_ITyres_stage_II.class   Coupe_RS_IRims_style_III.class
    Coupe_RS_ITyre_F_ST_stage_IV.class ...
    IVehicle_Coupe_RS.class          ← ★ 整台车的数据记录
```

## 2. 一台车的数据模型

### 2.1 车级类 `IVehicle_<Model>`（整车记录）

以 `IVehicle_Coupe_RS`（Phoenix RS 1997）为例，`<init>` + `<clinit>` 抬升结果：

```java
stylPrestigeMul = 0.6;  perfPrestigeMul = 0.6;      // 声望换算倍率（F）
getPrestige()   { return 350; }                      // 本车基础声望

minPrestige = 3810;   maxPrestige = 8900;            // 生涯解锁区间（I）
perfectTuning = { 24 个可调参数槽引用 };              // 完美调校项
dropTable     = { -1×6, 1,3,0,2,5,4,8,11,7,9,6,10,13,16,15,12,14,17 };
tuningValue   = { 0.15×1, 0.05×1, 0.25×1, 0.10×1, 0.10×1, 0.35×1,
                  0.05×2, 0.10×2, 0.15×2, 0.25×2, 0.35×2, 0.10×2,
                  0.15×3, 0.10×3, 0.10×3, 0.25×3, 0.05×3, 0.35×3,
                  0.10×4, 0.05×4, 0.25×4, 0.15×4, 0.10×4, 0.35×4 };  // [F]
stylingIDs    = { 15 组 int 数组 };                   // 外观件分组（[[I）
paintjobIDs   = { 0, VID_97_Phoenix_RS, VCF_CIRCUIT, VCF_STREET };
```

`tuningValue` 是 **24 项 = 6 项 × 4 个阶段**：每阶段 6 个「调校项目」的花费/权重，
数值 0.05–0.35，随阶段从 `×1.0` 升到 `×4.0` ✓ —— 这是调校经济模型。

`dropTable` 前 6 个是 `-1`（该阶段不可掉落），后 18 个是 0..17 的**排列** ——
掉落表的槽位映射（`docs/13` 的 `BET_TYPE_*` 同一套物品槽语义）。

### 2.2 部件类（`<Body>_<Parts>_<stage>`）

| 方法 | 出现次数 | 含义 |
|---|---|---|
| `getPrestige()I` | 1,091 | 部件声望（经 `roundPrestige(getPrestige() × perfPrestigeMul)` 换算） |
| `staticinit()I` | 690 | 部件自身初始值（多为 0 = 由父类定） |
| `getName()/getLongName()` | 546 / 540 | 显示名（多语言键/字面量） |
| `eRPMs()[F` / `eMuls()[F` | 60 / 60 | **引擎扭矩曲线**（RPM 断点 + 扭矩倍率，点数 2–13，各车各阶段不同） |
| `RPMs()[F` / `Muls()[F` | 50 / 50 | 第二组曲线（变速箱/转速限制） |
| `Rims()/Tyres()[Ljava.lang.String;` | 60 / 60 | 兼容轮圈 / 轮胎**类名表** |
| `getRimDensity()/getSpikeDensity()F` | 72 / 72 | 轮圈/防滑钉密度 |
| `CalculatePhysMass([F)` | 72 | 物理质量计算入口 |
| `getDecalTexture()/getPartDecal()` | 200 | 贴花贴图路径 |
| `getBrandLogoTextureUV()/getModelLogo*` | 20 各 | 车标/车型 logo 贴图与 UV |
| `getDefaultItems()[I` | 20 | 出厂配置件 |

### 2.3 部件的物理/贴图数据（`<init>` 实例字段）

```java
// Coupe_RS_Tyre_F_ST_stock：
Inflation = this.Ref_Inflation;         // 胎压引用（由 Chassis 的 TYRE_*_INFL 提供）
// Model_Coupe_RS 等模型类：
"Phoenix RS"
"vehicles\\Phoenix_RS_1997\\coupe\\textures\\Model_Coupe_RS.png"
"vehicles\\Phoenix_RS_1997\\coupe\\textures\\Model_Coupe_RS_locked.png"
"vehicles.Phoenix_RS_1997.coupe.classes.Model_Coupe_RS"
```

## 3. 引擎扭矩曲线（重制直接要的手感数据）

`eRPMs()` 给转速断点，`eMuls()` 给同长度扭矩倍率（**点数各车各阶段不同，2–13**）。
**Phoenix RS 1997**（13 点）：

```
RPM 断点  0, 1058, 1607, 2035, 2527, 3031, 3546, 4617, 5458, 6000, 6465, 7444, 8950
```

| 阶段 | 扭矩倍率曲线（对应上面 13 个 RPM） | 峰值 |
|---|---|---|
| stock | 0, 129, 158, 184, 255, 296, 305, 303, 298, 291, 266, 229, 113 | 305 |
| I | 13, 154, 188, 236, 284, 311, 317, 319, 314, 307, 292, 252, 168 | 319 |
| II | 13, 162, 204, 254, 297, 323, 329, 335, 334, 330, 322, 276, 193 | 335 |
| III | 14, 167, 210, 261, 306, 332, 348, 359, 363, 359, 360, 309, 216 | 363 |
| IV | 15, 186, 233, 291, 341, 370, 387, 391, 388, 388, 383, 349, 228 | 391 |
| WB | 同 stage IV（宽体版沿用顶阶动力） | 391 |

**全部 10 台车 × 6 个阶段的完整曲线见 `out_engine_curves.md`。** 跨车峰值对照：

| 车 | stock | I | II | III | IV | WB |
|---|---|---|---|---|---|---|
| Phoenix_Trend_1983 | 145 | 170 | 190 | 212 | 244 | 244 |
| Fantasy_Corus_2005 | 153 | 171 | 191 | 207 | 221 | 221 |
| Takura_Cyclone_2004 | 203 | 219 | 247 | 276 | 297 | 297 |
| NSR_Desert_2003 | 249 | 266 | 301 | 338 | 367 | 367 |
| Phoenix_RS_1997 | 305 | 319 | 335 | 363 | 391 | 391 |
| Takura_Tornado_2002 | 320 | 320 | 356 | 366 | 380 | 380 |
| Fantasy_Quaddro_1994 | 348 | 431 | 424 | 448 | 463 | 463 |
| Raptor_ZX_1997 | 378 | 378 | 387 | 419 | 440 | 440 |
| Fujin_MX_2006 | 393 | 408 | 433 | 446 | 455 | 455 |
| Hornet_Wega_2006 | 438 | 445 | 433 | 446 | 455 | 455 |

> 注：`Fantasy_Quaddro_1994` 的 stage I（431）> stage II（424）是**游戏原值**，不是抬升错误
> —— 该车曲线上Ⅱ阶中段更平、峰值略低。

## 4. 新格式发现：整数常量 = 常量池索引 + `0x20000000`

车数据里 `paintjobIDs = {0, 536870938, 536870959, 536870960}` 这种魔数不是随机值：

```
536870938 - 0x20000000 (=536870912) = 26   → 常量池 #26
536870989 - 0x20000000            = 77   → 常量池 #77 = "paintjobIDs"
```

`0x20000000` 正是模拟器里的 `HEAP_BASE` ✓ —— 编译器把**内嵌的类/字段/字符串常量**
编码成「池索引 + HEAP_BASE」。换 `ref_text()` 解引用后，`perfectTuning` 从
「24 个怪数字」变成：

```
{ IVehicle_Coupe_RS.renderClassDescription, VID_97_Phoenix_RS, perfectTuning,
  IVehicle_Coupe_RS.dropTable, ITF_TRACK_SUSP, ITF_STREET_SUSP,
  IVehicle.VHC_PRID, IVehicle_Coupe_RS.tuningValue, minPrestige, maxPrestige, ... }
```

—— **`ITF_*`/`VHC_*` 就是可调校的参数槽位 ID**（与 `IVehicle.VHC_*`、
`Chassis.CF_*` 同一套语义）✓。抬升器已加入自动解引用（`lift_expr.py` `HEAP_BASE`）。

> 残差：约 1/4 的引用仍显示 `<bad ref N>`（池条目是 tag5 方法引用时 `ref_text`
> 只能给出属主），机制已确认，属显示层问题，不影响数值。

## 5. 数组操作码的真实操作数顺序（两个真 bug）

原实现（JVM 惯例）假定 `ARRAY_STORE` 是 `(数组, 下标, 值)`、`ARRAY_ACCESS` 是 `(数组, 下标)`。
实测本 VM **相反**：

```
16 INT LITERAL 0        ← 下标先压
21 LOCAL_LOAD 0         ← 数组在上
26 INT LITERAL 1058
31 I2F                  ← 值最后
32 ARRAY_STORE
```

即 `ARRAY_STORE` 弹出 `(值, 数组, 下标)`、`ARRAY_ACCESS` 弹出 `(数组, 下标)` 且**数组在上**。
修前渲染出 `0[local0] = 0.0`（下标当数组）和 `idx[arr]`，修后
`local0[0] = 0.0`、`this.opponentBets[0].getBetType() == BET_TYPE_IVehicle` ✓。

**这两个 bug 栈高度完全看不出来**（弹几个压几个都一样），只有类型/语义判据能抓 ——
和上一轮 `ARRAY_INIT` 元素切片那个 bug 同类。

## 6. 复现

```bash
python tools/lift_expr.py --class extracted/vehicles/Phoenix_RS_1997/coupe/classes/classes/IVehicle_Coupe_RS.class
python tools/car_params.py --list      # 参数名出现次数
python tools/car_params.py --dump      # -> out_car_params.json
python tools/car_params.py --engine    # 逐车曲线
```

## 7. 待办

* **`IVehicle_Coupe_RS` 等车级类由谁实例化**：全库 0 处直接引用 → 走 **名字约定**
  （`vehicles.<Car>_<Year>.<body>.classes.IVehicle_<Model>`），入口在 `IVehicleArray`
  注册流程（`docs/13` 的 `VID_*` 表）。
* 约 1/4 池引用显示为 `<bad ref>`（tag5 属主渲染），不影响数值。
* `RPMs()/Muls()`（50 处）第二组曲线的语义（变速箱？限转？）未定。
* `CalculatePhysMass([F)` 的质量公式未展开（需读非直线方法 → P2.7b）。
