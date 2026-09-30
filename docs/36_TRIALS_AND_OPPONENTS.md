# 36 · 对手花名册 / 驾驶学院 / 地图清单（Java 规则数据实证）

> 数据源：`out_pseudo/java/classes/game/Gamelogic.java` 与 `MapTrack.java`。
> 这三张表是「游戏规则」层最核心的数据 —— 全部从伪码直接读出，无推测。
> 产物：**`out_opponents.csv`（60 行）**、**`out_trials.csv`（30 行）**。

## 1. ★ 地图清单（10 张）

从 `trials` 表的地图 ID 表达式与 `MapTrack.mapper` 交叉得到：

```
MID_Harbor  MID_Boulevard  MID_Suburban   MID_Coastline  MID_Industrial
MID_Highway MID_Hills      MID_Business   MID_Urban      MID_Observatory
```

`MapTrack.mapper`（32 项，取值仅 {0,1,2}）：
```
0,0,0,0,1,1,1,1,1,2,1,1,1,2,2,0,2,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0
```
（32 = 索引空间上界，实测只用到前 17 项 ⇒ 具体映射语义**未验证** ✗）

## 2. ★ 驾驶学院 30 关（`out_trials.csv`）

```
new java.game.Trial( (MAP_PRID<<TYPE_SHFT)|(MID_xx<<MAP_SHFT), 目标秒数, p1, p2, "$键|关卡名" )
```

| 地图 | 3 关的目标秒数 |
|---|---|
| Harbor | 20.0 / 19.8 / 29.5 |
| Boulevard | 21.5 / 34.0 / 31.8 |
| Suburban | 26.5 / 26.0 / 35.5 |
| Coastline | 24.0 / … |

前几关与末几关（完整 30 行见 CSV）：

| 地图 | 目标秒 | p1 | p2 | 键 | 关卡名 |
|---|---|---|---|---|---|
| Harbor | 20.0 | 2 | 3 | $201 | Slowing down for a low-speed corner |
| Harbor | 19.799999 | 3 | 0 | $202 | Delicate gas work |
| Harbor | 29.5 | 4 | 1 | $203 | High speed shortcut |
| Boulevard | 21.5 | 2 | 3 | $204 | Consequences of overspeeding |
| Boulevard | 34.0 | 4 | 1 | $205 | Gather the most momentum |
| Boulevard | 31.799999 | 1 | 3 | $206 | Avoid the poles |
| Suburban | 26.5 | 0 | 2 | $207 | Uphill @ full throttle |
| Suburban | 26.0 | 2 | 0 | $208 | Slowing down from high speeds |
| Suburban | 35.5 | 1 | 0 | $209 | Understeering high speed turns |
| Coastline | 24.0 | 0 | 1 | $210 | Some top speed turns |
| … | | | | | |
| Urban | 37.0 | 4 | 1 | $227 | Pedal to the metal |
| Observatory | 25.0 | 0 | 1 | $228 | First sector |
| Observatory | 13.5 | 1 | 2 | $229 | Second sector |
| Observatory | 15.5 | 2 | 0 | $230 | Third sector |

- 字符串键 **`$201`–`$230` 连续 30 个** ⇒ 与关卡**一一对应**（可用于定位本地化表）。
- 目标秒数范围 **13.5 – 62.0**。
- `p1 ∈ 0..4`、`p2 ∈ 0..3` —— **语义未验证** ✗（推测为检查点/出生点索引或车辆/天气档，
  需对照 `Track`/`Trial` 的构造或运行时值确认）。

## 3. ★ 60 名对手花名册（`out_opponents.csv`）

```
new java.game.Bot.<init>( "名字", 车手模型, 技术值, 种子, 勇气, 金钱, 性别, 名次 )
```

| 字段 | 实测规律 |
|---|---|
| 名字 | 60 个具名对手（Matt Peacock … Colonel） |
| 车手模型 | `manDriver` / `manDriver2..4` / `girlDriver` / `girlDriver2..4`（8 种；男 36 / 女 24） |
| 技术值 | **精确等差：`(60 − rank) / 60`**（1.0 → 0.0，如 0.983333 = 59/60） |
| 种子 | 每人一个 `±1` 内的小数（如 0.941713 / −0.789965）—— 个性/随机化用 |
| 勇气 | **11 档离散：0.0, 0.1, …, 1.0**（每 5–6 人一档，随名次递增） |
| 金钱 | **10000 → 250 递减**（10000/9600/9200/8850/8500/8150/7800/7450/…） |
| 性别 | 0 = 男（36 人）/ 1 = 女（24 人） |
| 名次 | **1–60，60 个唯一值**（无重复、无缺号） |

⇒ 重制时这 60 条就是现成的**对手难度曲线**：难度＝名次线性，
金钱＝另一条递减曲线，勇气＝阶梯函数。**三条曲线互不同步**，是原版的设计特征。
