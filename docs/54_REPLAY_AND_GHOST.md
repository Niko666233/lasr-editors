# 54 — Replay / 幽灵车（录像系统）完整规格

> 覆盖：`java.game.Replay`（599 行伪码）+ `ReplayInfo` + `GmReplay` + `ReplayWindow` + `FilePopup`（回放文件浏览器）
> + 原生 Replay 引擎（25 个原生方法、容器格式、对象/帧数据模型）。
> 标注约定：**✓** = 本轮已回原文/反汇编复核（给出行号或地址）；**✗** = 未解；**推断** = 由形状推得。
> 机器可读版：`out_replay_spec.json`。工具：`tools/replay_tags.py`（分块 tag 普查）、`tools/replay_reg.py`（原生注册表解码）。

---

## 0. 本轮新增的四条伪码/反汇编坑

1. **线性反汇编从半条指令起步会吞掉一个 `push imm32`**。`java.game.Replay.seekRel` 的注册项就在
   `0x42ae43`（`68 e0 98 42 00` = `push 0x4298e0`），而从 `0x42ae48` 起反汇编会看到
   `68 48 7f 6e 00 / 68 b4 b6 6e 00 / 8b 0d …` 三个「push + mov ecx」，于是得出「没有函数指针」的错误结论。
   **判据**：拿 4 字节小端字面量在整镜像里搜（`e0 98 42 00` 全文件只出现在 `0x2ae44` ⇒ VA `0x42ae44` 就是那个 push）。
   这也解释了 `out_native_methods.csv` 里为什么独缺 `seekRel` 一行（24 行而非 25 行）。
2. **`push imm32` 与 `mov ecx, [绝对地址]` 交错出现时，方法注册块的参数顺序不能只看 push 个数**。
   实测签名是 `0x652910(cls, name, sig, fn)`，`ecx` 另带一个句柄；本轮用「每个调用点前 5 条对齐反汇编 + 字符串解析」批量还原了 25 项。
3. **伪码里「重建残缺」有三种可判形态**（本轮在 `Replay.java` 一次撞见三处，见 §2.5；见到就标「疑似重建产物」，别当逻辑写进规格）：
   ① `while` 循环只有 `else` 分支自增 ⇒ 原实现含 `break`，命中的那次就是死循环；
   ② 方法/分支结尾留下 `if (x != null) {}` 空块 ⇒ 原实现非空（与读法规则 2 同源）；
   ③ 同一表达式双重自增（`indexOf(cur)+1` 之后又 `+1`）⇒ 边界行为不可信。
4. **子代理的复述必须回原文逐条复核**：本轮 3 个子代理给出 8 条关键断言（`Track.java:1090` 的 `Play()`、
   `Vehicle.replay_register/load` 写 `objparams`、`exitTo` 无读点、`ReplayWindow` 继承 `Window`+`HotkeyEventHandler`、
   `gameModeArray` 只装 `GmRace`、`mainMenu` 的生涯存档前置、`loop=true`、`Record` 三处上下文），
   全部用一次 `grep -rn` 批量打勾后才写「✓」；坐标类的则用 `out_ui_layouts.json` 独立复核（§5.4）。

---

## 1. 系统总览

回放系统是**「Java 层薄包装 + 原生录制引擎」**的分工：

```
java.game.Gamelogic.replay  (单例, Gamelogic.java:311)
        │  1:1
        ▼
原生引擎对象  [0x770fc0]   0x50 B   ← create_native @0x42ab70 / delete_native @0x42ac20
        │
        ├── 录制：record(map)  → 每帧把对象状态追加进内存
        ├── 存盘：save(File)   → 写「分块容器」(RPLH/RPLO/EOF)
        └── 播放：load(File) + seekAbs/seekRel + 每对象帧链重放
```

* **录像不落盘也可以回放**：`Record()` 之后 `replay.length() != 0 && replay.isReplay` 才让
  `FilePopup` 的 Save/Actual 按钮可用（`FilePopup.java:81-88`）⇒ **每局比赛都在自动录**，存盘是玩家的可选动作。
* 录制启动点（✓ 全库 grep，仅 3 处）：
  | 调用点 | 所在方法 | 上下文 |
  |---|---|---|
  | `GmRace.java:1475` | `GmRace.restartQuick()` | `command("start")` / `command("stop")` 之后、`startScene()` 之前，即 docs/48 倒数 `saythree`(-3 s) 前一刻 ⇒ **录像包含发车全过程** |
  | `GmTrial.java:532` | `GmTrial.restart()` | 试驾/挑战起跑前 |
  | `GameMode.java:299` | `GameMode.handleMetaEvent` | `case MES_TYPE_RoomMessageFromInspector` + `RE_timeOut` ⇒ **多人房间超时**时由逻辑层统一开录 |
* 停止录制（✓ 4 处同款）：`IngameMenu.java:105-108`、`GameMode.java:617-619`、`GmRace.java:1022-1024`、`GmTrial.java:377-379` 都是
  `if (useNetwork && localUserIndex != 0) { replay.stop(); log("Replay Record Stopped"); }`
  ⇒ **只有联网且不是房主时才主动停录**；单机录像一直写到内存上限/换场景，落盘只靠玩家点 Save。
* **`Play()` 有 4 个外部调用点**（✓）：`FilePopup:109`（Actual，播内存里最后一场）、`FilePopup:119`（Load 完文件）、
  `Gamelogic.java:498`（命令行 `playback=` 成功）、**`Track.java:1090`（`openIngameMenu` 的 `case 4:` = 赛后结果界面「看回放」）**。
* **播放屏只能由 `Play()` 创建**：全库唯一的 `new ReplayWindow` 在 `Replay.java:100-101`；
  且 `Gamelogic.gameModeArray = { Class.forName("java.game.GmRace") }`（`Gamelogic.java:107`）
  ⇒ **`GmReplay` 不在可选模式表里**，回放不可能从「选模式」菜单进。
* **幽灵车没接线**：`MODE_GHOST = 3`、`RPLOF_GHOST = 1`、原生 `ghost(GameRef)` @0x427ff0 三者俱全，
  但 2216 个伪码类里 **`ghost` 零调用点**（grep 只命中常量定义行 `Replay.java:5-6`）⇒
  **幽灵车/最佳圈影子车是一个做了一半、未启用的功能**。重制时要不要补，属于设计决策，不是复原任务。
* **未启用的还不止幽灵车**（✓ 全库 grep）：`EXIT_TO_PRACTICE`、`exitTo`（只被写一次、无人读）、
  `getIsReplay()`、`setPlayPause()`、`Restart()`、四档速度方法（`DoubleSpeed_onAction` 等，字节码在但布局无绑定）
  都是死代码 —— 见 §5.4 与 §7。

---

## 2. Java 层

### 2.1 常量（`Replay.java:1-13`，✓ 逐行）

| 常量 | 值 | 说明 |
|---|---|---|
| `MODE_IDLE` | 0 | |
| `MODE_RECORD` | 1 | |
| `MODE_PLAY` | 2 | |
| `MODE_GHOST` | 3 | **未启用**（见 §1） |
| `RPLOF_GHOST` | 1 | 对象级标志（native `flagObject(id, flag)` 用） |
| `VERSION` | `17301504` = `0x01080000` | 文件头版本 |
| `EXIT_TO_MAINMENU` | 0 | `exitTo` 的初值 |
| `EXIT_TO_PRACTICE` | 2 | **死常量**：`exitTo` 全库只被写一次（`Replay.java:18`）、**无任何读点** ⇒ 实际退出目的地只有主菜单（见 §5.4） |
| `CRLF` | `"\r\n"` | 文本输出用 |
| `CMD_TARGET` | 101 | 消息命令：切镜头目标 |

`Replay.mode()` = `s_mode != MODE_IDLE ? s_mode : native_mode()`；`native_mode()` = **`engine[+0x48] & 0xFF`**（✓ `0x4280cb`）。

### 2.2 录制 `Record()`（`Replay.java:49-65`，✓）

```java
s_mode = MODE_IDLE;  isReplay = true;
map = Gamelogic.gameMode.track.map;  trk = …track;  gm = Gamelogic.gameMode;
gameModeId = gm.getId();  driverId = Gamelogic.player.getDriverType();
TOD  = MetaServer.getRoomParameterI(ROOM_PARAM_LEVEL_main, ROOM_PARAM_timeofday);
if (TOD == -1) TOD = MetaServer.getRoomParameterI(ROOM_PARAM_LEVEL_main, ROOM_PARAM_randomTOD);
mapId  = MetaServer.getRoomParameterI(ROOM_PARAM_LEVEL_main, ROOM_PARAM_map);
spline = MetaServer.getRoomParameterI(ROOM_PARAM_LEVEL_main, ROOM_PARAM_track);
native record(this.map);
```

⇒ **文件头的 5 个字段全部来自「房间参数」**（`java.net.MetaServer`），不是从 `Track` 对象上读的。
单机也走同一套（MetaServer 是本地房主）。这一点对重制很关键：**比赛配置的真值源是 room parameter 表**，
和 docs/49 的前端流程、docs/48 的模式表串成一条线。

**唯一可见的写入方**（✓ 全库 grep）：`Gamelogic.changeMap(IIIII)`（`Gamelogic.java:1246-1253`）一次写 5 个 param
（map / track / timeofday / LAP / gamemode），由 `Gamelogic.enterRace(Challenge)`（`changeStatus(GST_INGAME)` 的分支，
`Gamelogic.java:888-889`、`:936`）经 `changeMap(trackID)`（`:1232-1237`）调用 ⇒ **「进赛道那一刻」快照**。
⚠ 该方法的实参顺序与 body 里的 `local` 对位在这份伪码里有明显错位嫌疑（5 个 local 全被用掉、`local5` 空缺），
**具体哪个实参落到哪个 param 标「不确定」**，不要照抄。
其它 param 的写者（都不写 map/track/timeofday）：`GmRace:84`(MapSplineID)、`GmRace:88`(Checkpoints)、`Gamelogic:901`(LAP)、
`Gamelogic:1274`(STARTORDER)、`Track:113`/`:2153`(REF_TIME)、`IExtraPcs:21`(ItemFlags)。
回放时 `Loading.java:127-134` 改读**文件里的快照**（`replay.spline/mapId/TOD/gameModeId`）而不是 room param
（非回放时同屏读 room param，`:135-141`）⇒ **回放不依赖当前房间配置**。

