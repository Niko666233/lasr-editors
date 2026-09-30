# 21 · AI 与路线（P5-A）

> **架构一句话**：路线的**几何**在 `.spl2` 文本文件里（Java 侧加载），
> AI 的**驾驶逻辑**在原生 `Controller` 类里，Java 的 `Bot` 只负责发**文本命令**。
> 所以：路线数据可以直接抄；AI 行为要靠 29 条命令的参数语义复刻。
> 工具：`tools/spline_dump.py`、`tools/ai_commands.py`；数据：`out_routes.json`、`out_ai_commands.json`

## 1. `.spl2` 路线样条（**纯文本**，不用反二进制）

游戏目录里 70 个（地图 53 + 前段摄像机等），命名即用途：
`Track_00{,_fast,_normal,_slow,_rescue,_shortcut}.spl2`、`Ctf_00.spl2`（抢旗）、
`maps/test/route_NN.spl2`（自由漫游用的 17 条）、`frontend/gamemode/PreRaceCamera_*.spl2`。

**一行 = 一段**，TAB 分列、CRLF 结尾；赛道线 9 列：

| 列 | 内容 | 验证 |
|---|---|---|
| 0 | `x y z` 段起点 | |
| 1 | `x y z` 起点切向 | **\|t\| ≈ 本段长度** |
| 2 | `x y z` 段终点 | **与下一行第 0 列逐位相等（最大差 0.0000）** ✓ |
| 3 | `x y z` 终点切向 | |
| 4 | `wl wr wl' wr'` 起/终点的左、右半宽 | **跨段连续（差 0.0000）** ✓ |
| 5 | `v0 v1` 端点标量 | 与列 4 同样跨段链式相连 ✓ |
| 6 | `0x…` 标志位 | 见下 |
| 7 | 整数 | 出货数据全 0 |
| 8 | `0 0 0 0` | 出货数据全 0 |

**切向的真相（一个容易误判的点）**：段 i 的"终点切向"与段 i+1 的"起点切向"**方向相同但
长度不同** —— 比值恰好等于两段长度之比
（实测 `|t0[i+1]| / |t1[i]| = 33.59/17.61 = 1.907`，而 `len[i+1]/len[i] = 1.907`）。
⇒ 每个节点的切向是**同一个方向、按各自段长缩放**（Catmull-Rom 式），
所以"切向不连续"是假象，别照着做两套切向。

**标志位**（第 6 列）按高 3 位区分路线用途，与文件名一一对应：

| 高 3 位 | 出现于 |
|---|---|
| `0x20000000` / `0x30000000` | `_fast` / `_normal` / `_slow` / `_rescue` |
| `0x40000000` / `0x50000000` / `0x60000000` | `_shortcut` |
| `0` | 基础 `Track_00` / `Ctf_00` / `route_NN` |

低位还有每段属性（如 `0x…2000`、`0x…400`、`0x…0a40`、`0x…0840`），
**按位解释待定**（已列在 `docs/01_ROADMAP.md` §2 B6）。

## 2. 路线查询 API（原生 `java.util.resource.GroundRef`，12 个方法）

| 方法 | 作用 |
|---|---|
| `loadSpline(I,Ljava.lang.String;)I` | 载入一个 `.spl2`，返回 spline id（摄像机用 `31`） |
| `clearSpline(I)V` | 卸载 |
| `getSplineLength(I)F` | 路线总长 |
| `getNearestSpline(LVector3;)I` / `(LVector3;II)I` | 位置 → 最近 spline（AI 定位用） |
| `getSplinePos(IFF)LVector3;` | (id, 沿程参数 t, 横向偏移) → 世界坐标 |
| `getSplineDir(IF)LVector3;` | 该处切向 |
| `getSplineVal(ILVector3;)F` | 位置 → 沿程参数 t |
| `getSplinePerp(ILVector3;)F` | 位置 → 横向偏移量 |
| `getSplineDist(ILVector3;FF)F` | 沿程距离（带范围） |
| **`getSplineWidth(IFF)F`** | 该处宽度（**API 名直接印证了列 4 = 宽度**） |
| `getSplineRake(IF)F` | 该处"倾斜/侧倾"（对应列 5 的标量） |

