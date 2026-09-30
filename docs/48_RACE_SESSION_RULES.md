# 48 · 一局比赛的会话规则（Race / Trial 模式规格）

> 目标：把「一局比赛怎么跑」写成可不看原码直接实现的规格。**这是 47 份文档里此前零覆盖的一层**
> （`game/GameMode` `GmRace` `GmTrial` `Track` `Gamelogic` 的会话部分）。
> 证据全部来自 `out_pseudo/java/classes/...`（伪码逐字 + 行号），原生侧另有 `docs/44`–`47`。
> 标注约定：**✓** = 本轮已回原文复核过引用行；**✗** = 未解；**推断** = 由形状推得，非逐字证据。

---

## 0. 读伪码的两条硬规则（不看会读错全部结论）

### 0.1 ★★★ 形参在伪码里是**逆序**编号的

**规则**：方法第 *k* 个形参 → 名字 `local_(n+1-k)`（n = 形参数）；`local0` = `this`（实例方法）。

**判据（本轮决定性复核，非推断）** —— `GmRace.addTrigger(Ljava.game.Trigger;Ljava.lang.String;)`（GmRace.java:416–419）：

```
417|this.trigger.addElement(local2);
418|local0.addNotification(local2, EVENT_TRIGGER_ON, EVENT_SAME, null, local1);
419|return local2;
```
签名是 `(Trigger, String)`。若 `local1`=第 1 参（Trigger）、`local2`=第 2 参（String），则
`this.trigger.addElement(String)` ✗、`addNotification(String, …, Trigger)` ✗（`addNotification` 第 5 参必须是处理器名串），**两条都不成立**；
只有 `local1` = String、`local2` = Trigger 才使两条都成立 ⇒ **`local1` 是最后一个形参** ✓

> **推论**：`GameMode.canRespawn(F I Vector3 I)`（GameMode.java:660）里 `local1` 被当 spline 索引、
> `local2` 被当 `Vector3`、`local3` 当槽位、`local4` 当浮点 —— 这不是「签名与代码矛盾」，
> 而是**同一个规则**；签名可以放心照抄。旧轮次与子分析里报的「签名 vs 函数体冲突」在此一并撤销。
> 例外：`CheckPoint.java`（4 行，构造里 `this.pori = new Pori(local3, local2); this.size = local1;`）
> 只有按此规则才与调用点 `new CheckPoint(Vector3 pos, Ypr ori, Vector3 size)`（Navigator.java:31 等）自洽 ✓

### 0.2 ⚠ 结构化重建会（a）吞掉 `break`、（b）留下空块

- 凡「命中分支不改变循环变量」的 `while`，按字面即死循环（`GmRace.java:122–128`、`439–460`、`1120–1126`、
  `GmTrial.java:76–87`、`GameMode.java:164–170`）—— 原码几乎必然有 `break`，**不要照字面读**。
- 空块（如 `GameMode.java:675`、`GmRace.java:520–522`）意味着**该分支体的语句被丢了**，
  不能据此断言「原码什么也不做」。
- **可靠的部分**：方法签名/常量/字段/顺序/公式的形状；**不可靠的部分**：循环出口、局部变量身份。

---

## 1. 一局比赛的总流程（Java 侧，全部实测）

```
前端                                 Gamelogic                                GameMode / 子类
─────────────                        ──────────                               ───────────────
mainMenu.quickRace_onAction    →  quickRaceInit() 建 challenge
PubWindow 接受挑战             →  challenge = betPopup.getChallenge()
trialChallengePopup            →  createTrial(i)  (weHaveATrial = true)
                                      ↓
                                 changeStatus(GST_INGAME)         →  status=7; setMusicSet();
                                      └ enterRace(challenge)          GameModes…
                                           ├ 设房间参数 / 洗牌发车顺序 startOrder[8]
                                           ├ gameMode = weHaveATrial ? GmTrial : GmRace
                                           ├ player.changeVehicle(挑战指定车)
                                           ├ new Track(map, trackIdx)
                                           └ changeScreen(new GameWindow(track));
                                             track.enter(win, viewport)
                                                  ↓
                                             GameMode.initGameMode(track)
                                               ├ 注册碰撞/横幅/INFO 通知（见 §7）
                                               ├ point(cp) 逐检查点建原生触发器
                                               ├ reset() 建 racerStats/名次链
                                               └ before321Go() 预载倒计时音
                                                  ↓
                                             prepare() → waitToStart(-3/-2/-1) → start()
                                                  ↓
                                             run() 线程（50ms 轮询）→ handleCP → handleLapTime
                                                  ↓
                                             handleRaceTime() → finish() → ResultsWindow
                                                  ↓
                                 changeStatus(GST_MENU)  →  challenge.apply(胜/负) + save()
```
**注意**：`GST_INGAME` 的进入有**两条路** —— 正常的 `changeStatus` 与网络路径 `Gamelogic.enterRace(challenge)`
直接调用（Gamelogic.java:641，`ROOM_PARAM_status==0` 时），后者**不置 status，也不触发退出结算钩子**。

---

## 2. 模式的静态属性表（逐字，✓ 全部回原文复核）

| 项 | `GameMode`（基类） | `GmRace`（街道赛） | `GmTrial`（试驾/挑战） |
|---|---|---|---|
| `getId()` | `0`（GameMode.java:77） | **`2`**（GmRace.java:46）✓ | **`3`**（GmTrial.java:37）✓ |
| `damageFactor` | `0.5`（:11）✓ | `0.3`（GmRace.java:41）✓ | `0.3`（GmTrial.java:32）✓ |
| `getPropertyFlags()` | `0`（:99，字面量） | 未覆写 | 未覆写 |
| `getCheckPointMissedSplineval()` | `-1.0`（:102） | `racerStats[localUserSlot].checkpointMissedSplineval`（GmRace.java:977） | `racerStats[…].checkpointMissedSplineval`（GmTrial.java:333） |
| `getDefaultParameters()[I` | 空数组 `new int[0]`（:105） | `{player.getLastTrack(), player.getLastLaps()}`（GmRace.java:49） | 未覆写 |
| `respawnAllowed(Racer)` | `true`（:117） | 未覆写 ⇒ **可救援** | **`false`**（GmTrial.java:28）⇒ 禁救援 |
| `repairAllowed(Racer)` | = `respawnAllowed`（:114） | 同上 | 同上 |
| 结果表示 | `finishCall` / `resultWin` | 名次 `racerStats[i].racePos == 1` ⇒ 夺冠 | `success` + `result`（1/0/−1） |
| 圈数来源 | — | `Gamelogic.laps`（`enterRace` 写）或参数数组[1] | 无圈概念，改为「检查点进度」 |