> ✗ 商品门控：`CommonStrings.BUY_REPLAY = "$6|To record replays, buy replay medium in the shop first!"`
> 与 `IExtra.REPLAY → IExtraPcs("Replay medium", "These are the medium needed to save your replays on.", …)`
> 说明**录制/存盘需要先买道具**；但 `BUY_REPLAY` 全库只命中定义行、无使用者，**门控判断点未定位**（✗）。

### 2.3 播放 `Play()`（`Replay.java:67-111`，✓）

1. 重建 32 个 `ItemRoot`；`replayMapRoot = ItemRoot(MAP_PRID << TYPE_SHFT | mapId)`；
2. `Gamelogic.useNetwork = false`；清 timer 0/1；`s_mode = MODE_PLAY`；
3. `Gamelogic.gameMode = new GmReplay()`（回放走独立的模式对象）；
4. `listMaps()` 里按 mapId 找 index（`-1` → 用末项；取到 null → `System.exit("Map N not found!")`）；
5. `trk = new Track(map, spline)`；`changeScreen(null)` → `changeScreen(new ReplayWindow())`；
6. `trk.enterToReplay(rwindow, new Viewport(0, 0.0, 0.0, 1.0, 1.0))`（全屏视口）；
7. `gameModeId ∉ {2,3}` → `loadAllSplines()`；
8. `timeWarp(1.0)`；`setEventMask(EVENT_COMMAND | EVENT_HOTKEY | EVENT_TIME)`；`addTimer(0.1, 0)`。

`enterCallback()`（`Replay.java:145-149`，✓）= `native play(map); native seekRel(0.01); timeWarp(0.0)`。
`timeWarp(0.0)` = **把游戏时钟停住**，回放时间只由引擎自己推进 —— 这与 docs/48 的 `timeWarp(0.0)` 用法一致。

### 2.4 事件驱动的心跳（`Replay.java:476-508`，✓）

`handleEvent(GameRef, type, arg)`（注意形参逆序：`local2` = type，`local1` = arg）：

| 条件 | 动作 |
|---|---|
| `type == EVENT_TIME` 且 `arg == 0`（timer 0） | `seekpos = native pos()`；`seekpos ≥ 1.0` → `loop ? seekAbs(0.0)+addTimer(0.1,0)` : `rwindow.setEndMovie() + addTimer(0.1,1) + end=true + removeTimer(0)`；否则继续 `addTimer(0.1,0)` |
| `type == EVENT_TIME` 且 `arg == 1`（timer 1） | `end ? addTimer(0.1,1)` : `addTimer(0.1,0) + end=false` |

⇒ **回放的推进完全靠一个 0.1 s 的定时器轮询 `pos()`**，没有回调式的帧同步。timer id 0/1 与
docs/48 §timer id 表是同一套原生定时器（`addTimer(interval, id)` / `removeTimer(id)`）。

### 2.5 播放期的对象与镜头（`Replay.java:387-593`，✓）

| 方法 | 行为要点 |
|---|---|
| `addObject(GameRef)` | `Vehicle` → `preCache()`；导航图标 `Marker(PLAYERICON, veh)`；按 `driver_type` 决定是否切镜头到它；`driverName != "" && playerSlot >= 0` → `rwindow.setRacerName(slot, name)`，且（除非 `Config.majomParade`）造一个 `vehicles.rpk` 的 **3D 名牌** `RenderRef(veh, RenderType("vehicles.rpk", 4096+playerSlot), "name"+slot)`，用 `getBoneId("bone00")` 挂到骨骼点 —— ⇒ **车模有骨骼命名（`bone00`），名牌靠骨骼附加**，这对 docs/53 的网格/材质线是一条新线索 |
| `remObject(GameRef)` | 若它正好是镜头目标 → 换列表里另一台车 |
| `changeCarTarget()` | `indexOf(cur)+1`（`+1 >= size` 归 0 —— 注意双重 +1 造成**跳过一台车**的边界行为，✓ `Replay.java:526-529`） |
| `chooseCamTarget2(Vehicle)` | 找**离目标车最近**的另一台车当下一镜头目标；结尾 `if (local5 != null) {}` 是被重建吞掉的空块（✗ 原实现应为设置相机目标） |
| `carWash()` | 所有 `Vehicle.setDirt(0.0, 1)` |
| `handleMessage(Message)` | `MT_EVENT` + `CMD_TARGET`(101) → 同 `changeCarTarget` |
| `mode()` | 见 §2.1；⚠ 全文件里 `s_mode` 只被写过 `MODE_PLAY`（`:82`，随即 `:107` 复位 IDLE）其余全是 IDLE ⇒ **推断 `s_mode` 实践上恒为 IDLE、`mode()` 实际返回 `native_mode()`**（重建可能吞掉写点） |
| `objparams` / `tags` | **写入方在 `Vehicle`**（✓ `Vehicle.java:1373-1385`）：`replay_register()Ljava.lang.Object;` 与 `replay_load(Ljava.io.File;)Ljava.lang.Object;` 都 `new Vehicle_Replay_Params()` 后 `replay.objparams.addElement(...)` ⇒ **车辆自报的「回放参数」接口**，是解开每对象负载字段（§7 第 2 项）的 Java 侧入口；`tags` 则是 §2.5 里那批 `RenderRef` 名牌 |

> ⚠ **三处重建残缺**（按伪码读法规则 2 标注，别照字面当逻辑）：
> ① `addObject` 的 `while (local6 < BOT_ARRAY_MAX)` opponents 查找：只有 `else` 分支自增 ⇒ 命中即死循环，
> **原实现应含 `break`**；② `remObject` 找下一台车的内层 `while` 同样只有 `else` 自增（命中即死循环）；
> ③ `changeCarTarget` 的 `indexOf(cur)+1` 之后又判 `(local2+1) >= size`（**双重 +1**）⇒ 疑为重建错乱，
> 「跳过一台车」是字面行为、不一定原版如此。其余未解语义：`driver_type == 1`、`Marker.PLAYERICON`、
> 子资源号 `4096+slot`、挂点 `getSlotPos(9997)`、`setDirt(0.0, 1)` 的第 2 参。

### 2.6 载入/存档/查询

| 方法 | 关键事实 |
|---|---|
| `Save(String) :366-382` ✓ | `isReplay` 且 `File.open(MODE_WRITE)` → 写 6 个 u32（version/mapId/spline/TOD/gameModeId/driverId）→ `native save(f)` → `close`；**返回 0 = 失败**（`FilePopup.java:139` 据此打 `"save replay - failed"`），native 成功返回 1。★ **`isReplay` 只在 `Record()` 里置 `true`**（`:21` 构造为 false；`Load`/`Play` 体内无赋值）⇒ **只有「刚录完、还在内存里」的录像能存盘；打开一个已有 `.rpl` 之后不能再另存**（与 `FilePopup.java:81/193` 的按钮使能条件自洽） |
| `Load(String) :268-358` ✓ | 读 version → 三个 case（见 §3.1）；成功后 `TOD<0 → 0`；清 `subtitleElements`；同基名 `.sub` 存在则解析。`s_mode` 只走 IDLE |
| `canLoad(String) :250-266` ✓ | `version ∈ {0x01080000, 0x01050000, 0x11070000}` **且** `mapId & (IMap.MAP_PRID << ItemRoot.TYPE_SHFT) != 0`；否则 `System.log("replay: invalid map/version …")` |
| `getInfo(String) :157-173` ✓ | 只读 24 B 头 → `ReplayInfo(version, mapId, spline, TOD, gameModeId, driverId)`；`FilePopup` 列表用它填「地图 / 赛道 / 时段 / 模式 + TOD 预览图」 |
| `Clear() :151-155` ✓ | `native removeAllTimers(); native clear(); s_mode = IDLE` |
| `finalize() :41-44` ✓ | `delete_native()` —— 原生引擎生命周期跟 Java 对象走 |
| `loadAllSplines() :113-132` ✓ | 反射 `Class.forName(map.getClass().getName() + "_freeride_0")`（一个 `MapTrack` 子类）取 `splineNames[]`，`map.clearSpline()` 后逐个 `map.loadSpline(i, name)` ⇒ **回放用「自由驾驶」spline 集，和比赛用的槽位集不同** |
| `unloadSplines() :134-143` ✓ | 对 0..`splineCount-1` 逐个 `clearSpline(i)` |

### 2.7 伴生类

* **`ReplayInfo`**（59 行）：构造形参顺序（按逆序规则还原 + 与 `getInfo` 读取顺序交叉验证）=
  `(version, mapId, spline, TOD, gameModeId, driverId)`；再经 `Gamelogic.player.items.listMaps()` +
  `getIndexById` 解析出 `mapName / splineName / todName / todTexture / gameModeName`，
  **TOD 索引经 `map.validateTodIndex()` 校正**。
* **`GmReplay`**（24 行）：`getPic() = ResourceRef("frontend.rpk", 126)`、`getLaps() = 0`、
  `getOpponents() = 0`、`getRoute() = this.route`、`getName() = "$1|Replay"`、
  `getRules() = "$2|Analyze your replays to learn more from your mistakes or from your opponents! …"`，
  `initGameMode` 直接委托基类 ⇒ **回放是「0 圈 / 0 对手」的退化模式**，与 docs/48 的模式表自洽。

---

## 3. 文件格式

### 3.1 整体布局（★ 已用真实录像 `samples/W_Brightwood_St-1.rpl` 校正）