⇒ 复刻路线只需：**读 `.spl2` → 建同样的 (点, 切向, 宽) 序列 → 实现这 12 个查询**。

## 3. AI 架构：Java 发命令，原生 `Controller` 驾驶

```java
// java.game.Bot.activate()（已从抬升伪码读出）
createNativeInstance(GameRef("system.rpk", 4), GameType("system.rpk", 21), null, "Controller");
setEventMask(GameRef.EVENT_COMMAND);
vehicle.setTransmission(Vehicle.TRANSMISSION_SEMIAUTO);
command("AI_level " + usedAILevel + " 1.0 -1 " + (2.5 - usedAILevel));
command("AI_params2 " + (2-aiLevel) + " " + (100*randomness*k) + " 50.0 "
        + (50*randomness*k) + " 1.0 " + (50*randomness*k) + " 5.0");
vehicle.takeSeat(bot);  command("AI_suspend");
```

* **AI 实体** = 原生 `Controller` 实例，Java 的 `Bot` 是它的"遥控器"；
* 每个 bot 的个性参数：`Bot(name, driver, aiLevel, aggressivity, randomness)`；
* 车手下车/上车、维修都走命令（`Bot.repair()` → `brake` / `start`）；
* `Bot.whatDoYouSay(kind)` 是赛前/赛后**对白系统**（`BOTTALK_REJECT/GOSSIP/TEASER/BOAST/OFFER`），
  含 `$1|`/`$2|` 前缀的多套台词 + 按玩家声望选边（"去别的 pub 找对手"）。

## 4. AI 命令表（29 条，从 exe 派发链机抽，含写入字段）

派发实现 = 一长串 `strcmp(cmd,"AI_xxx")` + 每块自己的 `sscanf`。
提取方式：**用字符串 xref 拿到精确的 `push` 地址**（线性反汇编会失步），
再按地址块反汇编。

| 命令 | 参数格式 | 写入（`Controller` 内偏移） |
|---|---|---|
| `AI_level` | （自定义分词） | 读 `+0x33b8` |
| `AI_params` | `%f %f` | `+0x2f38/0x2f3c/0x2f40/0x2f44` |
| `AI_params2` | `%f ×7` | `+0x3434/0x3458/0x345c/0x3464/0x3468/0x3470/0x3474` |
| `AI_race` | `%f,%f,%f %d` | 常量 `0.5` → `+0x33b8` |
| `AI_BeginRace` | `%f` | `+0x2f8c` |
| `AI_follow` | `%f,%f,%f %d` | |
| `AI_GoToTarget` | `%f,%f,%f %f,%f,%f` | （位置 + YPR ✓ 与 Java 一致） |
| `AI_GoToTraffic` / `AI_GoToTrafficSlow` | — | 跟车流行驶 |
| `AI_RaceSpline` | `%s`（文件名） | |
| `AI_RaceSplineMore` | `%f %f %s` | （cuMax, cuMin, 文件 —— 与 `ComplexSpline` 的调用一致 ✓） |
| `AI_RaceSplineMem` | `%d %d` | |
| `AI_spline` | `%f %s %d` | |
| `AI_ActivateSpline` | `%d` | |
| `AI_SetCatchUp` | `%f ×6` | `+0x3288/0x328c/0x3290/0x3294/0x3298/0x329c` |
| `AI_SetCatchUpSpline` | `%f ×4` | `+0x3440/0x3444/0x3448/0x344c` |
| `AI_SetShortCut` | `%f ×6` | `+0x32a0/0x32a4/0x32a8/0x32ac/0x32b0/0x32b4` |
| `AI_AddOpponent` | `%d %f %f %f` | `+0x3274/0x3278` |
| `AI_ResetOpponents` | `%d` | |
| `AI_SetOpponentParam` / `AI_OpponentXChange` | `%d %d` / — | |
| `AI_CatchUp` / `AI_CP_missed` | `%f` 等 | `+0x2dfc/0x2f8c/0x3270/0x3278/0x3284/0x337a/0x3388` |
| `AI_suspend` / `AI_stop` / `AI_smooth` / `AI_horn` / `AI_maxspeed` / `AI_NightRace` | — / `%f` | `+0x33b8/0x3418` |

**难度模型**（`Bot.activate()`，直接可抄）：