**`PF_*` 属性位**（GameMode.java:22–32，全表）：
`PF_JOINLIVEROOM=1` `PF_OWNERLEAVEGAME=2` `PF_LEAVEGAME=4` `PF_REJOINLIVEROOM=8` `PF_CHANGECARLIVE=16`
`PF_32PLSUPPORT=32` `PF_8PLSUPPORT=64` **`PF_OMIT321GO=128`** `PF_GPSMINIMAP=256` **`PF_NOBREAKIFFINISH=512`**
`PF_NOMINIMAP=1024`。
**基类 `getPropertyFlags()` 返回 0**，子类都没覆写 ⇒ 现有两种模式下 512 位**永远不生效**（`finish()` 的
「冲线后自动刹车演出」按 `(flags & 512) == 0` 判定，恒真）。✓

**会话参数（真正被写回的全局量）**：`Gamelogic.laps`（圈数，`enterRace`:940 读房间参数 `ROOM_PARAM_LAP`）、
`quickMap` / `quickCar` / `serverName` / `serverLocation` / `maxUsers` / `collisionMode`
（`game/frontend/raceParams` 建房窗口写，范围：圈数 **1..99**、人数 **1..8**、地区 6 选 1）。

**`GameMode.canRespawn` 的语义**（GameMode.java:660–682）：遍历 32 槽，排除空槽与自身，
**任一对手车距候选点 < `8.0` 就返回 0（不许重生）**；`(getSplineVal(idx, playaPos) − 候选样条值) * forwardSplineVal < 0`
的方向判据在**空块里（被丢）**⇒ 本版实际只看 8 米距离。⚠ `playaPos` 是单一复用字段，无车槽位会沿用上一个坐标。

---

## 3. 会话状态机（`Gamelogic.status`）

**状态枚举**（Gamelogic.java:2–13，✓）：
`GST_INIT=-2` `GST_SHUTDOWN=-1` `GST_START=0` `GST_USERLOGIN=1` `GST_USERINIT=2` `GST_SERVERLOGIN=3`
`GST_MENU=4` `GST_LOBBY=5` `GST_ROOM=6` `GST_INGAME=7` `GST_PUB=8` `GST_SETTINGS=10`（**无 9**）。

**`changeStatus(int)` 的两条硬规则**（Gamelogic.java:775–893）：
1. `status == 新状态` ⇒ **整个方法 no-op**（:777 守卫）。
2. 退出 `GST_INGAME` 的结算钩子（:778–788）在 `status = 新状态` **之前**执行：
   `player.getVehicle().repair()` → 若 `SINGLE && challenge != null && !isQuickRace`：
   `races.lastElement()` → `challenge.apply(是否夺冠)` → `save("save/career/00N.sav")` → `isQuickRace = false`。

**每个状态的副作用（:791 起的 switch，实测）**

| 目标 | 副作用 |
|---|---|
| `GST_START (0)` | `changeScreen(new StartWindow())`；单机首启播片头 FMV（`showLogos`）；`addDefaultItems()`；按 runMode 初始化（DEMO/GUITEST 用硬服务器，`MetaServer.connect(quickIP, quickUser)`） |
| `GST_SETTINGS (10)` | 开 StartWindow + `IngameOptionsWindow`，**随即嵌套 `changeStatus(GST_SHUTDOWN)`** |
| `GST_LOBBY (5)` | `serverInfo != null` ⇒ 组 `quickIP`、`runMode=DEMO`、`changeStatus(GST_START)`；否则 `changeStatus(GST_MENU)` |
| `GST_ROOM (6)` | **空分支** |
| `GST_MENU (4)` | 清 trial 标记；必要时 `Network.Leave()`/`MetaServer.disconnect()`；联网态回落 `runMode=SINGLE`、重连软服务器；`pub.backToGarage()` |
| `GST_PUB (8)` | 卸 frontend 贴图；`pub.enter()` |
| `GST_INGAME (7)` | **`enterRace(challenge)`** |
| `GST_SHUTDOWN (-1)` | `changeScreen(null)`、`Config.save()`、`System.exit()` |

**合法转移（调用点实测）**：`INIT→SETTINGS`(360–363)、`INIT→START`(394)、`START→MENU`(510)、
`START→INGAME`(514 TEST / 517 DEMO / 521 MULTI)、`START→LOBBY`(524)、`START→SHUTDOWN`(502/765)、
`LOBBY→START|MENU`(851/853)、`MENU→PUB`(mainMenu:280/687)、`MENU→INGAME`(mainMenu:212)、`MENU→LOBBY`、`MENU→SHUTDOWN`(1113)、
`PUB→INGAME`(PubWindow:631、trialChallengePopup:101)、`PUB→MENU`(PubWindow:215/655)、
`INGAME→MENU`(Track:1083/1089)、`INGAME→ROOM`(Track:2192/2241)、`SETTINGS→SHUTDOWN`(841)、
`任意→PUB|MENU`(Gamelogic:549，服务器 `ROOM_PARAM_USER_Logout==1` 回报时，按 `pub.isInPub()` 二选一)。
⚠ `GST_USERLOGIN/USERINIT/SERVERLOGIN` **在本版从未作为转移目标**（只被 `Init.java:89/105` 当区间用）。
⚠ `Gamelogic.java:461–462` 的 `changeStatus(GST_INGAME)` 在 `if (false)` 里 = 死代码。