```
<game>\save\replays\<名字>.rpl
├── SDAT 头  12 B   "SDAT" + u32 0x00030100 + u32 文件总长（close 时回填）
├── Java 头  24 B   6 × u32（Save/Load/getInfo 用 java.io.File 读写）—— 实际位于文件偏移 0x0C
├── 原生容器         分块流：RPLH → RPLO × N → EOF\0
└── SDAT 尾  12 B   00 ×8 + u32 8（四种存档文件全一致）
<同目录同基名>.sub    可选字幕（纯文本，见 §3.4）；**实测游戏本体从不生成**（下详）
```

★ **`.rpl` 不是裸文件：它和 `options` / `001.sav` / `active_control_set1` 一样被 SDAT 容器包着。**
四份文件实测（✓ 逐字节）：

| 文件 | SDAT 版本字段 | 长度字段 | 载荷首 u32 | 尾 12 B |
|---|---|---|---|---|
| `save\game\options`（360 B） | `00 01 03 00` | 360 ✓ | `0xFEDCBA98`（`SAVEFILEID`） | `00×8 + 08 00 00 00` |
| `save\career\001.sav`（1399 B） | `00 01 03 00` | 1399 ✓ | `0x97654301`（`SAVEFILEID_MAIN`） | 同上 |
| `save\controls\active_control_set1`（3382 B） | `00 01 03 00` | 3382 ✓ | `0x4C525443`（"CTRL"） | 同上 |
| `save\replays\W_Brightwood_St-1.rpl`（89531 B） | `00 01 03 00` | 89531 ✓ | `0x01080000`（`Replay.VERSION`） | 同上 |

⇒ 载荷的第一个 u32 一律是**该文件类型的 ID**（回放的 ID 恰好就是 `VERSION`，因为 `Save()` 先写版本号）。
这不是回放特有的格式，而是**引擎存档层的通用包裹**（`java.io.File` / 文件槽 IO 在 `open(MODE_WRITE)` 时写头、`close()` 时回填长度并写尾）。
⇒ **`docs/25` 里那份「options = SDAT」的描述可以推广到全部存档**；读回放时这 12+12 字节由 IO 层透明处理，`getInfo`/`canLoad` 看不到它们。

**Java 头**（`Replay.java:370-375` 写序 = `getInfo` 读序，✓ 两路互印 + 实测值）：

| 文件偏移 | 载荷偏移 | 类型 | 字段 | 实测（Brightwood 样本） |
|---|---|---|---|---|
| 0x0C | +0 | u32 | `version` | `0x01080000`（=17301504）✓ |
| 0x10 | +4 | u32 | `mapId` | `0xC0010000`（高字节 `0xC0` = `MAP_PRID` 位所在，符合 `canLoad` 的校验） |
| 0x14 | +8 | u32 | `spline` | `0` |
| 0x18 | +12 | u32 | `TOD` | `0` |
| 0x1C | +16 | u32 | `gameModeId` | `2`（= 单场比赛） |
| 0x20 | +20 | u32 | `driverId` | `3` ← ★ 与两个对象记录里 `d 3` 字段**独立互印** |

历史版本：`0x01050000`（17104896）只读**前 5 个**字段（无 `driverId`，`Replay.java:345-348`）；
`0x11070000`（285671424）在 `Load` 的 switch 里 **case 体为空**（✗ 疑似被结构化重建吞掉，见 §7）。

**读取工具**：`tools/rpl_parse.py <file.rpl> [--json out.json]`（本轮新增，逐字段打印上面全部结构）。

### 3.2 原生容器（★ 本轮逐指令解出 + 样本验证）

**分块语法**：`<4 字节 ASCII tag><u32 len><len 字节负载>`，以 `EOF\0` 收尾。
写入端 `0x428a20`（引擎→流），读取端 `0x42aa00`（流→引擎）。

| tag | hex | len | 负载 |
|---|---|---|---|
| `RPLH` | `0x484c5052` | 8（v1.01）/ 4（v1.00） | `u32 native_version`（读取端要求 `≤ 0x10100`；legacy 无此字段时引擎补 `0x10000`）+ `f32 total_length`（秒）。实测：`0x00010100` / `52.7142 s`（与真实一局时长吻合 ✓） |
| `RPLO` | `0x4f4c5052` | **恒写 4**（`0x4282cc`） | `u32 record_kind` + 资源自身序列化的数据（见 §3.3） |
| `EOF\0` | `0x464f45` | 0 | 结束（`0x428ab4` 写 / `0x42aa44` 读） |
| 其它 | — | — | **读取端按 len 跳过**（`0x42aa5d`，helper `0x560210`）⇒ 容器天然前向兼容 |

证据：写入端 `0x428a36-0x42aa4e`（RPLH）、`0x4282bb-0x4282d7`（RPLO）、`0x428a9c-0x428ab4`（EOF）；
读取端 `0x42aa28-0x42ab42`。`tools/replay_tags.py` 遍历 `0x5602c0` 的全部 62 个调用点，
**只有这 3 个 tag 以立即数出现在写盘路径上**（其余 59 个调用点写的是从变量来的负载），
⇒ 回放容器的 tag 词表就是这 3 个，不存在「没找到的隐藏分块」。

**RPLO 的读取路径**（`0x42aa72`）：分配 **0x8C 字节**节点（ctor `0x429f30`）→ 挂进 `engine+0x3C` 双向链
（`+0x44` 是尾）→ **`id = ++engine+0x4C`** → 节点 `+0x24 = 2` → `0x42a860(node, stream, len)`。

**文件 IO 模型**：所有原生文件操作走**文件槽表**（`0x88ebe8 + idx×0x10C`，32 槽，idx 1..0x1F），
三个 helper：`0x560290` = fread、`0x5602c0` = fwrite、`0x560210` = seek（0/1/2 三种模式）。
`sitap` 里 `save(File)` 先 `0x652ab0`（Java File → 槽号）再 `0x643bf0`（槽号 → 流对象）。

### 3.3 `RPLO` 的记录体：资源类型码 + 自序列化块（★ 原「len 恒写 4」之谜已解开）

写入函数 **`0x4282b0`**（逐指令，✓）走的是：

```
写 "RPLO" + u32 4                    ; 那个 4 就是「我接下来要写 4 字节」= 资源类型码本身，不是整块长度
kind = 0x434810(0x771050, res, 7, 0)
if (kind == 5) {                      ; 5 = 车辆（Vehicle）类资源
    写 u32 5
    ... 取 res 的某个接口 vtable（[res+0x24] 经 0x7439b0 偏移表）
    call [vtable + 0x48](记录节点, 引擎)   ; ← 资源自己的序列化器，往同一个流继续写
} else {
    写 u32 0
    call 0x403a80(记录节点, [0x771154], ...)   ; ← 通用资源记录写入器
}
```

⇒ **原来的「不一致」不存在**：`RPLO` 的 `len=4` 是字面正确的「头部长度」，后面的资源数据靠**自描述**接续，
不存在「谁来补长度」的问题（读取端 `0x42a860(node, stream, len)` 收到的 len 也参与同一个约定）。
`kind` 不是「0/5 两类记录」这么粗：它是 `0x434810` 解析出的**资源类型码**，实测样本里两条记录都是 `5`（两台车）。

**车辆序列化块（Vehicle blob）实测布局**（✓ 两条记录逐字段对齐，长度差恰好等于名字长度差）：

| 偏移 | 类型 | 内容 | 实测 rec1（玩家）/ rec2（AI） |
|---|---|---|---|
| +0 | u32 | 块格式号 | `9`（两条都是 9） |
| +4 | u32 | **对象 id** | `0x20010000` / `0x20070000` |
| +8 | u32 | 参数串长度（含 NUL） | `16` / `184` |
| +12 | str | **参数串**（见下） | `"r 2048 d 3 s 32\0"` / `"r 32 537329677 … 537329736 d 3 s 32\0"` |
| 串后 | u32 | 名字长度（含 NUL） | `5` / `6` |
| +4 | str | 司机/车手名（**不填充**） | `"Niko\0"` / `"Willy\0"` |
| 名后 | u32 | **槽号** —— 41 B 的 Java 头到此结束 ✓ | `0`（玩家）/ `1`（AI 对手） |
| +4 | u32 | 原生版本常量 `0x01040000`（来自 `[0x742a74]`） | 两条相同 |
| +8 | u32 | **帧数** | `476` / `519` ★ |
| +12 | — | **帧数据：直接从帧 0 的时间戳开始** | 帧 0 时间戳 = `0.0`（即 `00 00 00 00` —— 曾被误读成「保留字段」⚠） |
| 帧后 | u32 | **额外列表条数**（`[node+0x64]`） | `0` / `37` |
| 再后 | — | **额外列表**：`条数 × (u32 type + 8×f32)` = 36 B/条 | rec2 37 条 = 1332 B（type 恒 3）✗ 语义未定 |
| 之后 | — | 帧格式见 §3.3.1（★ 已完全解出） | |

**参数串语义**（三段空白分隔，`<字母> <值...>`）：
* `r …` = 本对象**被录制的子对象 id 表**。rec2 列了 17 个形如 `0x2007xxxx` 的 id（它是 `0x2007` 的零件：
  `0x2007000D`、`0x20070010`、`0x20070034`…）；rec1 却只有一个值 `2048`（`0x800`）—— ✗ 两者形态不同，语义未定。
* `d <n>` = **driverId**：两条都是 `3`，与 Java 头的 `driverId=3` 独立互印 ✓。
* `s <n>` = 两条都是 `32` —— ✗ 语义未定（疑与 `r` 表的容量/步长有关）。

> ⚠ 那些 `0x2007xxxx` id 在**载荷的二进制部分里一次都没以 u32 原样出现**（✓ 全文件计数 = 0）
> ⇒ 帧数据不是按 id 重复存储，而是**按索引/固定槽位引用**这些子对象。这也是「每对象负载」判读的关键约束。

#### 3.3.1 帧数据：★★ 已完全解出（✓ 实测 476 + 519 帧逐字节无缝隙）

