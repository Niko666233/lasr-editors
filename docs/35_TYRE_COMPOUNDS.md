# 35 · 轮胎配方全表（11 种 × 6 接触面 · Java 数据源实证）

> 数据源：`out_pseudo/java/classes/game/parts/Tyre_*.java`（唯一的抽象基类 `Tyre.java`
> 的 `getRef_pacVars()` 直接 `System.exit("overriden ... not implemented")`
> ⇒ 真身全在子类）。抽取工具：`tools/extract_tyres.py` + `tools/tyre_slots.py`。
> 产物：`out_tyres.json` / `out_tyres.csv` / **`out_tyres_slots.csv`（66 行 × 36 槽，推荐用这份）**
> / `out_tyres_geom.csv`。

## 1. 十一种配方与真实品牌

| 类 | 品牌 | 定位 |
|---|---|---|
| `Tyre_NC` | Pirelli P400 Touring | 民用/旅行 |
| `Tyre_NC_B` | Pirelli P400 Touring "B" version | 同上（B 版） |
| `Tyre_RH` | Yokohama ADVAN | **R**acing **H**ard |
| `Tyre_RM` | Yokohama V102 | **R**acing **M**edium |
| `Tyre_RS` | Kumho ECSTA S700 | **R**acing **S**oft |
| `Tyre_SH` | Bridgestone Potenza | **S**port **H**ard |
| `Tyre_SH_B` | Bridgestone Potenza "B" version | 同上（B 版） |
| `Tyre_SM` | Bridgestone Potenza RE070 | **S**port **M**edium |
| `Tyre_SS` | Bridgestone Potenza RE050A | **S**port **S**oft |
| `Tyre_XD` | BFGoodrich T/A KO | e**X**treme **D**uty（越野） |
| `Tyre_XD_B` | Bridgestone Dueler M/T D673 | 同上（B 版） |

字母编码由品牌名交叉印证（`_B` = 该轮胎的第二个变体；`Rh/Rm/Rs` 与 `Sh/Sm/Ss`
的抓地强弱排序见 §4，与 Hard/Medium/Soft 一致）。

## 2. 几何与弹性参数（`out_tyres_geom.csv`）

| 类 | 宽 | 侧壁 | 轮辋 | 失控角 | 充气 | DeoptRate | 弹簧 | 阻尼 | 胎面密度 | 侧壁密度 |
|---|---|---|---|---|---|---|---|---|---|---|
| NC / NC_B | 205 | 112.75 | 16 | **35.0** | 1.8 | **82.5** | 320000 | 0.011 | 0.69 | 0.79 |
| RH | 225 | 90.0 | 18 | 13.0 | 1.9 | 70.0 | 280000 | 0.015 | 0.77 | 0.89 |
| RM | 225 | 90.0 | 18 | 13.0 | 2.0 | 70.0 | 250000 | 0.010 | 0.88 | 0.96 |
| RS | 225 | 90.0 | 18 | 13.0 | 2.0 | 70.0 | 300000 | 0.010 | 0.76 | 0.90 |
| SH / SH_B | 225 | 90.0 | 18 | 13.0 | 2.0 | 70.0 | **400000** | 0.010 | 0.76 | 0.90 |
| SM | 225 | 101.25 | 17 | 13.0 | 1.9 | 70.0 | 180000 | 0.011 | 0.76 | 0.90 |
| SS | 245 | 110.25 | 17 | 16.0 | 2.0 | 77.0 | **（空）** | **0.050** | 0.76 | 0.90 |
| XD / XD_B | 205 | 133.25 | 14 | **45.0** | 1.6 | 70.0 | 160000 | 0.011 | 0.69 / 0.64 | 0.79 / 0.71 |

★ 侧壁是**表达式**：`Ref_Width × 扁平比 / 100`（55/40/40/40/40/45/45/65 ✓）—— 已在抽取时
代入真值。**`Tyre_SS` 未设 `SpringRate`（全表唯一）**，且阻尼是他人 5 倍 ⇒ 原版遗留，
重制时需自行决定（照搬 / 修正）。

`Tyre.java` 基类里另外两条公式（实机换算）：

```java
// 物理半径
metric(SD_P_METRIC=0)      : r = dims[2]*0.0127 + dims[0]*dims[1]*1e-5
competition(SD_COMPETITION=1): r = dims[1]*0.0005
// 物理质量
metric      : a=dims[0]; b=dims[0]*dims[1]*0.01; c=dims[2]
competition : a=dims[0]; b=(dims[1]-dims[2])/2;  c=dims[2]/25.4   // 英寸→mm
最后 : mass = c * 1.27
```

## 3. ★ 系数映射机制（这一节是复刻的关键）