**`enterRace(Challenge)` 关键分支（Gamelogic.java:895–1015）**：
- `runMode == TEST` ⇒ 强制 `ROOM_PARAM_LAP = 9`（:899–901）；
- `runMode == DEMO && 房间 status != 0 && (ROOM_PARAM_AutoInGame & 4) == 0` ⇒ `joinMode = 1`（中途加入/观战，:904–911）；
- **`ROOM_PARAM_status == 0`（大厅）时整个开赛体不执行**（:928 的 `!` 守卫）；
- `SINGLE` ⇒ 把发车顺序 `startOrder[0..7]` 用 `{0..7}` 洗牌 `local2*3` 次（:943–961）；其它模式走 `NormalizeStartOrder()`（:962–964）；
- 建 `gameMode`（:973–977）→ 切车（:978–985）→ 选地图（`getIndexById(listMaps(), ROOM_PARAM_map)`，找不到取最后一个；TEST 用 `quickMap`，:986–994）→ `makeCompatible(trackFlags)`（:998）→ `new Track(map, trackIdx)`（:1005）→ `cockPitCamOnly(ROOM_PARAM_Flags & ROOMFLAGS_COCKPIT_ONLY)`（:1006）→ `new GameWindow(track)` + `changeScreen` + `track.enter(win, viewport)`（:1007–1009）。

---

## 4. 单局生命周期（逐字时序，✓）

### 4.1 起跑倒计时
| 时刻 | 动作 | 证据 |
|---|---|---|
| `prepare()` 末尾 | `last_time = track.getRaceTime()`（此时为负） | GameMode.java:529 |
| `track.getRaceTime()` 跨 `-3.0` | `saythree.play()` + HUD 大写字幕 `THREE` | :533–535 |
| 跨 `-2.0` | `saytwo` + `TWO` | :537–539 |
| 跨 `-1.0` | `sayone` + **`track.defaultCam()`** + `ONE` | :541–545 |
| `start()` | `status = ST_RUNNING`；`setMessage(GO)`（`joinMode != 1` 才显示）；`saygo.play()` 无条件；玩家车 `command("start")` | :553, 561–569 |
| 音效资源 | `Count\One.evt` / `Two` / `Three` / `Go`（2D 音源），`before321Go()` 里按 three→two→one→go 顺序 `precache()` | :33–36, 448–452 |
| 重开 | 3 段 `sleep(1000, Thread.PHYSICS_TIME)`，起跑时刻 `track.setStartTime(simTime() + 0.3)` | GmRace.java:1476–1494 |

`GameMode` 常量：`ST_SETUP=0` `ST_COUNTDOWN=1` `ST_RUNNING=2` `ST_FINISHED=3`（:18–21）；
`STOP_IN_N_SECS_PLEASE = 5.0`（:37 = GmRace.java:10）。
`prepare()` 还做：清 `finishCall`；记 `player.xpBeforeRace = MetaServer.getUserParameterI(USER_PARAM_0, USER_PARAM_XP)`；
对每辆非玩家车 `command("idle")` 并挂**小地图 Marker**（`getIconFor(racer)` + `nav.addMarker`）；`nav.update()`；
非联网 ⇒ `track.defaultCam()`（:491–530）。

### 4.2 `run()` 主循环（50 ms；主检查每 4 tick ≈ 200 ms）
`GmRace.run()`（:1061–1289）/`GmTrial.run()`（:393–427）共同骨架：
1. 硝基震屏：`nitroInUse && !nitroInEnd && now − last > 0.1` ⇒ `track.shakeCam()`；`nitroInEnd` ⇒ `shakeCamStop()`；
2. 玩家在赛道走廊内判定：`perp = |map.getSplinePerp(spl, pos)|`，`width = map.getSplineWidth(spl, val, perp)`；
   `perp > width` 即**刚脱线** ⇒ `onSpline = false`、`raceChron.addSplineLeft()`；回到廊内 ⇒ `onSpline = true`；
   脱线期间持续 `raceChron.setOffSplineTime(now − lastSplineLeft)`（记**最长**脱线）；
   在廊内则不断刷新 `lastSafePos`（救援/样条查询的锚点）；
3. `raceTime = simTime() − getStartTime()`（未 `finish` 时），HUD `setCurrentTime`（已完赛显示 `finalTime`）；
4. `sleep(50)`；`lastSplineVal` 只在 `|Δval| < 80.0` 或 `> 段长 − 80.0` 时刷新（跨段接缝保护，常量 `80.0`）；
5. 每 4 tick：**漏点/逆行检测**（见 §8.2）+ 全车 `checkTakeover()` + 玩家前后车 HUD（`+x.xx"` / `-x.xx"`，仅 ≤60 s 才显示差值文字，`guessDiffTime`）。

### 4.3 `GmRace.reset()`（:381–402）—— 名次链的构造
```
recordStats = new RacerStats(); recordStats.reset(checkpoints.size());      // 存档最佳圈（room param / 1000.0）
raceStats   = new RacerStats(); raceStats.reset(size);                      // 本场最佳
racerStats  = new RacerStats[Racers.length];
逐车: new RacerStats(); reset(size); .index = i; .pos = i+1; .prev = i−1; .next = i+1;
racerStats[0].prev = -1;  racerStats[len-1].next = -1;  leader = 0;
```
⇒ **起跑名次 = 数组下标 + 1**；`racerStats` 是一条**按名次排序的双向链**（`prev/next` = 数组下标）。

---

## 5. 检查点与触发点（重制的关键机械）