**帧的书写函数 = `0x44d540`**（车辆资源接口 vtable `0x6edbb8` 的 `+4` 槽；`0x453af0` 循环
`[node+0x4c]` 帧链表逐个调用它）。**写入顺序与宽度（全部实测核对）**：

| 偏移 | 类型 | 内容 | 实测（rec1 帧 0 / 帧 300） |
|---|---|---|---|
| +0 | u32 | **帧时间戳**（按 f32 秒解释） | `0.0`（帧 1 = 0.1004，末帧 52.6581） |
| +4 | f32 ×3 | **世界坐标** `(x, y, z)`（y = 高度） | `(-281.4993, 117.3544, 76.9955)` / `(-71.3063, 130.6861, -87.1752)` |
| +16 | f32 ×4 | **朝向四元数** `(x, y, z, w)` | `(0.0058, -0.7, -0.0033, 0.7141)` / `(0.0656, 0.0189, 0.0031, 0.9977)` |
| +32 | u8 | **mask1**：bit0/1/2 = 后续通道存在位；bit4–7 = 数据位（= 帧节点 `[+0x51] << 4`） | `0x13` / `0x43` |
| +33 | — | if bit0 → 3 × f32（+12 B）；if bit1 → 3 × f32（+12 B）；if bit2 → 2 × u8（+2 B） | |
| ? | u8 | **mask2**：bit0–5 = 各 1 字节存在位（= 帧节点 `[+0x48..+0x4d]` 非 0）；**bit6/7 不占字节** | |
| ? | u8 × n | mask2 的 n 个字节，n = `popcount(mask2 & 0x3F)` | |
| ? | u32 | 单值（样本按 f32 解释 = `51.08 … 781.64`，均值 575.5；**与位移速度不相关**，✗ 语义未定） | |
| ? | u8 | **轮数**（样本 476+519 帧**恒为 4** ⇒ 四轮） | `4` |
| ? | 6 B × 4 | 每轮 6 字节量化值（✗ 内部拆分/物理量未定） | 帧 200：`[[20,87,75,3,136,1],[20,88,76,3,128,1],[20,88,78,1,82,4],[20,88,78,1,86,4]]` |

⇒ **帧长 = 32 + 1 + 1 + 4 + 1 + 24 + 12·bit0 + 12·bit1 + 2·bit2 + popcount(mask2&0x3F)**
   = 63 + 可选通道 + mask2 字节数（实测分布：`66×36, 78×28, 89×7, 90×168, 91×236, 92×1`）。
   这就是「变长帧」的全部来源：**掩码按帧决定带哪些通道**，不是变化驱动采样。

**逐帧序列化总体结构**（`0x453af0`，`ret 8`）：

```
u32 version = [0x742a74] = 0x01040000     ; 与 Java 头的 version 无关
u32 frameCount = [node+0x40]              ; rec1 = 476, rec2 = 519
frame × frameCount                        ; 0x44d540
u32 extraCount = [node+0x64]              ; rec1 = 0, rec2 = 37
extraCount × (u32 type + 8 × f32)         ; 36 B/条；rec2 = 37 条 = 1332 B（type 恒为 3）
```
※ 41 B（`9 / 对象id / 参数串 / 名字 / 槽号`）在这段**之前**，由 Java 上行调用 `java.game.Vehicle.save(File)`
写出（`0x453b2b call 0x434690`），`.exe` 内没有对应写码 ✓ 解释了为什么原生侧找不到那 41 字节。

**验证强度（可复现，`tools/rpl_parse.py`）**：
* rec1：476 帧从 `0x71` 起，**正好停在 `0xa400`**，其后 u32 = `0`，`0xa404` 就是下一条 `RPLO` —— **0 字节残差**。
* rec2：519 帧从 `0xa4ea` 起，正好停在 `0x1586f`，其后 u32 = `37`（= 第二列表条数），再后 1332 B 全部按 36 B 解释通。
* 时间戳 `0.0 → 52.6581` **单调不减**，dt 中位数 **0.1009 s（≈10 Hz）**；dt 最大 1.209 s（比赛中的空档/停顿）。
* **四元数 `|q| = 1.00000`（476 + 519 帧，最小值=最大值=1.0）** —— 这是「帧头 = 时间 + 坐标 + 四元数」的决定性证据；
  第 4 分量（w）在 rec1 458/476、rec2 324/519 帧里是最大分量 ⇒ 存储顺序 `(x, y, z, w)`。
* 位置序列形成一条平滑赛道轨迹（`z` 从 +77 一路到 -341、`y` 116→158 起伏）✓ 物理自洽。

> ⚠ 方法论教训：先用「坐标连续性 + 贪心」切帧，**能凑出 475/518 的近似帧数但是错的**（边界漂移、
> 末尾残留 100+ B），而且会把「时间戳在前 / 在后」判反（两种模型帧长公式相同、都能无缝铺满帧区，
> 只有时间戳单调性 + 四元数范数能判别）。**别用统计学替代读写入函数**。

### 3.3.2 帧内字段的物理语义（★ 本轮用样本 + 运动学交叉相关解出）

方法：把每条帧的**数值微分运动学**（世界速度、角速度、侧向加速度、滑移角）与未知字段做皮尔逊相关，
只承认 |r| 高且物理自洽的结论。工具：`tools/replay_dynamics.py`（产出 `out_replay_dynamics.json`）、
`tools/replay_viewer.py`（可视化 + `preview_tmp/replay_track.png` 静态图）。

| 字段 | 结论 | 证据（995 帧） |
|---|---|---|
| 头部四元数 | **车体→世界**旋转；**前向 = 局部 −Z、上 = 局部 +Y** | 用四元数旋转三条局部轴，与轨迹切向的 \|cos\|：Z 轴 **0.998 / 0.977**，X 轴 0.033 / 0.058；与世界 +Y 的 \|cos\|：Y 轴 **0.996 / 0.994**。滑移角均值仅 **2.2° / 4.2°**（p95 8.5° / 17.7°）⇒ 是真车身姿态而非错约定 |
| **mask1 bit0 的 3×f32** | ★ **世界速度 `v`** | 与数值微分速度逐分量：r = **0.998 / 0.997 / 0.999**（两车同时成立） |
| **mask1 bit1 的 3×f32** | ★ **世界角速度 `ω`** | 四元数差分得角速度：r = 0.875(x) / **0.990(y)** / 0.874(z)（y = 偏航分量最强，符合赛车） |
| mask1 bit2 的 2 字节（i8×2） | ✗ 本样本**从未出现** | 995 帧里该通道 0 次置位 ⇒ 该录像中恒 0（写入条件：`[node+0x4e/+0x4f]` 非 0） |
| **中段 u32（按 f32）** | ★ **引擎角速度 \[rad/s\]**（rpm = 值 × 9.5493） | ① 样本 47→830 rad/s = **450→7,900 rpm**，落在 `docs/14` 的引擎曲线区间（断点 0…8950，红线区 7444–8950）内；② 起步阶段两车各自升到 **776 / 825 rad/s 后长时间钉住** = 断油限转平台；③ 与车速**几乎无相关**（有变速箱）；④ rpm/车速 比值呈**离散挡位带**：玩家 ~300 / ~580，AI ~180 / ~240 / ~340 ⇒ 变速箱 |
| mask2 的 6 个字节 | ✗ 6 个「非 0 才写」的量化通道，含义未定 | 出现频率（玩家）：槽 2/4 恒在、槽 1 常在、槽 0 有时、槽 3 罕见、槽 5 从不；与速度/偏航 \|r\| ≤ 0.71 |
| **四轮记录的 6 字节** | 第 **0** 字节 = ★ **轮速**；第 3 字节 = 横向载荷类（疑）；其余 3 字节 ✗ | 第 0 字节与车速 r = **0.88~0.99**（四轮全部命中）；第 3 字节与侧向加速度 r = 0.64~0.76 |
| 额外列表的 8×f32（仅 AI 车有） | ✗ 语义未定 | 第 0 列 16.79→49.84 **单调增**、第 1 列 156.7→2439.8、末 3 列近似单位向量 |
| 世界单位 | ≈ **1 m**（弱证据） | 挡位带 300 rpm/(单位/s) + 典型轮半径 0.32 m ⇒ 总传动比 ≈ 10（1 挡量级） |

**交叉验证**：把两台车的帧解码结果各自画成轨迹（`preview_tmp/replay_track.png`），
**两条独立记录重合在同一段道路上** —— 玩家只跑完全程约 1/3（车速上限 12.7 单位/s），
AI 跑满整圈（上限 40.2 单位/s）。若任一车的帧边界错一个字节，两条曲线不可能重合 ✓✓。
（HUD 式可交互版本：`tools/replay_viewer.py` 生成的 `preview_tmp/replay_viewer.html`。）

### 3.4 `.sub` 字幕文件（`Replay.java:288-339`，✓）

> **实测：游戏本体从不生成 `.sub`**（用户全盘搜索确认）。它只在 `Load` 时被**尝试读取**，
> 且读不到只打一行 log。⇒ `.sub` 是**开发期工具链/手工产物**（SRT 风格），不是回放的组成部分；
> 重制时可保留「若是同名 `.sub` 就读」的兼容行为，但不必生成。

* 路径：与 `.rpl` **同目录同基名** + `.sub`；不存在则 `System.log("No subtitle for this replay")`。
* 时间轴行：`HH:MM:SS,mmm HH:MM:SS,mmm` —— 按空格分词取 `token[0]`（起点）与 `token[2]`（终点），
  **`token[1]` 被忽略**（按位置看应是 `-->`）；秒 = `h*3600 + m*60 + sec + msec/1000`。
* 之后是**索引行**（`intValue()`）+ 若干文本行；`@@@|` 前缀行 → `SubtitleElement.misc` 追加元素；
  文本行按 `" \n "` 连接；**文件头两行被 `readString()` 丢弃**（第 2 行只打日志 `#1 s=…`）。