```text
used = aiLevel
if raceSum < 10              used *= aiLevelMul3   (= 0.5)
else:
    if aiLevelMul < 1.0      used *= aiLevelMul    (= 1.1)
    if opponentStatus == 2   used *= aiLevelMul2   (= 1.5)
    elif bot.rank < playerRank
        used *= 1 + (playerRank - rank) / 35
然后 AI_level used 1.0 -1 (2.5-used)；k = max(0, 1-used)
     AI_params2 (2-aiLevel) (100·rand·k) 50 (50·rand·k) 1 (50·rand·k) 5
```

⇒ **"AI 有多强"= 一个标量 + 两个扰动项**，完全是可复刻的公式（不是黑箱）。

## 5. 路线对象与引擎默认（RPAK v2）

`maps/<map>/routes.rpk`（例如 hills 4956 B）是 **RPAK v2 名字表**，定义
`all_grey` + **`route_00` … `route_16`**（每条带 `mesh 0x…` / `texture 0x…` / `shd_*`）
⇒ 路线在场景里是有可见网格的（辅助/装饰）。

`system.rpk`（1532 B）是**引擎全局默认**，包含

* 类型注册：`typ_game_object` / `typ_physics_body` / `typ_render_object` /
  `typ_render_light` / `typ_render_camera` / `typ_physics_constraint` / `typ_physics_particle`；
* 实例类型：`ins_game` / `ins_physics` / `ins_render[_sprite/_text/_horizon/_sound]`；
* 资源类型：`res_mesh` / `res_texture` / `res_sound` / `res_force_fx` / `res_animation` / `res_viewport`；
* **`camera` / `player` / `ground` / `trigger` 各带一段 `ICFG` 文本配置**：
  `shd_center/diru/dirv/vbase/vup`、`type directional`、`diffuse/specular/ambient`、
  `position/direction/range/attenuation`、`lf_glow_color/lf_flare_distance`。

⇒ **这就是之前"属性缺省值从哪来"的答案之一**：引擎级默认写在 `system.rpk` 的 `ICFG` 块里。

## 6. 其它已确认

* `java.game.Navigator` **不是 AI**，是小地图/GPS HUD（`MODE_WHOLEMAP=0/MODE_GPS=1`、
  玩家/对手图标色、按 `scaleX/scaleY` 把世界坐标投到贴图上）；
* `java.game.Driver` = 车手**模型/动画**（8 个 `drivers.crc{man,girl}[N].Main`，
  `MALE=0x10000000` / `FEMALE=0x20000000`）；
* `CheckPoint(pos, ypr, size)`、`Marker`、`Trigger` = 检查点/标记/触发器；
* `Track.java`（2834 行）= 赛道逻辑（起终点、路线贴图与预览图、可视化边界）；
  `MapTrack` = 每图每模式一条赛道实例。

## 7. 重制落地清单

1. 直接读 `out_routes.json`（或解析 `.spl2`）建路线；实现 §2 的 12 个查询函数；
2. 用 §1 的切线规则（**方向共享、长度按段长缩放**）重建样条，别做两套切线；
3. 宽度用列 4 的两个值（左右分开），倾斜用列 5；
4. AI 用状态机复刻：`follow spline` / `goto target` / `follow car` / `catch-up` /
   `shortcut` 五种基本行为 + §4 的参数槽；
5. 难度照 §4 的公式实现（含 `raceSum<10` 的"新手保护"）；
6. 路线类型的六种变体（fast/normal/slow/rescue/shortcut + 基础）按标志位高位区分。

## 8. 未解 / 待办

* 标志位低位的确切含义（`0x2000` / `0x400` / `0x840` / `0xa40` …）；
* `v0/v1`（列 5）与 `getSplineRake` 的物理含义（倾斜角？抓地修正？）；
* `AI_params2` 那 7 个参数各自对应什么驾驶行为（本作里 `Controller` 是原生的，
  要读 `/0x444ee0` 之后的实现才能定名）；
* `AI_SetOpponentParam` / `AI_CatchUp` 的完整参数（自定义分词，未被 sscanf 捕获）；
* `routes.rpk` 的 route_NN → `.spl2` 的绑定关系（`route_00` 是 `maps/test/route_00.spl2`？）。