### 5.1 数据
- `CheckPoint(Vector3 pos, Ypr ori, Vector3 size)`（CheckPoint.java:2–3）→ 字段 `pori`（位置+朝向）、`size`、
  `trigger`、`splineval`。**`size` 是门盒的三轴尺寸**：地图数据里常见 `(25.0, 7.5, 0.25)`
  （x 变化最大 = 门宽，y 恒 7.5 = 门高，z 恒 0.25 = 门厚），来源 `maps/*/classes/classes/*_track_0.java`。
- `Trigger` 有 4 个构造（Trigger.java:8/11/14/18）：
  * `(GameRef world, Vector3 pos, float radius, String handler)` → 描述串 `"x,y,z,0,0,0,sphere,<r>"`
  * `(GameRef, Vector3 pos, Ypr ori, float, float, float, String)` → **体为空**（地图 banner 用这个重载，19 处），
    三 float 推断为 size.xyz（**推断**）
  * `(GameRef, Vector3, Ypr, Vector3, float, float, float, String)` → 体为空，**全库无调用点**
  * `(GameRef world, Vector3 pos, Ypr ori, Vector3 size, String handler)` → **检查点用这个**（Trigger.java:18）：
    描述串 `"x,y,z,y,p,r,box,sx,sy,sz"` 交给原生 `new GameType("system.rpk", 52)`；`Config.showTriggers` 非假时
    另建 `frontend.rpk` 260/261 的调试盒渲染色。
  ⇒ **触发体是原生对象（system.rpk type 52），命中判定在引擎里**；Java 只收事件。

### 5.2 注册与命中链（全实测）
```
point(cp)                                   GmRace.java:405-410 / GmTrial.java:195-200
  checkpoints.addElement(cp)
  cp.trigger = addTrigger(cp.pori.getPos(), cp.pori.getOri(), cp.size, null,
                          "event_handlerTrigger", "checkpoint_trigger")
  if (track_length > 0) cp.splineval = map.getSplineVal(0, cp.pori.getPos())     // ★ 恒定用 route 0
addTrigger(Trigger t, String handler)        GmRace.java:416-419
  trigger.addElement(t); addNotification(t, EVENT_TRIGGER_ON, EVENT_SAME, null, handler)
        ↓ 引擎回调（名字 = 注册时给的字符串）
event_handlerTrigger(ref, EVENT_TRIGGER_ON, 事件串)         GmRace.java:432-461
  carId = 事件串.token(0).int; 按 Racers[i].getVehicle().id() == carId 找下标
  用触发体 id 反查检查点下标 → gameEventID++ →
  MetaServer.sendEventInspector_CarTrigger(gameEventID, simTime − getStartTime(), cpIdx, metaLevel)
  本地压入 InspectorEvent{type=1, pl_ml=metaLevel, cp_id=cpIdx}
        ↓ inspector 回发 MES_TYPE_RoomMessageFromInspector(RE_carTriggerOn)
handleMetaEvent: 取 args{时间 f, cpID i, metaLevel i} → processTrigger(metaLevel, cpID, 时间)
  并删除刚压入的 insp_events 条目
        ↓
processTrigger(metaLevel, cpIdx, t)          GmRace.java:466-485 / GmTrial.java:256-258
  if (racerStats[i].raceTime == 0 && cpIdx == racerStats[i].nextCP) handleCP(t, i)
```
**⇒ 过点判定 = 「压到的触发器下标 == 该车的 `nextCP`」，否则这次触发被完全忽略。**
`raceTime == 0` = 「该车未完赛」的哨兵（同时用于 :479/547/556/701/1161/1243/1260）。

### 5.3 `handleCP(t, 车下标)`（GmRace.java:501–541）—— 每次有效过点
```
lastSplineVal = getCurrentSplineVal()
if (玩家 && racerStats[i].racePos <= 0 && !已完赛) finalTime = t
if (玩家 && nextCP != 0):
      cleanSector ? (HUD "CLEAN_SECTOR" + giveNitro(+1.0)) : (cleanSector = true)      // CLEAN_SECTOR_NITRO_GAIN
racerStats[i].checkpointMissedSplineval = -1
racerStats[i].lastCPtime = t
段用时 = t − racerStats[i].lapStartTime
标志 flag = (racerStats[i].prev 存在且 Racers[prev] 是玩家) ? 2 : 0
if (nextCP == 0) → handleLapTime(t, 段用时, i, flag); lapStartTime = t      // 完成一圈
else             → handleSplitTime(t, 段用时, i, flag);
                   lastsplitTimes[nextCP] = 段用时; 当前 LapStats.splitTimes[nextCP] = 段用时;
                   nextCP = (nextCP + 1) % checkpoints.size();              // ←:534-535 逐字为乱码，按 :740-741 同构式还原（推断）
                   distance = distance_min = 10000.0
```
⚠ `flag` 只产生 `2/0`，而 `handleSplitTime/handleLapTime` 只在 `flag == 1` 时更新 HUD
⇒ **「1」的来处在被丢空的分支体里**（:520–522）—— 未解，不影响计时数值本身。

### 5.4 一圈 = 检查点 0 是起终点线
`RacerStats.start(0)`（RacerStats.java:29–38）置 `nextCP = 1`、`laps = 0`、`lapStartTime = 0`；
过线后 `nextCP = 1`（GmRace.java:740）⇒ **一圈顺序：1 → 2 → … → N−1 → 0（起终点线）**，`nextCP == 0` 即完成一圈。

---

## 6. 计时·分段·名次（公式全摘）