* 查表：`getSubtitleElementFor(t)` 先用 `lastSE` 命中判断，否则**双向游标线性扫描**（`Replay.java:191-242`）。
* `getCurrentSubtitleElement()` = `getSubtitleElementFor(pos() * length())` ⇒ 因为 `pos()` 已是 0..1 归一化，
  乘 `length()` 得到**秒**，正好对上 `.sub` 的秒制时间戳（**不是 bug**，✓ 与 `pos()`/`length()` 的原生实现互印）。

---

## 4. 原生引擎

### 4.1 对象布局（0x50 B，单例 `[0x770fc0]`）

| 偏移 | 类型 | 含义 | 证据 |
|---|---|---|---|
| +0x0C | u32 | `native_version`（`RPLH` 读出，`≤ 0x10100`） | `0x42aae0` 比较 |
| +0x10 | f32 | 时间基（`setTime` 里 = `C − t`） | `0x428e1d` |
| +0x14 | f32 | 结束时刻 = `length + time_base` | `0x428e26` |
| +0x18 | f32 | **当前时刻（秒）** | `0x428e2b`；`pos()` = +0x18/+0x1C |
| +0x1C | f32 | **总时长（秒）** | `length()` @`0x4280fb` |
| +0x20/+0x28 | ptr | 被录制的资源（+0x28 是资源 id；`& 0xffff0000 == 0xffff0000` 是「无资源」哨兵） | `0x4282dc-0x4282f5` |
| +0x34 | list | **对象链头**（节点 +0x04 = next） | `0x428e30`、`0x428ea0` |
| +0x3C/+0x44 | list | 记录链头/尾 | `0x42aa97-0x42aaa0` |
| +0x48 | u32 | 低字节 = **模式**；bit `0x100` = 正在 seek | `0x4280cb`、`0x428e12` |
| +0x4C | u32 | **对象 id 计数器** | `0x42aaa6` |

**对象节点**（0x8C B）：`+0x04` next / `+0x18` 资源链（+8 = next）/ `+0x24` kind（**从文件读入 = 2**，录制时写 0 或 5）/
`+0x30` **id**（`rplID/instID/playObject/removeObject/flagObject/objectMode` 全按它匹配）/
**`+0x4C` 帧链头** / `+0x60` 当前帧节点缓存（其 `+0xC` 是 f32 时间）。

### 4.2 时间与 seek（`0x428de0` = setTime 核心，✓）

```
if |engine+0x18 − t| < ε(0x6e7df0) → return 0        # seek 死区：目标与当前几乎相同就什么都不做
engine+0x10 = C − t ;  engine+0x14 = engine+0x1C + engine+0x10 ;  engine+0x18 = t
engine+0x48 |= 0x100                                  # 标记「seek 中」
for node in 对象链 where node+0x24 == 2:
    用缓存帧节点(node+0x60)+0xC 与 t 比较，必要时重定位到帧链头(node+0x4C)
    0x428ae0(node, t, 1)                              # 应用该帧
engine+0x48 &= ~0x100
```

* **`seekAbs(F)` @0x429920**：形参是**归一化 0..1**（`目标 = engine+0x1C × arg`，`0x429943-0x429953`）。
* **`seekRel(F)` @0x4298e0**：形参是**秒**（`目标 = engine+0x18 + arg`）。
  ⇒ **两个 seek 单位不同**，是原生实现的既成事实；重制时不要「统一」。
  `Play()` 用 `seekAbs(0.0)` 回零、`enterCallback()` 用 `seekRel(0.01)` = +10 ms。
* 时间基被重设（+0x10/+0x14）意味着**帧时间戳是相对当前 seek 原点的**：这是理解录制数据的关键。

### 4.3 25 个原生方法（`out_native_methods.csv` + 本轮补 `seekRel`）

注册表在 `0x42acb0-0x42afc0`，形状 `0x652910(cls, name, sig, fn)`（✓ `tools/replay_reg.py` 逐项解出，
名字/sig 字符串实测）。完整表见 `out_replay_spec.json`；要点：

| 组 | 方法 | 备注 |
|---|---|---|
| 生命周期 | `create_native`@0x42ab70 / `delete_native`@0x42ac20 | 分配 0x50 + 绑 GameRef；`delete` 需成对，否则内存泄漏 |
| 模式 | `record`@0x427f40 / `play`@0x4297e0 / `ghost`@0x427ff0(未接线) | |
| 状态 | `clear`@0x429830 / `reset`@0x429d20 / `stop`@0x429860 | 分别落到 0x4283b0 / 0x429aa0 / 0x428740 |
| 文件 | `save`@0x429890 / `load`@0x42ac60 | 走 §3.2 容器 |
| 查询 | `native_mode`@0x4280b0 / `length`@0x4280e0 / `pos`@0x428110 | 见 §4.1 |
| 寻址 | `seekAbs`@0x429920 / `seekRel`@0x4298e0 | 见 §4.2 |
| 对象 | `recordObject`/`stopObject`/`playObject`/`removeObject`/`flagObject`/`objectMode`/`rplID`×2/`instID`/`setInst` | 全部按**节点 +0x30 的 id** 操作对象链；`recordObject` 经 `0x434810(mgr 0x771050, res, 0x4B, 0)` 查表后返回 `[eax+0x30]` |

### 4.4 顺带解掉 docs/48 的两个未解项（★）

1. **`setEventMask` 是覆盖还是累加** —— 答案：**累加**。`setEventMask` @0x421700 → 核心 `0x42b650`：
   `or edx, ecx; mov [base+0x88], edx`；`clearEventMask` @0x421770 → 核心 `0x42b6b0`：
   `not ecx; and edx, ecx`（清除位）。掩码存在对象的 `+0x88`（经类型 vtable 偏移表 `0x7439b0` 索引）。
   ⇒ `Replay.Play()` 里那次 `setEventMask(EVENT_COMMAND|EVENT_HOTKEY|EVENT_TIME)` **只加不减**，
   进回放前的掩码位依然有效。

---

## 5. 入口与 UI 流程

### 5.1 回放文件浏览器 `FilePopup`（`FilePopup.java`，✓ 行 64-249）

* 构造 `FilePopup(path, mask, mode)`。回放用途的三处调用：
  `mainMenu.java:463` = `("save\replays\", "*.rpl", 0)`；`ReplayWindow.java:343` = mode 2；
  `ResultsWindow.java:138` = mode 2（赛后存盘）。
* 字符串表（`FilePopup.java:2`）：`"$6|Back"`、`"$5|Delete"`、`"$4|Save actual"`、`"$3|Load"`、
  `"$2|Play actual"`、`"$1|Replays"`、`"$8|Last"`、`"$7|Selected"` ⇒ 它是**通用文件浏览器**，「Replays」只是它的标题。
* 开窗时用 `java.io.FindFile.first(path+mask, FILES_ONLY)` 遍历，**只收 `Replay.canLoad()` 通过的**文件
  ⇒ 列表本身就是合法的 `.rpl` 清单（旧 `0x01050000` 版本的录像也能列出来）。
* `Save` / `Actual` 按钮**仅当** `Gamelogic.replay.length() != 0 && replay.isReplay` 时可用（`81-88`）。
* `Load_onAction`（`113-124`）：`changeScreen(StartWindow)` → `replay.Clear()` → **`new Replay()`**（换新实例）→
  `Load(path+name)` → `Play()`。
* `Save_onAction`（`126-151`）：`StringPopup` 要名字 → **`path + name + ".rpl"`** → `canSave` 检查重名 →
  `Replay.Save()`，返回 0 就 log `"save replay - failed"`。
* `Actual_onAction`（`105-111`）：mode 2 时 `close(10)`，否则 `replay.Play()`
  ⇒ **mode 0/2 的区别就是「赛后用」还是「独立浏览器用」**。★ **mode 2 的完整闭环已打通**（✓ 三段代码对得上）：

  ```
  ResultsWindow.viewReplay（TextButton，313,215 140×26，Caption 却写作 "$5|Save replay"，onAction=viewReplay_onAction）
    → new FilePopup("save\replays\", "*.rpl", 2).openPopupModal(results)
    → 用户点「Play actual」→ close(10)
    → ResultsWindow.viewReplay_onAction: if (ret == 10) this.close(4)
    → 调用方 Track.openIngameMenu 的 case 4: changeStatus(GST_MENU); Gamelogic.replay.Play();   ← Track.java:1085-1091
  ```

  ⇒ **赛后面板那个按钮既是「存这局回放」也是「立刻看这局回放」**：点 Save 落盘，点 Play actual 直接进回放。
* 默认文件名（`StringPopup.java:40-53`）：`replay.getMapName()`（长度 >18 截到 17）+ `"-"` + 递增序号，
  空格换成 `_`，并且用 `do{…}while(File.exists("save\replays\"+名+".rpl"))` **反复换号直到不重名**。
* 每行卡片 `TabList3_onUpdate`（`209-223`）调 `Replay.getInfo()` 取时段预览图 `setTODPreview`；
  选中时 `setReplayFileInfo` 填「地图 / 赛道 / 时段 / 模式」四个标签（`241-248`）。

**主菜单入口**（`mainMenu.java:25/123/426/452-463` ✓）：`this.replayButton`（`IconButton`），悬停提示 `"$5|Replays"`，
点击音 `garage\Menu7-Replay.evt`；**前提是先有生涯存档**：`if (curSaveSlot == 0) { messageBox(1, "$7|Please load or create a career first."); return; }`
然后才 `new FilePopup("save\replays\", "*.rpl", 0)`。主菜单屏本身由 `Pub.backToGarage()`（`Pub.java:75-77`）挂上。

### 5.2 命令行直接放录像（`Gamelogic.java:347-349`、`466-503`，✓）

开关是 **`playback=<名字或路径>`**（`local5.equals("playback")` ⇒ `commandLineReplayName = token(1,"=")`）。
载入顺序（逐个 `canLoad` 试探，前一个成功才不试下一个 —— 判定用 `replay.length() <= 0`）：