Java 里的系数表是**紧凑序**，引擎通过索引映射表展开成真正的 Pacejka 变量号
（`PacejkaGlobals.java`）：

```java
pacVarIdxs    = {2,12,0,4,13,11,14,3,17,10,1,6,7,8,18,19}              // 16 项
pacVarIdxs_v2 = {2,12,0,4,13,11,14,3,17,10,1,6,7,8,18,19,15,16}        // 18 项
pacVarIdxs_v3 = {2,12,0,4,13,11,14,3,17,10,1,6,7,8,18,19,15,16,34,35}  // 20 项
common_pacVarIdxs = {15,16,26,24,25,22,23}
common_pacVars    = {1000, 6000, 10.0, 0.0, 0.0, 1.0, 1.0}
```

| 表长 | 用哪张映射 | 出现的配方 |
|---|---|---|
| 20 | `pacVarIdxs_v3` | `NC`, `NC_B`, `SH`, `SH_B` |
| 18 | `pacVarIdxs_v2` | 其余 7 个 |

★ **两条独立判据互证变量总数 = 36**：`v3` 的最大索引是 `35`（⇒ 0..35 共 36 槽），
而 `docs/20` 从 C++ 侧读到的是 `tyre[tyreIdx*36+idx] @ +0x20c`。两条路线各自独立
得到同一个 36。

★ **槽 18 的存储缩放**：`docs/20` 记录 `setPacejka` 有 `if(idx==0x12) v*=0.0001`
（`0x12 = 18`）⇒ Java 表里槽 18 的值（如 `3763.800049`）是**未缩放**的原始值，
引擎侧乘 `1e-4` 得 `0.37638`。重制时按同一规则处理。

★★ **数据通路**：`Tyre_XX.Ref_pacVars[CONTACT_Y] = {…}` →
`PacVals.setpacVals(Y, table)`（`PacVals.java` 的 0..N 分支直接存进 `pacVals_Y`）
→ 原生 `setPacejka`（`docs/20`）。

## 4. ★ 六接触面抓地缩放矩阵（槽 2）

`PacejkaGlobals` 的接触面枚举（**与 `docs/20`、`docs/31` 的路面音频三方一致**）：

```
CONTACT_Asphalt=0  Grass=1  Gravel=2  Hard_Sand=3  Snow=4  Ice=5  Count=6
```

| 类 | 沥青 | 草 | 砾石 | 硬沙 | 雪 | 冰 | 冰/沥青 |
|---|---|---|---|---|---|---|---|
| RS | **2.25** | — | — | — | — | 0.25 | 11% |
| RM | **2.17** | — | — | — | — | 0.17 | 8% |
| RH | 2.00 | — | — | — | — | **0.10** | 5% |
| SS | 1.85 | — | — | — | — | 0.25 | 14% |
| SM | 1.66 | — | — | — | — | 0.16 | 10% |
| SH / SH_B | 1.50 | — | — | — | — | 0.30 | 20% |
| XD_B | 1.40 | — | — | — | — | 0.30 | 21% |
| NC / NC_B | 1.30 | — | — | — | — | 0.30 | 23% |
| XD | 1.20 | — | — | — | — | 0.20 | 17% |

（完整 6 列值见 `out_tyres_slots.csv` 的 v2 列。）

★ **设计规律**：**光头轮胎沥青抓地最强（2.0–2.25）、冰面最惨（5–11%）**；
**民用/越野胎沥青较弱但冰面相对更好** —— 重制时要复刻这条曲线。

★★ **除槽 2 之外是否还有逐面差异**（自动检查结果）：

| 配方 | 逐面变化的槽 |
|---|---|
| 9 种（NC/NC_B/RH/RM/RS/SH/SH_B/SM/SS） | **仅槽 2** |
| **XD / XD_B（越野胎）** | **槽 0、2、11、13、19（5 个）** |

⇒ 越野胎对地面有**多参数响应**，其余是**单一抓地缩放**。这是实打实的手感分野。

## 5. 未闭合 / 待补

- **36 个 Pacejka 槽的物理含义只标定了少数几个**（槽 2 = 接触面抓地缩放；
  槽 18 = ×1e-4 缩放的量；`common` 的 15/16/26/24/25/22/23 沿用 C++ 侧记录）。
  完整语义需对照 `docs/20` 的 `setPacejka` 逐槽笔记补全 —— 这是重制落地前
  必须完成的一步。
- **`Tyre_SS` 缺 `SpringRate`** 以及各轮胎 `Ref_DeoptAngle`（35/13/16/45）的实际
  物理作用（推测＝胎压偏离最佳值后抓地下降的拐点），尚未在 C++ 侧验证。
- Java 数组里 `nameBrand` 的 `"B"` 版本带转义符（抽取时已清理），实际字符串里
  就是 `Pirelli P400 Touring "B" version`。