### 6.1 `RacerStats`（RacerStats.java，逐字 ✓）
`reset(int cpCount)`：`splits = cpCount`；`score = -1`；`laps = 0`；`pos = 0`；`bestPos = 0`；`racePos = -1`；
`nextCP = 0`；`splineval = 0.0`；**`distance = distance_min = 10000.0`**；`lastCPtime = 0.0`；`penaltyTime = 0.0`；
`bestLapTime = 0.0`；`lastLapTime = 0.0`；`raceTime = 0.0`；`diffTime = 0.0`；
`bestsplitTimes = new float[splits]`；`lastsplitTimes = new float[splits]`；`checkpointMissedSplineval = -1.0`。
`start(0)`：`lapStartTime = 0`、`laps = 0`、`nextCP = 1`，并 push 一个 `LapStats{lapNum=0, startTime=0, splitTimes=new float[splits]}`。
`start(1)`：`lapStartTime = 99999.898438`、`laps = -1`、`nextCP = 0`（**99999.9 = 「无穷大」哨兵**）。
`storeBestLap(other)`：`bestLapTime = other.lastLapTime`，并把 `lastsplitTimes[]` 整段抄进 `bestsplitTimes[]`。
`LapStats{lapNum, startTime, lapTime, splitTimes[]}`（LapStats.java:1–21，copy() 逐字段复制）。

### 6.2 分段 `handleSplitTime(绝对t, 段用时, 车下标, flag)`（GmRace.java:681–706）
`checkTakeover(racerStats[i])` → `refreshDiffTime(racerStats[i])`；
`flag == 1 && 段用时 >= 0` 时：若 `cpMissed` 则清除提示（`NONE` + `cpMissedMarker.setPos(nav, null)`）；
与 `raceStats.bestsplitTimes[nextCP]` 比较 ⇒ `hudinterface.setRaceSplitDiffTime(差)`（基准为 0 时显示 0.0）；
最后（非玩家/已完赛则提前 return）`setSplitTime(段用时)`。

### 6.3 一圈 `handleLapTime(绝对t, 圈用时, 车下标, flag)`（GmRace.java:709–777）
- 玩家过线：`lapsound.play()`；若**不是最后一圈**（`laps + 1 < 总圈数`）：
  `cleanLap` ⇒ HUD `CLEAN_LAP` + **`giveNitro(+5.0)`**（`CLEAN_LAP_NITRO_GAIN`）+ `cleanSector = true`；
  否则 `cleanLap = true`，且若 `nextCP == 0 && cleanSector` 补发 `CLEAN_SECTOR`(+1.0)。
- `圈用时 >= 0` 时：`lastsplitTimes[0] = 圈用时`；`lastLapTime = 圈用时`；末位 `LapStats.splitTimes[N-1] = 圈用时`、`.lapTime = 圈用时`；
  **`laps++`；`nextCP = 1`**（≥ N 则回 0）；`distance = distance_min = 10000.0`；HUD `setLastLap`；
  三处最佳圈比较（均「基准为 0 或 基准 > 本圈」才更新）：`recordStats`（存档，`setRecordBestLap` + `storeBestLap`）、
  `raceStats`（本场，`setRaceBestLap`）、`racerStats[i]`（该车，`setOwnBestLap`）；
  `flag == 1 && laps == 总圈数 − 1` ⇒ **最后一圈**：`finallap` 音（`Count\FinalLap.evt`）+ HUD `FINAL_LAP` + `addHUDTimer(2.0)`；
  `laps >= 总圈数` ⇒ **`handleRaceTime(lastCPtime, 车下标, flag)`**；
  否则 push 新 `LapStats{lapNum = laps, startTime = 绝对t, splitTimes = new float[splits]}`，`flag==1` 时 HUD `setCurrentLap(laps+1)`。

### 6.4 完赛 `handleRaceTime(完赛时刻, 车下标, flag)`（GmRace.java:780–865）
```
racerStats[i].raceTime = 完赛时刻;  racerStats[i].racePos = racerStats[i].pos;   // 冻结名次
if (是 Bot): Bot.stop();
   if (racePos == 1 && 有 HUD): addTimer(1.0, 13); HUD COUNTDOWN_STARTED;
                                showInfo("$13|Race's gonna end. Coundown started!"); minutesLeft = 15;
if (racePos == racers /*最后一名*/):
    按名次链生成奖励权重 1000 → 500 → 250 …（×0.5 递减）      // ⚠ 数组随后未被使用（消费方丢失）
    diffTime = 完赛时刻 − leader 的 raceTime
    if (countDownOver) return
    if (这车是玩家):
        removeTimer(13); removeTimer(14); 隐藏倒计时数字;
        非 practiceMode ⇒ 按名次显示 FIRST_PLACE / SECOND_PLACE / THIRD_PLACE / FINISH；否则 FINISH
        addHUDTimer(3.0); finish()
    else if (childWindow 是 ResultsWindow): refreshResults(...)
```
**AI 夺冠 ⇒ 启动 15 分钟收尾倒计时**（timer 13 每分钟一跳，见 §7.3）。

### 6.5 名次交换 `checkTakeover(stats)`（GmRace.java:544–584）
进度量：
- 未完赛：`laps * 100.0 + (nextCP == 0 ? 检查点数 : nextCP) − distance * 0.0001`
- 已完赛：`1000000.0 − raceTime` ⇒ **完赛者恒排在未完赛者前，用时短者更前**
与链上**紧邻前车**比较，更大则交换链指针与 `pos`（`local4.pos = local1.pos; local1.pos = local4.pos − 1`），
继续向前比（goto）；若最终 `pos == 1` 则 `leader = index`、`diffTime = 0`。返回换位次数。

### 6.6 差值 `diffTime`
- `getCheckTime(stats, 圈号, cp号) = LapStats[圈号].splitTimes[cp号] + LapStats[圈号].startTime`（圈号 <0 返回 0）。
- `refreshDiffTime(stats)`：`pos == 1` ⇒ `diffTime = 0`（并刷新 `leader`）；否则
  `diffTime = (simTime − getStartTime()) − getCheckTime(racerStats[leader], stats.laps, stats.nextCP)`。
- `guessDiffTime(a, b)`（:586–653，⚠ 结构不可全信）：用**两车到当前 CP 的样条距离比例**线性插值出预测时刻，
  返回「当前耗时 − 预测时刻」；`b.pos == 1` ⇒ 0；`distance < 1.0` 或 `distance/段距 > 0.95` ⇒ 回退用 `diffTime`。
  HUD 用它显示前车 `+x.xx"` / 后车 `-x.xx"`（>60 s 不显示文字）。