```
<name> → <name>.dem → <name>.rpl → save\replays\<name> → save\replays\<name>.dem → save\replays\<name>.rpl
```

全失败 → `actualWindow.messageBoxWait(2, "The requested file cannot be loaded.")` + `changeStatus(GST_SHUTDOWN)`；
成功 → `replay.Play()`。同族开关还有 `alias=<名字>`（载 `save/career/<名字>.sav`，与存档线相接）。

> 这说明 **`.dem` 也是合法容器**（只被读、从未被写；全库仅 `Gamelogic.java:472/488` 两处出现），
> 是开发期遗留的「demo」扩展名。

### 5.3 回放加载链 `Track.enterToReplay(ReplayWindow, Viewport)`（`Track.java:2394+`，✓）

`Play()` 把播放屏建好后就交给 `Track`：

1. `this.rwindow = rwindow`；`Input.cursor.enable(false)`（**隐藏鼠标指针**）；
2. `new Navigator(); nav.init(this, map, trackId, rwindow.getMiniMap(), Config.gpsMode==1 ? MODE_GPS : MODE_WHOLEMAP)`
   —— `getMiniMap()` 返回的就是 §5.4 里那个 `map` 旋转控件；
3. `new Loading(); rwindow.showPopup(loading)`；`Loading` 屏读 **`replay.spline/mapId/TOD/gameModeId`** 显示模式名/规则
   （`Loading.java:127-134`）；`msgDisplay = new String[rwindow.getMessageRows()]`（=3）；
4. `map.prepareTrack(mtr, Gamelogic.replay.TOD)`；`gameMode.initGameMode(this)`；加载进度 `loading.setProgress(map.getLoadPercent()*0.9)`；
5. `changeCam(CMD_CHANGECAM_BUILD)` → **`Gamelogic.replay.enterCallback()`**（= `play(map); seekRel(0.01); timeWarp(0.0)`）→ `waitToStabilize()`；
6. `Sound.changeMusicSet(MUSIC_SET_INGAME)` + `Sound.setVolume(CHANNEL_MUSIC, Config.ingameMusicVolume)`；随后注册镜头热键。

### 5.4 回放播放屏 `ReplayWindow`（501 行，✓ 本轮逐行梳理）

**类身份**：字节码类表实测 `java.game.frontend.ReplayWindow` → **`java.gui.Window`** → **`java.io.HotkeyEventHandler`**
（伪码里没有 `super`/`implements` 行，是重建产物）。全屏 800×600，自持一个 `View3D` + 底部菜单条。

**屏幕字符串表**（`ReplayWindow.java:2`）：`{"00:00:00:000", "00:00:00:000", "/", "Cameras", "Cars"}`
（两个时间码 Label 的 Caption、`Per` 的 `/`、`CameraSwitch`/`CarSwitch` 的 ToolTip）。

**控件树**（布局从 `:73-100` 的编码块用 `tools/ui_layout.py` 解出，坐标为原样数字）：

| 控件 | 类 | 位置/尺寸 | 作用 |
|---|---|---|---|
| `Window1` | Window | 0,0 800×600（`Visible=0`） | 根窗，`onAnimate=Window1_onAnimate`（每帧刷新时间码 OSD） |
| `menuBack` | Component | 0,526 800×74 | 底部菜单条底板（隐藏时 `setTop(getHeight())`） |
| `menuline` | Component | 0,0 800×74 | 菜单条贴图（`GUI_02.png`） |
| `quit` | IconButton(`gui_menubuttonsound`) | 359,20 50×45 | `$7|Exit.` |
| `PlayPause` | IconButton | 8,28 44×34 | `$1|Play / Pause`，四态 UV 由 `PlayPauseChange()` 覆写 |
| `Save` | IconButton | 311,22 45×40 | `$6|Load / save a replay.` → `new FilePopup("save\replays\","*.rpl",2)` |
| `MovieSlider` | **HSlider**(`gui_grey`) | 0,0 **800×10**，**Max=1.0** | 时间轴；`onChanged` → `replay.seekAbs(v)` |
| `FullMovieTime` / `ElapsedMovieTime` / `Per` | Label(`#ReplayMenu#`) | 404,21 / 273,21 / 387,21 | 时间码，初始全 `Visible=0` |
| `ScreenShot` | IconButton | 259,20 50×45 | `$5|Take a screenshot.` |
| `CameraSwitch` | IconButton | 136,21 50×45 | ToolTip `Cameras`，`$3|Change the camera view.` |
| `CarSwitch` | IconButton | 190,20 50×45 | ToolTip `Cars`，`$4|View other players.` → `replay.changeCarTarget()` |
| `Embedded1` | Embedded → `java.game.frontend.infoComponent` | 464,18 336×42 | 提示条（`onShow` 里把 `Gamelogic.infoComp` 指向自己） |
| `slomo` | **Rotating** | 63,12 60×60 | 拖拽调速圆盘，`$2|Slow motion control.` |
| `Component1` | Component | 432,23 7×40 | 竖分隔条 |
| `View3D1` | View3D | 0,0 800×600 | 3D 视口（`onHide` 里 `replay.Clear()` + `track.exit()` + 关 NameTAG） |
| `map` | Rotating | 5,330 168×188 | `getMiniMap()` 的返回值，给 Navigator 当小地图 |
| `CurrentLap` + 9 个数字板 | Component ×10 | `CurrentLap` 327,13 146×22；数字板相对父级 `Top=1`、17×18，`Left` = 0/18/32/46/64/78/92/110/128 | 时间码数字板（贴图 `frontend\textures\positionplate.png`），10 个名字依次是 `MinNumber1OnCurrentLap`、`MinNumber2OnCurrentLap`、`kettospontOnCurrentLap`、`SecNumber1/2OnCurrentLap`、`DotOnCurrentLap`、`HSecNumber1/2/3OnCurrentLap`（= 分十/分个/冒号/秒十/秒个/点/毫秒百/十/个，与 §5.4 `getTimeNumbers` 的 8 元素对位） |

> ✓ 上表的**每一个坐标/尺寸/类名都来自 `out_ui_layouts.json` 的 `ReplayWindow` 布局 28 条记录**（`tools/ui_layout.py` 机械解码，非人工转录），
> 控件类 id：`Window`=2、`Component`=6、`Label`=8、`IconButton`=37、`View3D`=39、`HSlider`=53、`Embedded`=56、`Rotating`=63。
> ⚠ 布局里 `View3D1`/`map`/`menuBack` **没有任何 `onX` 绑定**（只有 `Window1.onAnimate`、`MovieSlider.onAnimate/onChanged`、
> `slomo.onMouseMoved` 与各按钮 `onAction`）⇒ `View3D1_onHide` / `View3D1_onShow` / `map_onShow` 这类方法是被**基类在窗口隐藏时按约定回调**，不是布局绑定。

**输入**：没有 `onEvent`/`keyDown` 覆写，全靠控件回调 + 热键。

| 输入 | 行为 |
|---|---|
| `ESC`（`Hotkey(RCDIK_ESCAPE, KEY, HOTKEY_RELEASE, cmd=0)`） | `menuvis = !menuvis`，菜单条在 `getHeight()` / `getHeight()-menuBack.getHeight()` 之间来回 ⇒ **只收起/展开底部菜单条** |
| `9`（仅 `Config.majomParade`，`cmd=1`） | 截图（`ScreenShot_onAction(null)`） |
| 进度条拖动（`MovieSlider_onChanged`） | `replay.seekAbs(v); replay.seekpos = v;`，且若当前是车内视角（`camMode < CMD_CHANGECAM_TV=7`）则 `changeCam(CMD_CHANGECAM_INT_HEAD=1)` → `changeCam(原 camMode)` **重算镜头**；记 `lastMouseLeftUpTime` |
| 圆盘拖拽（`slomo_onMouseMoved`） | 顺时针拖动算角度，夹在 **0.2 ≤ slomoAngle ≤ 6.0**；`timeWarp(slomoAngle/6)`（<0 加 2π、>2π 减 2π）；速度倍数 `int(slomoAngle/6)` 显示成 `$10|Speed multiplier: N` |
| 点 `PlayPause` | `if (replay.seekpos >= 1.0) replay.seekAbs(0.0);` 再 `PlayPauseChange()` |
| 点 `quit` | 见下 |

> ⚠ **`playing` 字段名与语义相反**（照字面）：`if (playing)` 分支做的是「暂停」（UV 换成暂停帧、`setToolTip("Pause")`、
> `replay.end = false`、`timeWarp(slomoAngle/6)`），`else` 分支才 `replay.end = true; timeWarp(0.0)`。
> `Replay.handleEvent` 里 `end == false` 才继续推进 ⇒ 该窗口里 `playing == true` 表示**已停/暂停**。

**播放控制汇总**：`MovieSlider_onAnimate` 每帧 `setValue(replay.seekpos)`（≥1.0 时钉在 1.0）；
`Window1_onAnimate` 每帧 `HUD_Interface.setTimeOnHUD(getTimeNumbers(replay.length() * replay.seekpos), timecomp)`
⇒ **OSD 当前时刻 = `length() × seekpos` 秒**（`getTimeNumbers` 返回 8 元组：符号 + 分十/个 + 秒十/个 + 毫秒百/十/个）。
`EndChange()`（由 `Replay.handleEvent` → `rwindow.setEndMovie()` 触发）设 `playing=true, end=true`，并把 `ElapsedMovieTime` 钉成
`timeToString(replay.length())`。**`FullMovieTime` 的 Caption 全程是静态 `00:00:00:000`**（伪码里没有 setCaption）⇒ ✗ 总时长显示逻辑缺失。

**退出路径**（`ReplayWindow.java:403-414`，✓ 逐行）：

```java
if (Gamelogic.commandLineReplayMode) System.exit();      // 命令行 playback=<file> 模式：直接退进程
else { replay.active = false; timeWarp(1.0); replay.stop(); Gamelogic.useNetwork = true;
       changeScreen(new mainMenu(), 0); close(); }        // 正常：回主菜单
```