### 6.7 最佳圈来源（多路）
房间参数 `ROOM_PARAM_BestLapTime / 1000.0`（GmRace.java:384–385、:135）；
`MES_TYPE_Only4JavaRankingLapTRec` ⇒ `recordStats.bestLapTime = args[7]/1000.0`（:171）；
`MES_TYPE_Only4JavaRankingLapTUser` ⇒ `racerStats[localUserSlot].bestLapTime = args[7]/1000.0`（:176）。
⇒ **时间单位统一是秒（float），网络/房间参数里是毫秒（int）**。

---

## 7. 事件与定时器管线（原生 ⇄ Java，本轮新增基础设施）

### 7.1 事件位（`java.util.resource.GameRef.<clinit>`，逐字 ✓）
`EVENT_COLLISION=1` `EVENT_DELETE=2` `EVENT_HIT=4` `EVENT_DAMAGE=8` `EVENT_COMMAND=16`
`EVENT_TRIGGER_ON=32` `EVENT_TRIGGER_OFF=64` `EVENT_TIME=128` `EVENT_DESTROY=256` `EVENT_WATER=512`
`EVENT_INFO=1024` `EVENT_BODYCOLLISION=8192` `EVENT_GNDCOLLISION=16384` `EVENT_NETEVENT=32768`
`EVENT_CURSOR=65536` `EVENT_HOTKEY=1048576` `EVENT_ANY=268435455` `EVENT_NONE=0` `EVENT_CUSTOMINFO=268435456` `EVENT_SAME=0`

### 7.2 注册机制 = **按方法名字符串回调**
Java：`addNotification(target, onMask, offMask, ?, handlerMethodName)` / `remNotification(target, mask)` /
`setEventMask(mask)` / `clearEventMask(mask)` / `registerCallback(GII_*)`（均为 native）。
原生：`addNotification` 实现位于 **0x420DD0 / 0x420EE0**，函数内两处 `call 0x643BF0` = **按名驻留字符串**，
再 `mov ecx, esi; call 0x432470` 登记 ⇒ **处理器名以字符串存进引擎，命中时回调该名字的 Java 方法** ✓（实测）。

| 处理器名（字符串） | 注册点 | 事件 | Java 方法 |
|---|---|---|---|
| `"event_handlerTrigger"` | GmRace.java:407 / GmTrial.java:197 | `EVENT_TRIGGER_ON` | `GmRace.event_handlerTrigger`(432) / `GmTrial.event_handlerTrigger` |
| `"handleCollision"` | GmRace.java:64, 67 / GmTrial.java:48 | `EVENT_COLLISION` | `GmRace.handleCollision`(1311) / `GmTrial.handleCollision`(454) |
| `"handleInfo"` | GameMode.java:567 | `EVENT_INFO` | `GameMode.handleInfo`(371) |
| `"handleAiInfo"` | GmRace.java:247 | `EVENT_INFO`（对手车） | `GmRace.handleAiInfo`(99) |
| `"handleBannerTrigger"` | GameMode.java:358–363（对 `map.banners` 每个触发器） | `EVENT_TRIGGER_ON｜OFF` | `GameMode.handleBannerTrigger`(417) |

`GameRef.handleEvent(GameRef,II)` / `(GameRef,I,String)` 是**基类默认实现**（只 `System.log("Unhandled event for …")`）；
真正覆写者：`GmRace:894`、`GmTrial:323`、`Track:2278`、`Vehicle:1291`、`Replay:476`。

### 7.3 定时器（`addTimer(周期秒, id)` / `removeTimer(id)`，id 是全局命名空间）
| id | 周期 | 用者与含义 |
|---|---|---|
| 13 | 1.0 | `GmRace`：AI 夺冠后的**分钟**收尾倒计时（:791 注册；`handleEvent` case 13 每跳递减 `minutesLeft`，7 分钟提醒、0 分钟 `finish()`） |
| 14 | 0.01 / 1.0 | `GmRace`：**秒**级收尾（`ROOM_PARAM_GM_GameEndTime` 变化时 :143–148 注册；30 s 内显示两位数字，20 s/7 s 提醒，0 s 结束） |
| 15 | `timeLimit` | `GmTrial` 限时（GmTrial.java:172）；case 15 ⇒ `success = false` + `finish()` |
| 1001 | 1.0 | `GameMode`：涉水/洪水后的干燥重生点（`handleInfo` 的水 mask 分支，:382–392） |
| 10 | 1.0 / (a+b) | `Track`（:480/507） |
| 3 | — | `Track`（:1765 remove） |
| 0 / 1 | 0.1 | `Replay` 录制/播放心跳 |

### 7.4 各模式的事件掩码（实测）
`GmRace.<init>` / `GmTrial.<init>`：先 `setEventMask(EVENT_INFO|EVENT_COMMAND|EVENT_HOTKEY|EVENT_TRIGGER_ON|EVENT_TRIGGER_OFF|EVENT_TIME|EVENT_COLLISION)`，
紧接着 `setEventMask(EVENT_TIME)`（GmRace.java:35/42、GmTrial.java:31/33）。**已定案（`docs/54` §4.4）**：
`setEventMask` native @0x421700 → 核心 `0x42b650` 是 **`or [obj+0x88], mask`（累加，不覆盖）**；
`clearEventMask` @0x421770 → 核心 `0x42b6b0` 是 **`not mask; and [obj+0x88], mask`（清位）**。
⇒ 上面的两次调用等价于「大掩码 ∪ EVENT_TIME」= 大掩码本身；掩码存在对象 `+0x88`（按类型 vtable 偏移表 `0x7439b0` 索引）。
`GameMode.initGameMode` 末：`setEventMask(EVENT_TRIGGER_ON|EVENT_TRIGGER_OFF|EVENT_TIME)`（:365）；
`reset()`：`setEventMask(EVENT_INFO)`；`deinitGameMode`：`clearEventMask(EVENT_ANY & ~EVENT_NETEVENT)` + `removeAllTimers()` + `MetaServer.remHandler(this)`。
其它：`Bot`(`EVENT_COMMAND`)、`Chassis`/`io.Controller`(`EVENT_NETEVENT`)、`io.Pointer`(`EVENT_CURSOR`)。

### 7.5 两个 `handleMetaEvent`（网络事件）
`Gamelogic.handleMetaEvent` 处理房间参数/服务器消息；`GmRace.handleMetaEvent`（:110–182）在转发基类后处理：
- `MES_TYPE_RoomParameterChange`：`ROOM_PARAM_USER_PP` ⇒ 写 `racerStats[i].score`（并在结果显示窗开着时 `refreshResults`）；
  `ROOM_PARAM_BestLapTime` ⇒ `bestLapTime = 参数/1000.0`；`ROOM_PARAM_GM_GameEndTime` ⇒
  `raceOverTime = 参数/1000`、`secondsLeft = (int)(raceOverTime − track.getRaceTime() + 1.2)`、`removeTimer(14)` + `addTimer(0.01, 14)`；
- `MES_TYPE_RoomMessageFromInspector`（`RE_carTriggerOn`）⇒ 过点链（见 §5.2）；
- `MES_TYPE_Only4JavaRankingLapTRec` / `…LapTUser` ⇒ 最佳圈回写（见 §6.7）。

---

## 8. 犯规 / 越界 / 碰撞 / 救援

### 8.1 干净圈奖励（硝基）
`cantBeCleanSector(float)`（GmRace.java:1303–1309）：`cleanSector = false; cleanLap = false;`
触发点：`handleCollision` 里 `damageSum > 0.15`。奖励：干净分段 **+1.0**、干净一圈 **+5.0**；
GmTrial 的差异：`cleanLap = false` ⇒ **当场判负**（`letMeLose()` → `success = false` + `finish()`，GmTrial.java:441–444、:477）。

### 8.2 逆行 / 漏点提示（`GmRace.run`，:1157–1218）
`distance = 环形最短(到 nextCP 的样条差)`（> 段长一半则取补）；
`distance_min` 记录历史最小；当 `distance > distance_min * 1.5` 且 inspector 未报过该 CP 时，
再看**到上一个 CP 的样条差** `|Δ| > 2.0` ⇒ HUD `WRONG_WAY` + `addHUDTimer(3.0)`；
例外：玩家速度与 `map.getSplineDir(0, val)` 点积 ≤ 0（正朝赛道方向）则**不提示**。
常量：`1.5`（1 倍半）、`2.0`（样条差阈值）、`3.0` s（提示时长）、`80.0`（接缝带）、`10000.0`（distance 哨兵）。

### 8.3 碰撞（`handleCollision`，:1311–1393）
窗口 **2.0 s**（超时清零 `damageSum`）、阈值 **0.15**、累积窗 **0.5 s**、去抖 **0.2 s**（0.2 s 内同一对不重复处理）；
只对含 Bot 的一对记 `raceChron.addPush()`：判据是**碰撞方向与该 Bot 朝向的偏航差 < ±1.5 rad**（= 被推）；
`raceChron.addCrash()` 由 UI（`carConditionComponent:119`）调用。
⚠ `:1325–1328` 的 `if (damageSum > 0.15)` 位于已知 `damageSum <= 0.15` 的 else 分支内 = **死代码**（逐字如此）。

### 8.4 救援 / 维修
- 门：`repairAllowed` → `respawnAllowed`；基类 `true`，**GmTrial 覆写为 `false`**（试驾禁用救援/维修按钮，调用点 `frontend/IngameMenu:198/203`、`Track:1280/1286`）。
- 允许性：`canRespawn(...)` = 候选点 8.0 m 内无其他车（§2）。
- 统计：`RaceChronicle.addRescue()/addRepair()` 在 IngameMenu 的救援分支成对调用。
- **赛道横幅（banner）= 救援点**：`GameMode.handleBannerTrigger` 在 `EVENT_TRIGGER_ON` 且 `token(0) == 玩家车 id` 时直接
  `respawn()`（:417–422 ⇒ :687–689 `respawn(player)`）。banner 数据来自地图类的 `banners` 字段（每张图都有）。
- 提示音节流：`playTimed(sfx, 时间)` —— 最近 4 个已播 id 去重 + **至少间隔 1.5 s**（GameMode.java:424–439）。

---

## 9. 结束与结算

### 9.1 两种模式的结束路径
| | 街道赛 `GmRace.finish()`（:980–1059） | 试驾 `GmTrial.finish()`（:335–391） |
|---|---|---|
| 结束触发 | `handleRaceTime` 里玩家最后一名完赛 / 超时定时器 | `checkSuccess()`（`raceTime < timeLimit`）或 timer 15 超时、或撞车 `letMeLose()` |
| 结果 | `racerStats[localUserSlot].racePos == 1` ⇒ 夺冠 | `result = 1` 成功 / `0` 超时 / **`-1` 失败且撞过车**（:341/343/347 ✓） |
| 冲线演出 | `(flags & 512) == 0 && 车速² > 300.0` ⇒ 建 `Bot "Bob"` 接管、`AI_maxspeed = (1 − t/5)³ × v + 0.01` 递减至 0（:993–1017）；否则 `command("brake")` + `sleep(3000)` | 失败且距终点 < 20.0 ⇒ `timeWarp(0.0)` + 相机 `"simulate 1"` + 2×`sleep(1000)` + `timeWarp(1.0)` |
| 战绩 | `raceSum++`、夺冠 `winSum++`、`raceChron.setPrestige(getPrestigeForRace(胜))`、`setNewRaceChronicle`（**仅非快跑**） | `trialCompleted(trial)` ⇒ 完成数 +1、整组 3 个（`TRIALS_PER_SERIE=3`）完成 ⇒ `newConversoinAvailable = true` |
| 结算落地 | `changeStatus(GST_MENU)` 钩子 ⇒ `challenge.apply(胜)` 结算赌注（赢收件/收车、输掉件）+ `save()` | 同（`Challenge.apply` 里 `trialMode` 为真直接 return） |