⇒ **退出目的地唯一 = 主菜单**；`EXIT_TO_PRACTICE`/`exitTo` 是死代码（见 §2.1）。
另：`View3D1_onHide` 里 `replay.Clear()` + `gameMode.track.exit()` + `NameTAG_Window.hide()`；
`Track.java:1327` 的 `case 50:` 会调 `rwindow.changeOsd()`（= `vis = !vis`，而 `vis` 在窗口内**无读点** ⇒ 用途不明，可能被原生读）。

**截图**（`:293-306` + `:469-475`）：先把 `menuBack`/`map`/`CurrentLap` 移到画面外 → `sleep(100)` →
`GfxEngine.vblank.wait()` ×2 → `screenshot()` → 复原位置；`screenshot()` 里 `timeWarp(0.0)`、
播 `sounds\screenshot.wav`、`GfxEngine.printScreenIndexed("screenshots\shot")` 取文件名、再恢复 `timeWarp(slomoAngle/6)`、
提示 `$8|Screenshot saved as '<name>'`。

**✗ 重建残缺**（方法在字节码里存在但伪码无体、或布局里找不到绑定）：
`Options_onAction`、`Hide_onAction`、`Loop_onAction`、`DoubleSpeed/NormalSpeed/HalfSpeed/QuarterSpeed_onAction`
（四档速度的**实现逻辑在伪码里有**：`timeMul=2.0/1.0/0.5/0.25` + `timeWarp(...)`，但**布局里没有任何控件绑定它们**）、
`View3D1_onShow`、`setCounter`、`setDebugCounter`、`displayMessage`；字段 `waiting1Frame`、`offset`、`dir`、`vis`（只在 `:494` 取反）同理。

---

## 6. 与其它文档的接口

| 接点 | 说明 |
|---|---|
| docs/48 §状态机 | 回放走 `GmReplay`（0 圈 0 对手）；`GST_*` 状态机不参与回放内部流程 |
| docs/48 timer id | 回放用 timer id **0（播放心跳）/ 1（结束心跳）0.1 s**；与 docs/48 的 timer 表（13/14/15/1001/10/3/0/1）一致 |
| docs/48 事件位 | `EVENT_TIME / EVENT_COMMAND / EVENT_HOTKEY`；`setEventMask` 语义已定案（§4.4） |
| docs/49 前端 | `FilePopup` / `ReplayWindow` / `ResultsWindow` / `mainMenu` 四个屏；`FilePopup` 是通用文件浏览器，回放只是其中一种 mask |
| docs/50 数据层 | 回放头字段全部来自 `MetaServer` room parameter（map/spline/TOD/gameMode/driver），不是 Track 字段 |
| docs/53 网格/材质 | `addObject` 用 `getBoneId("bone00")` 造 3D 名牌 ⇒ 车模/司机模有骨骼命名，可用于挂点 |

### 6.1 顺带结论：**LASR 没有骨骼动画系统**（类清单实证）

全库 2216 个伪码类里，名字含 `anim/skel/bone/joint/morph/keyframe/pose` 的只有 **6 个**：

| 类 | 体积 | 性质 |
|---|---|---|
| `game/frontend/Anim` | 6.8 KB | **UI 动画**（菜单过渡） |
| `game/frontend/Animator` | 2.3 KB | UI 动画驱动 |
| `gui/Animator1CH` | 0.7 KB | UI 动画（单通道） |
| `gfx/Animation` | 162 B | 桩/枚举级 |
| `game/frontend/AnimState` | 55 B | 状态常量 |
| `util/BoneAssign` | 131 B | 骨骼挂点赋值（与 `getBoneId` 配套） |

⇒ 没有骨架 / 动作剪辑 / 蒙皮 / 关键帧系统：**车辆是「刚性零件网格 + 骨骼挂点」拼出来的**
（零件表 `docs/50`、网格导出 `docs/52`、材质绑定 `docs/53` 都已覆盖），
车轮/指针这类运动靠直挂变换。重制时**不需要**移植动画系统，但需要保留骨骼挂点命名
（至少 `bone00`，见 §2.5 名牌）。

---

## 7. 未解清单（✗）

> 状态说明：★ 表示**本轮用真实样本推进**；已关闭的项直接写结论，未关闭的写「需要什么」。

| # | 项 | 状态 / 需要什么 |
|---|---|---|
| 1 | ~~`RPLO` 的 `len` 恒为 4 而负载更长~~ | **已关闭**（§3.3）：`len=4` 就是紧随其后的资源类型码长度，块体自描述 |
| 2 | 每对象负载的字段级格式 | **已关闭**（§3.3 + §3.3.1）：41 B Java 头 + 原生 version/帧数/帧/额外列表；**帧内字段全部解出并逐帧验证**（时间戳+坐标+四元数+双掩码+轮数据）。仍 ✗ 的只是**语义**（见 #17/#19/#20），结构不用再查 |
| 3 | ~~帧采样率 / 帧节点字段集~~ | **已关闭**：帧头 +0 = f32 秒；476 帧 `0.0→52.6581`、dt 中位 0.1009 s（≈10 Hz）。rec2 的 519 帧不是「另一采样率」而是它自己的记录长度 |
| 4 | `.dem` 的实际格式 | 全库只读不写；与 `.rpl` 是否同族未验证（`canLoad` 会试 `.dem`） |
| 5 | `version 0x11070000` 的 `case` 体为空 | 疑似结构化重建吞掉（规则 2），但无法从伪码自证 |
| 6 | ~~「回放介质」商品门控位置~~ | **已关闭**：用户实测**游戏里没有商店机制**，回放功能直接可用；`CommonStrings.BUY_REPLAY` 全库零使用者 ⇒ 是**未完成的遗留文案/道具**（`IExtra.REPLAY` 仍在道具表里，但无任何门控）。重制**不需要**做这个限制 |
| 7 | `MODE_GHOST`/`ghost()` 的原始设计 | Java 层零调用（结论已确认）；原设计意图只能猜 |
| 8 | `getSubtitleElementN(int)` 用 `lastSEindex` 而非形参 | 疑重建错位或原始 bug |
| 9 | `handleEvent` 的 `GameRef` 形参来源 | 事件从哪个对象广播到 `Replay`（原生事件管线侧），需实机确认 |
| 10 | `Gamelogic.changeMap(...)` 的实参↔param 对位 | 5 个 local 全被用满、`local5` 空缺 ⇒ 重建错位嫌疑；**不要照抄**（§2.2）。实机验证法：看 `.rpl` 头第 3/4 个 u32（spline / TOD）是否等于实际设置 —— ★ 本样本两者都是 0，**无法区分**（该场没换图/时段），需一场非默认 TOD 的录像 |
| 11 | `ReplayWindow.vis` / `changeOsd()` | `vis` 只被取反、无读点；`Track.java:1327 case 50` 调 `changeOsd()` ⇒ 疑似供原生/HUD 消费 |
| 12 | `FullMovieTime` 总时长 Label 的刷新 | 伪码里无 `setCaption`，全程静态 `00:00:00:000`。★ 实机已验证回放屏行为，但这一项**在实机里也是静态的**（用户未报告总时长显示）⇒ 更可能是原版就没实现 |
| 13 | `playing` 字段语义 | 名字与行为相反（`true` 表示已暂停）⇒ 命名遗留，重制别沿用 |
| 14 | `Config.majomParade` 开关含义 | 控制「9 键截图」与「3D 名牌生成」，原始用途不明（疑开发者彩蛋/调试模式） |
| 15 | `changeCarTarget` 的**双重 +1** | 需**联机**（>2 台车）才能实机验证；单人局只有 2 台车，用户已确认「连点 Cars 正常往返切换」⇒ **单人场景无异常**，字面双重 +1 的跳过行为在 2 车时不可观测 |
| 16 | ★ 参数串 `r` 段语义 | rec2 = 17 个 `0x2007xxxx` 子对象 id，rec1 = 单个 `2048`(0x800)：两者形态不同。且这些 id **在二进制载荷里 0 次出现**（✓ 全文件计数）⇒ 帧数据按索引引用子对象 |
| 17 | ★ 参数串 `s 32` 与 blob 里的 `u32 9` / `0x01040000` | 三个常量字段的语义未定（`s` 与 `r` 表容量疑有关） |
| 18 | ★ SDAT 的 `0x00030100` 与尾 12 B（`00×8 + u32 8`） | 四种存档文件里**完全相同**，疑为容器版本 + 「索引/对齐」字段；语义未定，但不影响读写（按常量处理即可） |
| 19 | ★ mask2 的 6 个量化字节（槽 0–5） | 「非 0 才写」的 6 个通道，出现频率差异大（玩家：槽 2/4 恒在、槽 3 罕见、槽 5 从不）；与速度/偏航相关性均 ≤ 0.71 ⇒ 需**另一段录像**（急刹 / 碰撞 / 打滑）比对才能命名 |
| 20 | ★ 四轮 6 字节里的第 1/2/4/5 字节 | 第 0（轮速）与第 3（横向载荷类）已解；其余四字节 ✗ |
| 21 | ★ mask1 bit2 的 2 字节通道 | 本样本 995 帧**从未置位** ⇒ 需要一段能触发它的录像（疑与某种阈值/打滑状态有关） |
| 22 | ★ 额外列表 8×f32 的语义（仅 AI 车 37 条） | 第 0 列单调增、末 3 列近似单位向量；结构已解（36 B/条） |
| 23 | ★ 引擎角速度的**单位**（rad/s 推断） | 依据 rpm 范围与断油平台推断为 rad/s，未在代码里找到「×9.5493 / ×60/2π」的换算点 ⇒ 中等置信 |
| 24 | ★ mask1 **bit4-7 的 4 位状态字段**（= `[node+0x51]<<4`） | 玩家取值 `{0,1,2,8,9,10}`、AI 取值 `{0,1,2,3,4,8,9,10,11,12}` —— **各 bit 独立出现且可叠加** ⇒ 更像 **4 个布尔标志**（不是枚举）；与姿态无关地逐帧变化，疑为「刹车/打滑/档位/灯」这类离散状态，✗ 未定位到写点 |

## 8. 实机验证结果（✅ 用户已上机确认 2026-09-28）

**已确认（写进结论，不再列为未知）**：

1. ✅ **游戏里没有商店机制**，回放功能**开箱可用** ⇒ 「Replay medium / `BUY_REPLAY`」是**未完成的遗留**（与「零使用者」的静态结论一致）。§7 #6 关闭。
2. ✅ **游戏本体不生成 `.sub`**（用户全盘搜索无命中）⇒ `.sub` 是开发期/手工旁挂文件。§3.4 结论已改。
3. ✅ **`.rpl` 落在游戏根目录 `save\replays\`**，样例 `W_Brightwood_St-1.rpl`（89,531 B）已存档到 `samples/`，
   并已用它校正出 §3.1/§3.3 的全部结构（★ 本轮最大推进）。
4. ✅ **命令行 `playback=<name>`** 行为符合 §5.2（六段试探顺序）。
5. ✅ **赛后 `viewReplay` 按钮**（显示 `Save replay`）→ `Play actual` → 立刻播刚跑完那局（§5.1 的 mode 2 闭环）。
6. ✅ **回放屏逐项**：`ESC` 只收底部菜单条、拖进度条跳转、拖圆盘调速、`quit` 回主菜单、
   主菜单 `Replays` 无生涯存档时弹提示、`ScreenShot` 落盘。
7. ⚠ **`Cars` 连点无法验证「跳过一台车」**：单人局只有**两台车**（玩家 + 一名对手），连点只在两台车之间正常往返；
   联机模式用户也无法实测 ⇒ §7 #15 保持开放，但**单人场景无异常**。

**仍需要你上机的只剩一件**：

* 若以后跑一场**改了时段（TOD ≠ 0）或不同赛道**的比赛并存档，把 `.rpl` 发我 —— 那能顺带验证 §7 #10
  （`changeMap` 的实参↔param 对位：`.rpl` 头的 spline/TOD 字段是否等于你实际选的）。
  本样本这两项都是 0，无法区分。

---

## 9. 重制落地建议

1. **数据侧**：录像 = 「24 B 头 + 分块容器」。容器 tag 词表只有 3 个且未知 tag 可跳过，
   重制可直接用**同名容器 + 自定义 RPLO 负载**；但**逐字段负载格式现已全部解出**（§3.3.1 帧布局 +
   §3.3.2 语义），所以重制也可以**直接读原版 `.rpl`**——两条路都通，见下一条。
2. **幽灵车**：原版没接线，重制要「最佳圈影子车」是**新功能**；数据模型已经现成
   （对象链 + 帧链 + 时间基），照 §4.1/4.2 直接实现即可。
3. **回放 UI**：`FilePopup(path, mask, mode)` 是通用文件浏览器（回放只是 `*.rpl` 的用法），
   重制时可复用为「录像列表 + 预览信息」组件；`ReplayInfo` 的 4 个标签 + TOD 预览图就是列表行要显示的全部内容。
4. **兼容性**：`canLoad` 只认 3 个版本号 + `MAP_PRID` 位 ⇒ 重制若要读老录像，必须保持
   `0x01080000` 头布局与 `MAP_PRID` 位约定。
5. **重制侧已落地（★ 本轮）**：录像已进 `remaster/` 数据层——
   - `remaster/data/replay.json`：格式规格（容器/分块/车辆块/帧布局/帧长公式/播放建议）
     + 已验证的帧内语义表 + 样本索引（**引擎实现读档只需这一个文件**）；
   - `remaster/tools/rpl_read.py`：自包含（stdlib only）读取器，含 `sample_state()`
     回放插值（线性位置 + 四元数 slerp），可直接移植到引擎侧；
   - `remaster/samples/replay_W_Brightwood_St-1.json`：995 帧逐帧时间线（列 = `format.timeline.columns`）；
   - 校验：`remaster/tools/validate.py` **37 项全通过**，其中 8 项专测录像/幽灵车——
     零残差 / 时间线自洽（帧数·单调·`|q|=1`·10 Hz）/ **与 `tools/rpl_parse.py` 逐帧全等** / 插值抽查 /
     几何对上赛道 / 切圈里程互校 / 发车格对位 / ghost 文件自洽。

## 10. 幽灵车：从录像切圈 → ghost 文件（★ 本轮落地，`remaster/tools/replay_laps.py`）

原版幽灵车**代码齐全但零调用点**（§6/§9.2），所以重制要把它当**新功能**做。缺的其实是这条链：

```
.rpl 录像（姿态时间线）→ 车在赛道上的进度 s → 切圈 → 单圈 ghost → 计时赛里回放当影子车
```

### 10.1 赛道识别：拿录像轨迹去和 spline 库几何对拍（`identify_track`）

判据要**两条一起用**，只看「离中心线的中位距离」会选错（同一条路的 `_normal/_slow/_fast/_rescue`
变体彼此只差 0.15 m）：

| 判据 | 本例结果 |
|---|---|
| **在路内比例**（离中心线 <8 m 的帧占比） | `maps/suburban/Track_00.spl2` **100.0%**（995 帧全中）；次优 `_slow` 也 100% |
| **车头 · 路线切向**（用四元数算车头，与样条 `dir` 点乘） | **−0.98**（两车一致）；其它图 0–6% 覆盖 ✗ |
| 交叉印证 | 该赛道的显示名是 **`$1|W Brightwood St`**，而录像文件名正是 `W_Brightwood_St-1.rpl` ✓ |

★ **重要坑：样条的 s 增大方向与行车方向相反**（车头·切向 = −0.98）。所以进度不能直接用 s 的增量，
要按 `u = (起终点线 s − s) mod L` 算「行车里程」再解绕。

### 10.2 切圈算法（`extract_laps`）

1. **起终点线**：用赛道数据的 `start_point`（= 检查点 0）投到主路线上的弧长 —— 本例 **s = 58.7 m**。
   ✗ **不能**用「路线 s=0」当线（本例发车格在线后 8.3 m，用 s=0 切会把线切错）。
2. **投影必须局部搜索**（围绕上一帧 s 的 ±80 m 窗口）：全局最近点在折返/近邻段会翻面，
   症状是「总里程 3703 m」而录像里速度上限只有 12.7 单位/s ⇒ 一眼假。
3. **里程互校**（两条独立路径必须一致，否则说明投影还在翻段）：

   | 车 | 投影弧长 | 记录速度通道积分 | 偏差 |
   |---|---|---|---|
   | Niko（玩家） | 486 m | 480 m | **1.26%** |
   | Willy（AI） | 1216 m | 1220 m | **0.32%** |

4. **切段结果**（这一段录像：52.71 s，10 Hz）：

   | 车 | 第 1 段（发车格→起跑线） | 第 2 段（真正的比赛圈） | 完整圈 |
   |---|---|---|---|
   | Niko | t 0→6.87 s，8 m（0.5%） | t 6.87→52.66 s，477 m（**29.7%**） | ✗ |
   | Willy | t 0→6.46 s，9 m（0.5%） | t 6.46→52.66 s，1207 m（**75.0%**） | ✗ |

   ⇒ **这份录像里没有完整圈**（会话在 52.7 s 被截断），所以样本 ghost 全部标 `complete: false`。
   链路的正确性靠上面第 3 条的里程互校 + ghost 自洽校验保证，与「有没有完整圈」无关。

### 10.3 顺带钉死的一条数据事实：发车格锚点 vs 车身参考点

录像首帧位置 vs `tracks.json` 的 `start_grid`（**跨两个独立数据集**）：

| 车 | 水平偏差 | y 差 |
|---|---|---|
| Niko（slot 0） | **0.006 m**（3 毫米级） | +0.269 |
| Willy（slot 1） | **0.005 m** | +0.290 |

⇒ 水平面完全重合（3 mm 级），y **系统性地高约 0.28 m** —— 这不是误差，而是「发车格锚点（轮胎着地/出生点）」
与「录像里车身参考点」的固定高度差。重制摆放车辆时用它对齐即可。

### 10.4 ghost 文件（重制侧格式）

产出在 `remaster/samples/ghost_<map>_<track>_<car>_lap<N>.json`，自描述：

```json
{ "source": {"recording": "...", "md5": "...", "car": "Willy", "slot": 1},
  "track":  {"route": "maps/suburban/Track_00.spl2", "track": "suburban/track0",
             "name": "$1|W Brightwood St", "length_m": 1608.8, "start_line_s": 58.74},
  "lap":    {"index": 2, "complete": false, "coverage": 0.75, "lap_time_s": null, "distance_m": 1207.1},
  "playback": {"frame_rate_hz": 10.0, "interpolate": "位置线性 + 四元数 slerp",
               "columns": ["t","s","x","y","z","qx","qy","qz","qw","rpm"]},
  "frames": [[0.0, 0.0, -281.5, 117.4, 77.0, 0.006, -0.7, -0.003, 0.714, 488.0], "..."] }
```

回放规则：**10 Hz 采样必须插值**（`remaster/tools/rpl_read.py` 的 `sample_state()` 已实现位置线性 + 四元数 slerp），
计时赛里每帧按 `elapsed` 采样姿态即可；完赛比较 `lap_time_s` 决定是否覆盖保存。

### 10.5 重制实现清单（幽灵车）

1. 计时赛/练习赛开赛：读 `ghost_*.json`（或自己用 `rpl_read` 读原版 `.rpl`）。
2. 每帧 `sample_state(elapsed)` → 生成**无碰撞、无物理、无 AI** 的幽灵实体（原版 `MODE_GHOST` 就是这个语义）。
3. 完赛后：`lap_time < ghost.lap_time` ⇒ 覆盖保存（用 `replay_laps` 重新切这一圈产出新 ghost）。
4. 注意：原版录像**打开后不能再另存**（`isReplay` 语义，§2.6）——重制别继承这个限制。