`Challenge.getPrestigeForRace(I)` **恒返回 0**（Challenge.java:26–27）⇒ 写入 RaceChronicle 的 `prestige` **恒为 0**，
真正的 prestige 变动在 `Challenge.updateRanking()`（连败偶数次降档 / 击败更高排名对手升档）。
输赛难度补偿 `Gamelogic.lostRace(usedAILevel)`（:1793–1800）：`aiLevelMul *= 1 − 0.03 × (1 − usedAILevel)`
（另有一条 `local1` 恒为 0.0 的死式）。

### 9.2 `RaceChronicle`（存档布局，逐字 ✓）
写入顺序（save）/ 读取顺序（load）完全一致，**17×int + 1×float = 72 字节/场**：
`bestLapTime(f32)` 夹在第 6 位；其余 int：`splineLeft, crashes, won, rescue, repair, pushes, trackID, TOD, laps,
mycar, mystage, opcar, opstage, pinks(0/1), prestige, opstatus, oprank`。
初值：`trackID/TOD/laps/mycar/mystage/oprank = -1`、`opstatus = -2`、`prestige = 0`（:2–15）。
**`longestOffSplineTime` 不落盘**（save/load 都没有它，只在局内累加）。
`setNewRaceChronicle` 环形缓冲上限 **15**（`MAX_RACECHRONICLE`）。
⚠ `setLapTime(f)` 的比较符是 `>`（保留**最慢**圈，RaceChronicle.java:127–128），与 `RacerStats` 的「最快圈」相反，
且**全库无调用点** ⇒ 按 `RacerStats` 语义实现（**存疑，见 §11**）。

---

## 10. 重制落地清单（照此实现即可跑通一局）

1. **检查点**：门盒（pos/ori/size，尺寸取自地图 `*_track_0` 的 CheckPoint 构造），沿 route 0 的样条值定序；
   `nextCP` 命中判定 + `getSplineVal/Perp/Width/Dir/NearestSpline/SplineLength` 六个原生查询（`docs/21` 已有 .spl2 全量）。
2. **起跑**：倒计时 3/2/1 各 1 s + `GO`；发车顺序 `startOrder`（单机洗牌、联网 `NormalizeStartOrder`）+ `mtr.startGrid`。
3. **计时**：`raceTime = simTime − startTime`；每圈 push `LapStats{lapNum, startTime, splitTimes[]}`；
   三处最佳圈（存档/本场/本车）；差值用 §6.6。
4. **名次**：双向链 + `pos`；`checkTakeover` 进度量公式（含完赛者 `1000000 − raceTime`）每帧全体比对。
5. **干净圈**：`cleanSector/cleanLap` + 硝基 +1.0/+5.0；碰撞阈值 0.15/窗口 2.0 s。
6. **结束**：完赛冻结名次、AI 夺冠后 15 分钟收尾倒计时、结果窗、`Challenge.apply` 结算、
   `GST_INGAME → GST_MENU` 钩子里 `repair()` + `save()`。
7. **试驾**：限时 timer、`success = raceTime < timeLimit`、结果 1/0/−1、禁救援、检查点计数取代圈数。
8. **事件层**：实现与原生等价的「事件位 + 具名处理器 + 定时器 id」三件套（不必逐位兼容，但要把 §7 的表当接口契约）。

---

## 11. 未知清单（✗）

| # | 项 | 影响 | 备注 |
|---|---|---|---|
| 1 | ~~`setEventMask` 是覆盖还是累加~~ **已定案** | 事件能否被收 | **累加**：`or [obj+0x88], mask`（0x42b650）；`clearEventMask` = `and not`（0x42b6b0）—— 见 `docs/54` §4.4 |
| 2 | `handleCP` 第 4 参 `flag` 何时为 1 | 只影响 HUD 刷新（差值/分段显示），不影响计时数值 | 赋值语句在被丢的空块里（:520–522） |
| 3 | `handleCP:534-539` / `handleSplitTime:683-684` / `handleLapTime:744-745` 的「乱码行」 | `nextCP` 推进、`distance` 复位的精确写法 | 已按 `:740-741` 同构式还原（推断），建议重制时用 `nextCP = (nextCP+1) % N` |
| 4 | `handleRaceTime` 的奖励权重数组（1000→500→…）消费方 | 名次奖金/PP 结算 | 伪码丢失消费方 |
| 5 | `RaceChronicle.setLapTime` 的 `>` 方向 | 存档里那格存的是最快还是最慢圈 | 无调用点，重制按最快圈 |
| 6 | `processTrigger*` / `guessDiffTime` 参数编号在头部与实际用法不一致 | 只影响读码，不影响重制（按 header 实现） | §0.1 规则已给出判定法 |
| 7 | `GmRace.stop()` 只拆掉约一半检查点触发器（`removeElementAt(i)` 且 `i++`） | 内存/句柄泄漏 | 逐字如此，重制应改成清空 |
| 8 | `GmTrial.racerStats` 无分配点 | 试驾下访问 `getCheckPointMissedSplineval` 可能 NPE | 或被引擎另一路径初始化 |
| 9 | `Trigger` 两个「空体」构造（banner 用的 7 参重载）三个 float 是 size 还是 halfsize | banner 触发盒体积 | 需实机用 `Config.showTriggers` 目视 |
| 10 | 计时时基混用：`simTime()` vs `currentTime()`（GmTrial.start vs restart、GmRace.start vs restartQuick） | 重开后计时可能偏移 | 建议统一用 `simTime` |
| 11 | `timeWarp`、`addHUDTimer`、`setCounter/getPointNumbers`（HUD 数字面）、`Integer.toOrdinal` 的实现 | HUD 表现 | 原生/工具类，未解 |
