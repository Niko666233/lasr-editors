# 49 · 前端 / UI 层规格（gui 控件库 + 布局数据格式 + 窗口流程）

> 目标是「重制时怎么把菜单/HUD 摆出来、按什么键去到哪」这一层。上一份 `docs/48` 管一局比赛怎么跑，
> 本份管它周围的所有界面。证据来自 `out_pseudo/java/classes/{gui,game/frontend}`（2224 类里的 139 个）
> 与 `LASR.exe` 原生代码（UI 布局解析器，本轮新逆出）。
> 约定：**✓** = 本轮已回原文/原生码复核；**✗** = 未解；数字给确切值。

---

## 1. ★★★ UI 布局数据的二进制格式（本轮完全逆出，含工具）

**这份格式此前 48 份文档零覆盖，而游戏里所有界面都由它定义** —— Java 前端里每个控件都是：

```java
this.Label1 = new java.gui.Label();          // （伪码里是 <i>() / <init>() 中的字段初始化）
this.Label1.construct(window, stringTable, "IEAAAAAAAHAABAAAAIEMGBGCGFGMD...");   // 第 3 参 = 布局块
```

第三个参数是 **十六进制文本**（字母表 `A=0, B=1, … P=15`，两位一字节，大写）。共享工具：
**`tools/ui_layout.py`**（本轮新增）→ 解出 `out_ui_layouts.json`（**1058 个布局全部解析成功**，值全部合理）。

### 1.1 格式规格

```
u32  size        # = 整块字节数 − 4        （1058/1058 校验通过 ✓）
u16  version     # 恒为 7
u16  0x0010      # 恒为 16
u8   kind        # 控件类型号（见 §3）
cstr name        # 控件名 = Java 里的字段名（"Label1" / "TextButton1" / "maps" …）
cstr template    # 模板 / 皮肤名，可为空（"gui_button" / "plexi_white_nohead" / "" …）
prop*            # 属性表
0x00             # 属性表结束（其后可能是若干 0 填充，不保证整块 4 字节对齐）
prop  := cstr name | u16 type | payload
```

**type → 载荷**（由原生解析器的类型跳转表读出，见 §1.2）：

| type | 载荷 | 含义 | 例 |
|---|---|---|---|
| 1 | 4 字节 int | 整数属性 | `Align`, `Priority` |
| **2** | **4 字节 float** | 浮点属性（位置/尺寸） | `Left=3.0`, `Width=60.0` |
| 3 | cstr **+ 4 字节** | 名字 + 附加整数（version ≥ 7 才有后半段） | |
| 4 | 4 字节 | 颜色（ARGB int） | `Background.Color_Inactive = 0xAAFFFFFF` |
| 5 | cstr | 贴图路径 | `gui\textures\frame\gui_ingamefader.png` |
| **6** | **16 字节 = 4×f32** | UV / 颜色向量 | `Background.UV_Inactive` |
| 7 | cstr | **回调函数名**（Java 方法名） | `onAction` → `"Back_onAction"` |
| 8,9,10,11,15,16,17 | cstr | 名字引用（模板/资源/字形等） | `Template` → `"gui_button"` |
| 12,13,14 | cstr **+ 4 字节** | 文本 + 附加整数 | `Caption` → `"$3|Cancel"` |
| 0 / >17 | cstr | 未列入跳转表 ⇒ 走同一个通用字符串分支 | |

**属性名与 `gui/*` 类的 setter 同名**（`Background.Color_Inactive` → `Background.setColor_Inactive(...)`，
`Frame.BorderTop` → `Frame.setBorderTop(...)`，`onAction` → `Component.setonAction(comp, "名字", 0)`），
且带 **`对象名.属性`** 的点号前缀（`Background.` / `Frame.` / `Template`）；属性名里出现 `'.'` 时解析器会切换
子对象（原生码里 `cmp al, 0x2e` = `'.'` 的分支 ✓）。属性名/模板名的高频统计见 `out_ui_layouts.json`。

### 1.2 原生侧证据（怎么确认的）

| 事实 | 证据 |
|---|---|
| `Component.construct(Window,String[],String)V` 是 native | `out_native_methods.csv` → `0x005a0450` |
| construct 只是壳：驻留两个字符串后交给真解析器 | `0x5a0481/0x5a0494/0x5a04a8 call 0x643bf0`（字符串驻留）→ `0x5a04d8 call 0x5d4b20` |
| **真解析器 = 0x5d4b20**（约 6.3 KB，含 SEH 与 0x180 字节局部） | `0x5d4b20` 起，`ret` 在 `0x5d63a0` |
| **类型分派 = 跳转表 `0x5d57a0`（17 项）**，索引 = `type − 1` | `movsx eax, word ptr [esp+0x20]` → `dec eax` → `cmp eax,0x10` → `jmp dword ptr [eax*4 + 0x5d57a0]`（`0x5d4d36`–`0x5d4d45`）|
| 各 handler 的载荷宽度 | type1/2/4 handler 里 `mov eax, 4`；type6 用 `mov eax, 0x10` 且 4 个 `movss` 默认值；type3/12/13/14 先扫 NUL 串再有 `cmp dword ptr [esp+0x1c], 7`（**version ≥ 7 才读那 4 字节**）；其余 handler 只有 NUL 扫描循环 |

### 1.3 怎么用

```bash
PY=<venv>/python.exe
$PY tools/ui_layout.py                    # 全部 1058 个布局 → out_ui_layouts.json（+ 控件类型号统计）
$PY tools/ui_layout.py --class mainMenu   # 单个前端类的布局树（人类可读）
$PY tools/ui_layout.py --kind 54          # 看某类控件（54 = Gauge）
```
重制路线：要么把 `out_ui_layouts.json` 当数据源在新引擎里重建 UI（尺寸/坐标/贴图/回调名全在里面），
要么直接在代码里重写等价布局 —— 两者信息量相同，但 JSON 可当**回归基准**（改完比对）。

---

## 2. `gui` 控件库（70 类）

### 2.1 层次与容器模型
- `gui.Component`（129 行）：所有控件基类。静态 `allRootChild : Vector`（根窗口表）；
  `addChild/remChild`（→ native `addChildN/remChildN`）、`addRootChild/remRootChild`（会同时进 `allRootChild`
  并调 `addRootChildN/remRootChildN`）；`setTemplate(String)` → `new Template(name)`。
- `gui.Window`（342 行）：`show()` = `setFocus(1); setVisible(true); addRootChild(this); nshow()`；
  `showModal()` = `show()` → 给**所有已有 root 窗口** `setLock(this)` → `wait()` → 返回 `modalResult`；
  `showModalNoWait()` 同上但不阻塞；`showModalPopupNoWait(Window)` = 记进静态 `popups` 并设 `myParent`；
  `openPopupModalNoWait(target, 位置常量)` 按 17 个位置常量摆相对位置。
- **位置常量**（`Window` 静态字段，逐字）：`TOPLEFT=1 TOPMIDDLE=2 TOPRIGHT=3 MIDDLETOPLEFT=4 MIDDLETOPRIGHT=5
  LEFT=6 LEFTMIDDLE=7 MIDDLE=8 RIGHTMIDDLE=9 RIGHT=10 LEFTBOTTOM=11 BOTTOM=12 RIGHTBOTTOM=13
  MIDDLEBOTTOMLEFT=14 MIDDLEBOTTOMRIGHT=15 MIDDLEBOTTOM=16 UPPERMIDDLE=17`（另 `WAIT=16`，与 MIDDLEBOTTOM 同值）。
  摆位公式（实测）：`TOPMIDDLE` = `x = (2*left + width)/2 − w/2, y = top + 5`；`TOPRIGHT` = `x = width − w − 5`；
  `MIDDLETOPLEFT` = `x = (2*left+width)/2 − (w/4)*3`（即左三分之一处）… 以此类推，边距常量 **5**。
- `gui.Embedded`（11 行）：**嵌入式渲染容器**（`setCurrentSize`、`getObject`）：HUD 与 3D 预览（`View3D`）
  就挂在这上面（`HUD`、`HUDInfo`、`CarCondition`、`View3D1..5` 都是 kind 39/56，见 §3）。
- `gui.Page` / `PageControl` / `TabList` / `TabListHeaderItem` / `Combobox` / `ComboboxHeader`：
  多页/多标签/下拉的容器族（`setonChanged`、`setcreateCustomRow`）。
- `gui.Frame`（223 行）/`Background`（83 行）/`Gauge`（55 行）/`Rotating`（19 行）/`Cursor`/`Texture`/`TextureUV`/
  `Font`/`Text`/`FormattedText`/`Polygon`/`ViewVideo`/`Smiley`：外观与绘制原语。

### 2.2 回调机制（和引擎事件同一套「按方法名回调」）
`gui.Function(Component, String handlerName, int)` —— 20 个注册接口（`gui/Component.java` + 子类）：

```
onCreate onDestroy onShow onHide onAnimate onCustomLayout onCustomEvent
onMouseMoved onMouseLeftDown onMouseLeftUp onMouseLeftDouble
onMouseMiddleDown onMouseMiddleUp onMouseRightDown onMouseRightUp
onHoverIn onHoverOut onKeyDown onKeyUp onHotkey
```
各控件再加自己的：`Button/TextButton/IconButton/Checkbox/Radiobutton` → **`onAction`**；
`LineEdit` → `onAction`/`onChanged`/`onLangChanged`；`Select/VSelect/HSelect/FCVSelect/FCHSelect` →
`onSelectionChange`/`onSelect`/`onEscape`；`Listbox/Combobox/HSlider/VSlider/HScroller/VScroller/
HProportional/VProportional/Progressbar` → **`onChanged`**；`TabList` → `onSelectionChange`+`onChanged`+
`createCustomRow`；`MasterGameList` → `onQueryBegin`/`onQueryUpdate`/`onQueryEnd`；`Page` → `onEnter`/`onExit`。

⇒ 布局里 `onAction = "Back_onAction"` 就是在 Java 类上回调 `Back_onAction(Component, ...)`。**重制时这张表就是
「UI 事件 → 业务代码」的全部接入点**：官方前端类里所有 `*_onAction`/`*_onChanged`/`*_onShow` 方法都是它的目标。

### 2.3 动画
`gui.Animator1CH`（37 行）：单通道插值器，`Component.setFadeAnimation(Animator1CH)`；
`game/frontend/Anim`（188 行）+ `Animator`（74 行）+ `AnimState` 管前端层的序列动画（`Anim.ONCE` 等 flag）。

---

## 3. 控件类型号 → 类（kind 表，实测反查）

由「布局里的控件名」在 Java 源码里找 `this.<name> = new java.gui.<类>` 反查得到（`tools/ui_layout.py` 自动打印）。
**1058 个布局的 kind 分布与对应类**：

| kind | 类 | 出现 | kind | 类 | 出现 |
|---|---|---|---|---|---|
| 2 | `Window` | 54 | 37 | `IconButton` | 55 |
| 6 | `Component`（通用容器/dummy） | 255 | 39 | `View3D` | 4 |
| 7 | `Button` | 20 | 42 | `TabListHeaderItem` | 18 |
| 8 | `Label` | 347 | 43 | `TabList` | 13 |
| 9 | `HProportional` | 16 | 53 | `HSlider` | 21 |
| 13 | `TextButton` | 116 | **54** | **`Gauge`**（转速/速度表） | 10 |
| 16 | `LineEdit` | 4 | 55 | `VSlider` | 4 |
| 20 | `Page` | 8 | 56 | `Embedded` | 48 |
| 21 | `PageControl` | 2 | 60 | `ViewVideo` | 1 |
| 29 | `Checkbox` | 7 | 63 | `Rotating` | 24 |
| 30 | `Progressbar` | 16 | 64 | `MasterGameList` | 1 |
| 34 | `Combobox` | 13 | | | |
| 36 | `Logview` | 1 | | | |

（`gui/*` 里其余类 —— `Radiobutton`、`Listbox`、`StringListbox`、`IconButton` 之外的按钮变体、
`TabListContainer/Row`、`UserList`、`RoomList`、`MetaList`、`Numeric`、`Group`、`FormattedText`、
`Browser`、`PageControlHeader*` 等 —— 在本版前端里没有直接实例化，属于引擎提供的未用控件。）

---

## 4. UI 文本表（445 条，`out_ui_texts.json`）

每个前端类的 `stringTable` 就是一张 `"$N|文字"` 表，控件 `Caption` 属性写 `"$N|..."` 直接引用（`$N` 即索引）。
32 个类共 **445 条**。摘录（完整表见 JSON）：

- `mainMenu`（27 条）：`$9`=Car repository…、`$13`=Mod your car, tune it to the max.、`$15`=Go measure your skills.
  Find a racer at local rally points.、`$19`=Do you want to see the intro?、`$20`=Are you sure you want to quit?、
  **`$3`=Cheat 2 - Gives all cars.、`$4`=Cheat 1 - Gives all parts to the current vehicle.`**（作弊项在主菜单文本表里）
- `videoOptions`：`$8`=RESOLUTION、`$9`=FSAA、`$10`=GAMMA、`$11`=SHADER、`$12`=TEXTURE DETAIL、`$13`=VIEW RANGE、
  `$14`=WORLD DETAIL、`$17`=SHADOW DETAIL、`$18`=DYNAMIC ENV. MAP.、`$19`=PARTICLE DENSITY、
  `$20`=FOLIAGE DENSITY、`$21`=MOTION BLUR、`$22`=HIGH DYNAMIC RANGE、`$23`=NOISE、`$24`=CONTRAST、
  `$25`=OWN VEHICLE DETAIL、`$26`=OPPONENT VEHICLE DETAIL、`$27`=HEADLIGHT REALITY、`$6`=BENCHMARK
- `soundOptions`：`$8`=MENU MUSIC VOLUME、`$10`=EFFECTS VOLUME、`$11`=ENGINE VOLUME、`$13`=USED CHANNELS、
  `$15`=INGAME MUSIC VOLUME、`$16`=ENVIROMENTAL EFFECTS（原文拼写）
- `gameOptions`：`$5`=GENERAL、`$6`=TRANSMISSION、`$7`=CLUTCH、`$10`=GAME HELPERS、`$12`=ANALOG STEERING、
  `$13`=THROTTLE、`$14`=CLUTCH ON HANDBRAKE、`$15`=CLUTCH ON BRAKING HARD、`$16`=VIRTUAL GEARSTICK、
  `$17`=HEAD MOVEMENT、`$18`=STEER、`$19`=VELOCITY、`$20`=ACCELERATION、`$21`=DAMPING、`$22..$26`=FORCE FEEDBACK
  （REAL/EFFECTS/EMULATED STRENGTH）、`$27`=HELPER INFOS、`$28`=GPS STYLE MINIMAP、`$33`=ANALOG STEERING RANGE、
  `$34`=METRIC SYSTEM、`$35`=SLOW MOTION；`$100`=Manual、`$101`=Auto、`$102`=Semiauto、`$103`=Semiauto2、
  `$110`=Autoclutch、`$111`=Manual clutch
- `controlOptions`：`$13..$35` = ACCELERATE / BRAKE / TURN LEFT / TURN RIGHT / HANDBRAKE / SHIFT UP / SHIFT DOWN /
  CLUTCH / HORN / RESCUE CAR / LOOK BACK / LOOK LEFT / LOOK RIGHT / NEXT MUSIC TRACK / PREV MUSIC TRACK /
  VOLUME UP / VOLUME DOWN / **`$43`=NITRO** / `$36`=CHAT / `$12`=TEST YOUR AXIS HERE；`$9`=RESET、`$11`=APPLY
- 公共页签：`$1`=GAME `$2`=CONTROL `$3`=SOUND `$4`=VIDEO（四个设置窗共用同一套页签前缀）
- `IngameMenu`：`$1`=Repair your wrecked vehicle.、`$2`=Stuck? Wrecked? Gone off the road? No problem, push it!、
  `$3`=Continue game.、`$4`=Options.、`$5`=Exit game.、`$6`=End race.、`$101`=Do you really want to leave the race?
- `PubWindow`：`$6`=Prestige level:、`$10..$13`=Go to COOL Market. / Hyper Center Supermarket. / Peninsula shops. /
  Village Motel.、`$14..$19`=对手台词（Make your bet, buddy! / Let's wager! / … / Bet or I'm off!）
- `raceParams`：Map:/Laps:/Max users:/Server name:/Server location:/Car collisions: + 六个地区名

---

> ⚠ 勘误：独立子分析曾把布局块描述为「名字长度+名字 + 属性名+0x00+类型+填充0x00+4字节小端值…，
> 以 0xFFFFFFFF 结尾」，与 §1 不符。**以 §1 为准**（由原生跳转表判定，1058/1058 校验通过；
> 结尾是 `0x00` 属性表结束符 + 0~5 个零填充）。子分析解出的几何数值（Left/Top/Width/Height/Caption/
> onXxx/模板名）与本节一致，可直接采信。

---

## 5. 窗口与弹窗机制（`gui.Window` 的模态协议）

**返回值协议是理解全部 UI 流程的钥匙**：弹窗里 `close(n)` / `closePopup(n)` 的 `n` 就是
调用方 `openPopupModal(...)` 拿到的返回值（`closePopup()` ≡ `closePopup(1)`）。

| 方法 | 语义 | 证据 |
|---|---|---|
| `openPopupModal(Window parent)` | `parent.showModalPopup(this)` → 阻塞在 `wait()`，返回 `modalResult`；默认对齐 `Window.MIDDLE` | Window.java:197–203、34–44 |
| `openPopupModal(parent, 位置常量)` | 按 17 个位置常量摆位（边距 5，见 §2.1） | Window.java:200–203 |
| `openPopupModalNoWait(parent)` | 不阻塞、无返回值；给已有 root 窗口 `setLock(this)` | Window.java:62–72 |
| `showPopup(Window)` | **非模态**挂载（进 `popups` 表、不锁不阻塞）——全库只有 `Track` 用它挂 `Loading` | Window.java:154–157；Track.java:196–197 |
| `messageBox(type, msg)` / `messageBoxWait(type, msg)` | 播 `frontend/sounds/error.wav`(frontend.rpk#390) → `popup123`；type1 标题 `$1|Warning`、type2 标题 `$2|Error`；Wait 版阻塞 | Window.java:301–338 |
| `close(n)` / `closePopup(n)` | `closePopup` 先从静态 `popups` 表移除再 `close(n)` | Window.java:188–195 |

**`Track.openIngameMenu(Window, int code)` —— 比赛中一切子窗口的统一宿主（逐字复核 ✓，Track.java:990–1138）**
1. 前置：`gameMode.finishCall && SINGLE && 参数是 IngameMenu` ⇒ 直接返回；
   非 `IResultsWindow` 时 `enableCamChange(false)`；`allowChat(false)`；`code == 999` ⇒ `quitCalled = true`；
   关掉上一个 `childWindow`（`close(1000)`）；`HUDvisible(false)`；`activateHotkeys(false)`。
2. `local3 = childWindow.openPopupModal(gwindow)` —— **在这里阻塞**，返回后立刻断开 `childWindow`。
3. `switch (local3)`（结果码 → 官方语义**全表**）：

| 码 | 动作 | 证据 |
|---|---|---|
| 1 | 弃赛/转观战：非 SINGLE ⇒ 置 `ROOM_PARAM_USER_Logout`、`setSpectatorMode()` | 1039–1062 |
| 2 | 全量重开：HUD 计数清零、逐槽 `remPlayer`、`restartTrack(1)` | 1063–1078 |
| 3 | `changeStatus(GST_MENU)` 退出到菜单（**return**，不再走收尾） | 1079–1084 |
| 4 | `changeStatus(GST_MENU)` + `replay.Play()`（先看录像再回菜单） | 1085–1091 |
| 5 | 系列赛完成 ⇒ `messageBoxWait("$3|Well done! You can find your brand new wide body ride in the garage. Enjoy!")` + 登出 | 1092–1100 |
| 6 | 服务器模式登出（`intentionalDisconnection` + `ROOM_PARAM_USER_Logout`） | 1030–1038 |
| 7 | **重开本场**：`quitCalled=false` → `HUDvisible(true)` → `gameMode.restart()` | 1101–1107 |
| 999 | （进入前就置 `quitCalled=true`，无独立分支） | 1000–1002、1027–1028 |

4. 收尾（非 3/4）：对玩家车 `setDefaultTransmission/SteeringHelp/ASR/ABS/ESP`（**每次开菜单都会重置驾驶辅助**）；
   `HUDvisible(true)`、`showInfoComp()`、`allowChat(true)`、`enableCamChange(true)`、`activateHotkeys(true)`（1110–1137）。

⚠ 全前端**没有任何按钮产生结果码 2**（`close(2)` 全库无命中）⇒ 该分支在本版是死路（✗ 见 §12）。

### 5.1 公共弹窗族（构造参数 + 返回码）

| 类 | 构造 | 关闭码 | 语义 |
|---|---|---|---|
| `popup123` | 无参；`setCaption` 标题、`setLabel` 正文 | OK/ESC → **5** | 简单提示（`messageBox` 用它） |
| `popupOkCancel` | `(label, left, right[, escapeExitCode])`；`changeToYesNo()` ⇒ `$4|Yes`/`$5|No` | 左 → **1**，右/ESC → **0** | 二选一确认 |
| `StringPopup` | `(Component sender, int mode)`；mode 1 = FilePopup 存盘名输入 | Ok → **1**，Back/ESC → **0** | 文本输入；自动生成 `save/replays/<地图名截断18>-N.rpl` |
| `askNamePopup` | `(Window parent)` | 一律 `closePopup()`=1 | 新建生涯取名 + 性别 + 头像；结果写回 `userManWindow.newPlayerName`/`okClicked` |
| `botTalkPopup` | 无参；`makeBotTalk(bot, 台词)` | — | 对手搭话气泡（`$1|OK`） |
| `FilePopup` | `(path, mask, mode)` | Load: mode2→**0** 否则直接播放；Actual(mode2)→**10**；Save/Delete/Back→**0** | 录像/存档文件浏览器 |
| `PDAPopup` | 无参 | 关闭 → **1** | 排名 + 个人战绩 + **作弊码序列**（见 §9.5） |
| `creditsWindow` | 无参 | — | 滚动制作名单（`vanishLabels`→`endScene`） |
| `pleasewait` | `(String label)` | — | 转圈等待（配 `openPopupModalNoWait`） |
| `felugro` | 无参 | — | 「`$1|Hit a key!`」等待按键（按键采集用，`controlOptions.java:628` 唯一调用点） |
| `IngameOptionsWindow` | 无参 | 事件 105 → `closePopup()` | 设置页容器（见 §7） |

---

## 6. 启动与导航流程

```
[进程启动]
  Init → Config 载入 → Gamelogic 构造（showLogos = true，:85）
  → showSplashScreen("frontend/textures/Opening.png") → 预载 frontend.rpk#299/300/302 → sleep 1.5s
  → changeStatus(GST_START)（Gamelogic.java:386–394）
      ├ showLogos && SINGLE && !majomParade && !commandLineReplayMode
      │    ⇒ 窗口背景刷黑(alpha=1) → showLogos=false → new VideoPlay().openPopupModal(window)（:800–806）
      │        VideoPlay 依次播 {"fmv/Groove.fmv","fmv/Invictus.fmv","fmv/online_rating.fmv"}（VideoPlay.java:8）
      │        播完自动 playNext()（:24）；ESC（cmd 1）⇒ stop+playNext，全放完 deactivate 热键 + 开光标 + close（:16–47）
      │        SPACE（cmd 2）注册了热键但分支为空 ⇒ **空格不能跳过**（:36–38）
      └ changeScreen(new StartWindow())（:798）
[StartWindow = 800×600 StandardWindow + 房间/连接等待]
  控件：Component2(plexigreenhead 标题 + map/laps/racers/racer1..8 列表)、loadingAnim(Embedded loadInProgress)、abort(TextButton)
  非 SINGLE/SETTINGS/非断线 ⇒ 起 userWatch 线程轮询房内用户（StartWindow.java:81–84、214–241）
  abort ⇒ 停线程；等级不足/未 ready ⇒ commandLine ? GST_SHUTDOWN : GST_MENU；否则置 ROOM_PARAM_USER_Logout=1（:99–112）
  onAnimate 超时：>40s 或 (>10s 且未进 lobby) ⇒ 10–20s 且房未满则 GST_ROOM→GST_LOBBY，否则
      messageBoxWait(0,"$7|Connection failed. Please check your network connection.") + GST_MENU（:115–141）
  handleMetaEvent：ClientStatusChanged/LobbyJoined/RoomParameterChange/UserWaitTimeout("$1|Timeout: n")/
      RoomJoinFailed(MaxUserLimit ⇒ "$8|Join too many players"、InGameLock ⇒ "$9|Cannot join. The game has already begun.")（:162–208）
[GST_MENU] → changeScreen(new mainMenu())
[GST_PUB ] → pub.enter() + changeScreen(new PubWindow(), 0)（Gamelogic.java:885；Pub.java:63）
[GST_INGAME] → enterRace(challenge) → new GameWindow(track) + track.enter(gwindow, Viewport(0,0,1,1))
               → Track.enter 里 gwindow.showPopup(new Loading())（非模态）→ 加载完 loading.closePopup()（Track.java:196–197、411–412）
[比赛结束] GameMode.finish() → openIngameMenu(createResultsWindow(), 999)（GameMode.java:630–631）→ ResultsWindow → 结果码见 §5
```

### 6.1 `mainMenu` = 车库主界面（883 行 / 69 方法，**没有热键，全是控件事件**）

自身节点：`StandardWindow` 800×600；子控件（`mainMenu.java:66–144`，`this.<字段>` 即布局里的名字）：

| 控件 | 类型 | 几何 | 作用 / 证据 |
|---|---|---|---|
| `garage3d` | Embedded → `CarComponent` | 0,0,800,600 | 3D 车库 + 车况/性能面板（:106,159） |
| `carSelect` | Embedded → `CarTabListComponent` | 0,477,800,53 | 车辆横向列表（:108,160） |
| `tuningComp` | Embedded → `ItemlistComponent` | 0,70,290,405 | 改装/零件列表（:118,162） |
| `menu` | Component | 0,528,800,72 | 底部图标条容器（:107） |
| `infos` / `infoComp` | Embedded → `infoComponent` | 464,510,336,85 / 390,65,410,30 | 滚动提示行（:109,133） |
| `race` | IconButton | 5,548,45,40 | 去酒吧找对手 ⇒ `changeStatus(GST_PUB)`（:110,679–692） |
| `quickRace` | IconButton | 141,548,45,40 | 快跑 ⇒ `pleasewait("$110|Loading quick race...")` → `quickRaceInit()` → `GST_INGAME`（:142,197–213） |
| `multi` | IconButton | 56,548,45,40 | 联机 ⇒ `serverSelect`（:124,439–451） |
| `options` | IconButton | 323,548,45,40 | ⇒ `IngameOptionsWindow`（:113,722–732） |
| `userMan` / `career` | IconButton | 184,548,45,40 | 生涯存档管理 ⇒ `userManWindow`（:114,733–749） |
| `trial` | IconButton | 98,548,45,40 | 宽体试炼：车可转换 ⇒ `trialMode=true` + `GST_PUB`；否则 `$102`/`$101` 提示（:135,269–289） |
| `RaceInfos` | IconButton | 232,548,45,40 | **真正的「比赛信息/PDA」入口** ⇒ `PDAPopup`（:125,396–411） |
| `replayButton` | IconButton | 280,548,45,40 | `FilePopup("save/replays/","*.rpl",0)`（:123,452–468） |
| `credits` | IconButton | 367,548,45,40 | `creditsWindow`（:115,750–764） |
| `quit` | IconButton | 414,548,45,40 | 确认 `$20|Are you sure you want to quit?` ⇒ 存档 + `exitGame()`（:111,693–704） |
| `tuning` | IconButton | 556,540,45,40 | 展开/收起改装列表（含音效 `menuSlide1/2`）：`:112,706–721` |
| `cars` | IconButton | 611,540,45,40 | `carTabComp.toggle()`（:119,504–506） |
| `phone` | IconButton | 440,540,60,50 | **布局声明的 onAction=`race1_onAction` 在类里不存在** ⇒ 遗留按钮（✗） |
| `cheatButton`/`cheatButton2` | IconButton | 746/710,530 | `giveAllParts()` / `giveAllCars()`（仅 `Config.majomParade` 可见，:121–122,163–167,469–486） |
| `prestigeUp`/`prestigeDwn` | IconButton | 676,530 / 676,550 | 调 prestige（`getOpponentPrestigeByStatus(±1)+1`，同 majomParade 门控，:126–127,369–381） |
| `win` | IconButton | 640,530,30,30 | 切换 `bastardRaceFinished`（:134,299–301） |
| `arrowCars*`/`arrowTuning*`/`*Comp` | Button/Component | 边缘 42×50 | 左右滑动箭头（速率 **200 px/s**，`onAnimate`；初始 left = −100 或 width+100，`left_end = −1 / width−w+1`，:136–143,861–883） |
| `takeThisCar`/`carHolder`/`corusButton`/`phoenixButton` | TextButton/Component | — | 「二选一初始车」选择（`chooseFromTwoCars()`，:128–132,316–367,765–772） |

`StandardWindow_onShow`（:594–661）关键动作：`userManNeeded()` 判定 → 需要且无档 ⇒ `changeVehicle(-1)` +
`showInfoInMenu("$16|You need to create a new career first.")` + 自动 `userMan_onAction`；
`justWonTheGame` ⇒ `GameOutro` + credits + 复位；`goToJoinMenu` ⇒ 自动 `multi_onAction`；
换音效组（卸 impact/vehiclesfx/groundtype/vehiclesounds，载 garage/Tuning）、`changeMusicSet(MUSIC_SET_MAIN)`。
`StandardWindow_onHide`（:663–677）：卸动画、`syncGameTime(0)`、停 ambient、卸 garage 组、逐部件 `exitGarage()` + `IPart.flushTextures()`。

**主菜单显示的动态数据**（全部来自车库面板，不是 mainMenu 自己算）：
`CarComponent.Embedded1` → `ProgrBarComponent`（CarComponent.java:93）：
用户名+等级 `player.getNickName()`（ProgrBarComponent.java:186）、进度 `(61 − getPlayerRank())/60`（:134,155–159）、
胜率 `getWinningRate()`（:160–164）、试炼完成数 `"n / 10"` + `$10|Street Legend`（:172–185）、
冠军标 `$9|BastardRace Champion`（:166–171）、车辆性能条 `refreshSliders(Vehicle)`（:129–131）。
提示行 = `Gamelogic.showInfoInMenu(s)` → `infoComp.setInfo(s,false)`（Gamelogic.java:1352–1356）。
**✗ 「钱」在本引擎不存在**：全伪码树 grep `money|cash|Price` **零命中**（本轮复核）——LASR 的经济是
prestige + 零件/车，没有货币系统。

---

## 7. 设置窗口群

### 7.1 结构与导航
4 个设置页 + 1 个容器：`IngameOptionsWindow`（800×600，`Embedded1` 用 `setClass` 承载当前页，默认 **videoOptions**）
—— 自定义事件 100/101/102/103 = video/sound/control/game，104 = 空（**CHAT 页在本版不存在**，4 个窗口里的 CHAT 按钮都 `Visible=0`），
105 = 退出（IngameOptionsWindow.java:2,13–52）。打开点：`mainMenu:727`、`IngameMenu:222`、`ResultsWindow:295`、
`Gamelogic:840`（GST_SETTINGS 状态先 `changeScreen(StartWindow)`）。
每个设置窗自带 4 个页签按钮（VIDEO/SOUND/CONTROL/GAME，x=96/244/392/540，y=10，150×23）——切页前先
`checkBeforeLeaving()`；底部 3 个按钮（x=6/319/609，y=529，150×23）：BACK / APPLY 或 RESET|BENCHMARK / APPLY|BACK。

**未保存拦截**（4 窗一致）：`checkBeforeLeaving()` 只在 APPLY 按钮 `Enabled==true` 时弹
`popupOkCancel`（`CommonStrings.UNSAVED = "$31|You have unsaved settings. Exit control options?"`，
`changeToYesNo()`），YES 才放行；ESC 热键同路且有 **0.25 s** 节流（`(now − lastAllowEscapeTime) > 0.25`）。

### 7.2 videoOptions（18~20 个 GfxFeature）
- 值写入 `GfxFeature.lastValue`（**pending**），真正下发引擎只在 `GfxEngine.applyFeatureChange()`，
  而它只在 **APPLY / BENCHMARK** 里被调用；**BACK 会 `resetFeatureChange()` 丢弃未 APPLY 的改动**。
- 控件与特性：RESOLUTION→`GFX_RESOLUTION`、SHADER→`GFX_DX_COMPATIBILITY`（**需重启**，提示 `$100`）、
  FSAA(0..2)、GAMMA(0..6，标签 0.5/0.7/0.9/DEFAULT/1.2/1.5/2.0)、TEXTURE DETAIL(0..2)、VIEW RANGE(0..2)、
  WORLD DETAIL(0..2，**同时写** `GFX_WORLDDETAIL` 与 `GFX_OBJECTDETAIL`)、SHADOW DETAIL(0..2)、
  DYNAMIC ENV. MAP(0..1)、PARTICLE DENSITY(0..2)、MOTION BLUR(0..1)、HDR(0..1)、NOISE(0..2，**写入前 `min(v,2)`**)、
  CONTRAST(0..2)、HEADLIGHT REALITY(0..2)、**FOLIAGE DENSITY（布局里 `Visible=0`，隐藏但仍绑 `GFX_SPRITE`）**、
  OWN/OPPONENT VEHICLE DETAIL（写 `Config.vehicle_detail_own/opp`，补丁模式下 Max 由 3→1）。
  三值滑条统一用 `off|low|high` 或 `low|mid|high` 标签数组。
- `GFX_OBJECTLODDETAIL(8)` 与 `GFX_MIRROR(17)` **没有 UI**（只能在 benchmark 里被自动设置）；`ObjectLodDetail_onChanged` 是死回调。
- APPLY = `applyFeatureChange()` + 写 `Config` + `Config.save()` + `Navigator.updateSizes()`；
  RESET 按钮名（布局里 `ButtonBack` 的 Caption 是 BENCHMARK）**实际是 benchmark**：`GfxEngine.benchmark()` → float[10] →
  按阈值自动配 DX 档/画质/车辆细节 → `Config.save()`。
- **首次启动自动配档**：`save\game\options` 不存在时执行 `videoOptions.benchmark()`（videoOptions.java:721–866，阈值全表在源码里）。

### 7.3 soundOptions
MENU MUSIC VOLUME / INGAME MUSIC VOLUME / EFFECTS VOLUME / ENGINE VOLUME（均 0..10 → `/10`，
显示 `(int)(100*v)%` 或 `(int)(10*v)%`，**两套公式不一致，照抄原码**）、USED CHANNELS（**4..32**，显示原样整数）、
ENVIROMENTAL EFFECTS（0..3 → early/late reverb + occlusion 三位组合）。
EFFECTS 改动会连带 `CHANNEL_GUIEFFECTS = 0.5*v` 与 `speech_volume_opponent = v`；
ENGINE 改动 **不落 Config**（Config 只存 `Sound.getVolume(CHANNEL_ENGINE)`），退出时用内存值重新赋权。
`Sound_Mix_HW`/`Sound_3D_HW` 两个老字段被 `setSfxSettings()` **强制清零**（用户改不了）。
RESET 硬编码默认：`ingameMusicVolume=0.9, menuMusicVolume=0.9, channels=16, mix_hw=0, 3d_hw=0, early/late/occl=false, speech_opponent=1.0, engineVolume=0.7`。

### 7.4 controlOptions —— 按键绑定机制（★重制必读）
36 个可见热键按钮（`TextButton`，模板 `gui_textbutton_keys`，124×18）分两列（`buttonArray[0..19]` x=172、
`buttonArray[20..39]` x=300，行距 20）；caption **不在 stringTable 里**，运行时由 `cs.axisName(idx)` 填。
点击 ⇒ `startThread(idx, button)`：建线程 + 弹 `felugro("$1|Hit a key!")`，`allowEscape=false`。
采集线程（20 ms 轮询所有设备的 `activeAxis`）：
- 先等所有轴回中，之后任一轴被按下 ⇒ 写入 `ControlSet.controls[idx]` 的 `deviceID/axisID`（`cs.change`）；
  非 `AXIS_GEAR_SET` 的轴按方向设 `from_min/from_max`：方向 0→(0,1)、1→(0,−1)、2→(−1,1)、3→(1,−1)；
- **ESC（device=KEYBOARD 且 axis=RCDIK_ESCAPE=1）= 取消**：清 caption、`cs.change(idx,−1,−1)` 解绑；
- 绑定后反向扫 `maxAxisIdx(39)→0`，把占用同一 `(deviceID,axisID)` 且方向相同的其它槽**自动解绑**；
- 结束：`Input.controller.reset()`、`getKeyStat=2`、关提示窗、允许 ESC、`ButtonApply.setEnabled(true)`。
持久化：APPLY ⇒ `Input.activeControlFileId = tempControlFileId` + `Input.controller.cs.save(Input.activeControlFile + id)` + `Config.save()`；
文件 = `save/controls/active_control_set<0|1|2>`。`ControlSet.controls` 每项字段：group/vaxisID/deviceID/axisID/from_min/from_max/to_min/to_max/dead_zone。
`group` 位：`1=DEFAULTSET 2=DRIVERSET 4=MENUSETA 8=MENUSETB 16=FREECAMSET 32=MOUSESTICK`；复位用 `DRIVERSET|MENUSETA = 6`。
⚠ 列 2（idx 20..39）在 `ControlSet.defaults()` 里**全为空绑定（−1,−1）**，代码里没有任何「玩家 1/玩家 2」区分字段 ⇒ 语义待定（✗）。

### 7.5 gameOptions（46 条文本）
`GENERAL`（变速箱 Manual(100)/Auto(101)/Semiauto(102)/Semiauto2(103)、离合器 Autoclutch(110)/Manual(111)、
CLUTCH ON HANDBRAKE、CLUTCH ON BRAKING HARD、VIRTUAL GEARSTICK）、`GAME HELPERS`（ANALOG STEERING、
ANALOG STEERING RANGE、STEER、THROTTLE、VELOCITY、ACCELERATION、DAMPING、HELPER INFOS、GPS STYLE MINIMAP、
METRIC SYSTEM、SLOW MOTION）、`FORCE FEEDBACK`（开关 + REAL/EFFECTS/EMULATED STRENGTH）、`HEAD MOVEMENT(S)`（`$17` 有两个标签，
旧的行 `Visible=0`）。⚠ `Config.ForceFeedBack`（下拉）与 `Config.FFB_strength`（滑条）名字近似易混。

---

## 8. HUD 层

### 8.1 容器与换型
`GameWindow`（比赛窗口，Track.enter 的 screen）：字段 `HUD/HUDInfo/CarCondition/Embedded1/map/Embedded2/
GameMessagesEmbedded`（全 `gui.Embedded`）+ `hudinterface = new HUD_Interface()`（GameWindow.java:54–61）；
静态单例 `NameTAG_Window`；`View3D1.addChild(...)` 后逐个 `setClass`：
`HUDClassName = {"…HUD_Standard"}`、`HUDextClassName = {"…HUD_Standard_ext"}`、
`HUDInfoClassName = {"…HUD_StandardInfo","…HUD_Trial"}`（:66–68）。
换型由 `Track.getHUDTypeForCamera()` 决定：`CMD_CHANGECAM_REAR → 0`（两组都不显示）、
`INT_HOOD → 1`（HUD_Standard）、`INT_HEAD → 2`（HUD_Standard_ext），其余 → 1（Track.java:947–987）；
Info 皮肤由 `GameMode.getId()` 决定：1/2 ⇒ HUD_StandardInfo，3..6 ⇒ HUD_Trial（Track.java:2793–2830）。
⇒ **`getId()` 间接决定 HUD 皮肤**：`GmRace.getId()=2` → 标准板；`GmTrial.getId()=3` → 试炼板。

### 8.2 各 HUD 类
- `HUD_Standard`（仪表盘）：`RPMGauge` 挂 `SpeedDigital/Gear/SpeedGauge/BrakeBorder/AccelerateBorder/
  RevlimiterLed/HandbrakeBorder`；`SpeedGauge` 挂 `GMeter/TurboPressure/N2OGauge`；三根针 Border 各挂 Thumb。
  指针动画：`RPMGaugeStartTop = 601`、`RPMGaugeEndTop = getTop()`、`backTime = fullTime = 1.5`（:81–88），
  进场三次缓动；RPM 归一 **`(RPM − 500)/9500`**（:125）；`Gauge.setValue` 抽指针。
- `HUD_Standard_ext`（引擎盖视角）：转速**条**用 UV 切片逐条画（`RPMfullUVRange = (u0,v0,(u1−u0)/30,v1)`、
  `RPMRed`/`RPMCool` 两层，:108–115）；红区 `(int)(RPM_redline*0.003)`——与上面 `(RPM−500)/9500` 是**两套口径**（✗）。
- `HUD_StandardInfo`（信息板）：`PandLComponent`(LapComponent + PositionComponent)、`BestLapComponent`、
  `LastLapComponent`、`CheckPointComponentX`、`CurrentLap`、`countDown1/2`、`sectorTime1/2`；
  数字位数组 `CurrentTimeComp[1..7]`/`SplitDiffTimeComp[0..7]`/`BestLapComp[1..7]`/`LastLapComp[1..7]`（:248–276）。
- `HUD_Trial`：`HUD_StandardInfo` 的精简版（只有 Lap 一栏 + 计时 8 位数字，无 Position/BestLap/CheckPoint）。
- `HUD_Interface`（557 行 / 88 方法）：**HUD 的唯一接口层**，`GameMode/GmRace/GmTrial/Track/Vehicle` 全部通过它
  写 HUD（`setCurrentTime/setLastLap/setRaceSplitDiffTime/setPosition/setLaps/setGear/…`）。
  ⚠ 有大量方法**在本构建里没有任何调用者**（`setHUDInfoVisible`、`setFullPoint/getFullPoint`、
  `setFlagPoint*`、`setPlayerCtfInfo`、整套 `Bonus*`、`getFloatNumbers`、`sectorTimeRemains` …）⇒ 被砍掉的
  CTF/夺宝/奖励弹字玩法残留；`LastLapComp`/`SplitDiffTimeComp` 只被构造填充、无消费者 ⇒ **上圈时间与分段差值在本版 HUD 上不显示**（但 `GmRace` 仍在写）。
- 数字渲染：`getPointNumbers/getFloatNumbers/getTimeNumbers` 把数字拆到数码贴图控件（`NumberTexture`，HUD_Interface.java:18）；
  `InfoTag`（比赛后 PDA 表格用，`PDAPopup:305,317,383`）、`NameTAG`（8 Label + `setRenderTarget(1)` + 256×600）、
  `racerInfoComponent`（8 组 name/pos/info）、`carConditionComponent`（4 轮 + 车体损伤着色：绿→红）。
- `GameMsgComponent`（大字消息）：`GOComponent` 挂 `Three/Twoo/One/gogogo/CarRepaired/Rescue/FinalLap/
  WrongWay/CheckpointMissed/RescueOrGoBack/Winner/Second/Third/Finish/CleanSector/CleanLap/CountdownStarted`
  （GameMsgComponent.java:54–71）—— **docs/48 里那些 HUD 大字提示的载体**（倒计时/终圈/干净圈/逆行/救援…）。
  `addHUDTimer(t)` + `MSG_DISPLAY_TIME = 1.0` 控制停留时长。
- 动画：`Anim`（TYPE_FADER/JUMPER/PULSER/FLYER/SLIDER；`ONCE=1 LOOP=2`；`ANIM_SPEED=2.0`）/`Animator`
  （`Animator_onAnimate` 里删除元素后仍自增 `i` ⇒ **会跳过紧随其后的一个动画**，潜在 off-by-one）/`AnimState`（死类）。
  ⚠ 全库**没有任何 `new Animator()`** ⇒ 该调度器在本版可能没跑；HUD 进场动画走 `playAnimacio` + `*_onCustomLayout`。

---

## 9. 车库 / 酒吧 / 大厅 / 挑战

### 9.1 车辆列表 `CarTabListComponent`（285 行）
`TabList1`（`Columns=10 Rows=1`）+ 左右箭头 `balra/jobbra`；行模板 = `TabListHeaderItem1_createCustomItem`
→ `Embedded.setClass("java.game.frontend.CardComponent")`（Align 5、四边 Margin 2、车卡不显示选中底色）。
`initCars()`：取 `player.items.listVehicles()`，用**固定槽位表**映射到 UI 顺序：窄体 `{2,1,7,9,0,4,8,5,6,3}`、
宽体 `{12,11,17,19,10,14,18,15,16,13}`（`seekId` 用 `(id & VHC_MASK) >> VHC_SHFT` 匹配）；
`TabList1.setRows(IVehicle.VID_CAREER_MAX)`。选中 = `player.changeVehicle(idx)`；当前车自动 `setCheckboxChecked(true)`。

### 9.2 改装列表 `ItemlistComponent`（496 行）
4 个 `TabList`（`$1|Body` / `$2|Styling` / `$3|Power` / `$4|Handling`）+ `PageControl`；
数据 = `player.getVehicle().item.listAllParts()` 按 `Item.IFM_BODY/IFM_STYLING/IFM_POWER/IFM_HANDLING` 分桶
（跳过 `getName()=="<undefined>"` 与默认件）。装备链：卡片勾选 → `vehicle.item.attachItem(part)` +
`MetaServer.changeUserItemPosition(part.getId(), part.getOption())` → 对被顶下来的件同样上报 → `refresh()`；
卸下 → `removeItemSafe` + （POWER/HANDLING）`attachPreviousStage` 退回上一阶零件。
右键卡片 → `carComp.setPartLocation(part.getLocationFlags())`（3D 车高亮部位）。

### 9.3 `PubWindow`（790 行）= 酒吧/找对手场地（**不是车库**）
`View3D1` 3D 场景 + `pubName/difficulty1/2/difficulty_star`（用 `#tebarat#`/`#obarat#` 星标难度）+
4 个 `rallypoint` 按钮（**1→goToPub(4)、2→(3)、3→(2)、4→(1)**，带 3 s 冷却）+ `backToGarage` + `ranking`(PDA) +
底部 `Embedded1` 信息条 + 对手搭话气泡 `saySomething`（`#Bottalk.text_b#`）。
**挑战流程**（`updateOffer()`）：等到某个对手 `Bot.whatsUp(...)` 位掩码含 `BOTTALK_OFFER(4)`
⇒ 弹 `botTalkPopup`（台词）或直接 `MakeBetPopup(offer)`；连续被拒 ≥2 次后下一次 `createChallengeOffer(true)`
会设 `findAcceptableOpponent=true`（放宽筛选）。接受 ⇒ `Gamelogic.challenge` + `changeStatus(GST_INGAME)`。
`Bottalk` 掩码：`REJECT=0 GOSSIP=1 TEASER=2 BOAST=3 OFFER=4`。

### 9.4 `MakeBetPopup`（821 行）= 下注/挑战弹窗
布局：左「我」右「对手」两组 `nameLabel*` + `ProgrBarMini` 性能条 + 中央 `"VS"` + `Rotating1` 地图预览 +
`oppBet1..oppBet6`（前 3 = 我的赌注、后 3 = 对手的，均为 `CardComponent`）+ `PinkSlips` + `MapName1/2` +
`TextButton1 "$1|GO!"` / `TextButton2 "$2|REJECT"` / 关闭 `Button1` / 地图作弊翻页 `Button2..4`。
赌注项由 `player.getPossibleBets(trackID, challenger, offeredBets)` 产出（Prestige→`Bet(0)`；
PerformPart→随机挑一个性能件；StylingPart；整车 `BET_TYPE_WholeStage`/`WholeStyle`）。
提交：`TextButton1` ⇒ 未勾选槽位置空 → `isPinkSlipsOffered=false` → **`new Challenge(trackID, challenger,
offeredBets, player.vehicle.item, possibleBets, destIVhc)`** → `closePopup(1)`；拒绝 ⇒ `closePopup(0)`。
`Challenge.isForPinks()` 在 `trialMode` 或 `isQuickRace` 时恒 false。

### 9.5 `PDAPopup` 与作弊码
页签切换 `TabList1_onChanged` 里滚动 4 位数字序列（`cheat[0..3]`）：
`0,8,4,5` ⇒ 全车（`cheatButton2_onAction` / `giveAllCars()`）、`0,8,7,8` ⇒ 全零件（`giveAllParts()`）、
`0,8,1,9` ⇒ 转宽体（`convertToWideBody()`，把车挪回原位）（PDAPopup.java:222–289）✓。

### 9.6 存档槽窗口 `userManWindow`（440 行）
5 个槽（`user1..5`：头像 `pic` + `usernameN` + 存盘日期 `dateN` + 垃圾桶 `delN`）；
有档 ⇒ `Gamelogic.getTimeAndName("save/career/00N.sav")`，无档 ⇒ `$7|::Empty::`。
动作：`resume` 读档（失败 `$6|The file could not be loaded!`）；`newCareer` 找空槽 → `askNamePopup` 取名 →
`resetCareer()` + `player.items = new ItemRoot()` + `addDefaultItems()` + 加两台初始车（Corus S2 / Phoenix Trend）+
填 `PRESTIGE_VECTOR_SIZE` 条 RaceChronicle（前 10 条 prestige 20、其余 40）+ `setNickName` → 关窗后 `mainMenu.chooseFromTwoCars()`；
`loadCareer` 带 `pleasewait("$10|Loading career.")`；`deleteSlot` 二次确认 `$11`。
**没有改名/密码/改头像功能**（名字只在新建生涯时设；`picN` 无贴图切换代码）。

### 9.7 联机入口 `serverSelect` + 建房 `raceParams`
`serverSelect`：`MasterGameList1`（Rows=20，表头 Server name/Map/Server loc./Users/Status，`setAutoRefresh(30.0)`）+
Connect/Host/Refresh/Stop；列表来自 `Gamelogic.getMGS()` 的 `host:port` → `Network.ConnectToMGS(host,port)`；
Host ⇒ `raceParams`，返回 1 则 `System.execute("dedicated server.exe", "cfgfile=ds.cfg map=… laps=… maxusercount=…
servername=… serverlocation=… collisionmode=…", 7)` 并记 `Gamelogic.DS_PID`（Stop 用 `System.abort(DS_PID)`）。
`raceParams`：地图（`player.items.listMaps()`，按名字前两字符冒泡排序，**排序代码在 `:82–123`**）、圈数 **1..99**、
人数 **1..8**、服务器名（空格→下划线）、地区 6 选 1、车碰撞复选框 → `Gamelogic.collisionMode`。

### 9.8 `ConsoleWindow`（调试控制台）
热键 **Numpad\*** + `Config.majomParade` 才可开（Init.java:64–80）；`LineEdit1` 回车 → `interpreter(文本)`，
**只有 3 条命令**：`pop intro`（播 GameIntro）、`pop outro`（播 GameOutro）、`champ`（关窗 + `justWonTheGame=true`，
若当前是 mainMenu 则触发其 `StandardWindow_onShow` 的夺冠流程）——**这是最快看到通关/过场的调试路径**。

---

## 10. 比赛结果与回放

### 10.1 `ResultsWindow`（518 行）
列/控件：成绩单主体 + 名次/名字/时间/最佳圈/奖励 + `resultsbn`（展开成绩单 `showMenuLine(true)`）+
`BackButton`、`BackToPub`、`viewReplay`、`quit`、`options`、`nextCamera`、`nextCar`。
按钮 → 结果码（**与 §5 的 switch 一一对应**）：

| 按钮 | 条件 | 结果码 | 证据 |
|---|---|---|---|
| `BackButton` | 试炼 ⇒ 5，否则 3 | 退出到菜单 | ResultsWindow.java:123–131 |
| `BackToPub` | `isQuickRace || weHaveATrial` ⇒ **7（重开）**，否则 1 | 回车库/重赛 | :148–160 |
| `viewReplay` | `FilePopup(...,2)` 返回 10 ⇒ 4 | 存录像/看录像 | :133–146 |
| `quit` | 试炼 ⇒ 5，否则 1 | | :281–288 |
| `options` | — | 打开设置 | :290–299 |
| `nextCamera`/`nextCar` | — | `track.changeCam(mode)` / `changeCamTarget(v)` | :246–275 |
| `Window1_onAnimate` | `COUNTDOWNTIME − (now − startTime)` 到 0 | 自动 `BackToPub` | :209–240 |

⚠ `getTimerProgress/getMainComponent/getBackToRoomLabel/getBottomItems` **全是空块 return null**，
但 `Track.java:1011` 真的调用了 `getBottomItems().setVisible(false)` ⇒ 原实现非空、语句在结构化重建中丢失；
`Track.enableResultsCountdown` 在 Track 侧**无方法体**（✗）。

### 10.2 回放 `ReplayWindow` + `FilePopup`
入口：`mainMenu.replayButton` → `FilePopup("save/replays/","*.rpl",0)`（mode 0 = 直接播放）；
`ResultsWindow.viewReplay` → mode 2（存/删）。`FilePopup`：Load ⇒ `changeScreen(new StartWindow())` +
`replay.Load(path+name)` + `replay.Play()`；Save ⇒ `StringPopup(this,1)` 取名 → 重名 `popup123("$10|File exists. Try another name!")`；
Delete ⇒ 二次确认 → `File.delete`。`ReplayWindow` 持有静态 `NameTAG`，退出 ⇒ `changeScreen(new mainMenu(), …)`。

---

## 11. 重制落地清单

1. **UI 框架**：`Component` 树 + `Window` 模态协议（`close(n)` 返回值）+ 17 个对齐常量 + `addChild/addRootChild`，
   事件钩子 20 个 + 各控件专属（`onAction`/`onChanged`/`onSelectionChange`/`onHover*`/`onKey*`/`onAnimate`）。
2. **布局**：直接吃 `out_ui_layouts.json`（1058 块，含名字/模板/坐标/贴图/回调名），或按同结构重写；
   `tools/ui_layout.py` 可当回归工具。文本走 `out_ui_texts.json` 的 `$N|` 表。
3. **导航**：§6 流程图 + `Gamelogic.changeStatus` + `Track.openIngameMenu` 结果码全表；
   `GST_INGAME` 进入两条路（`changeStatus` / `enterRace`）。
4. **设置**：§7 四窗 + 页签容器 + APPLY/BACK/RESET 语义 + **按键绑定采集机制**（含互斥解绑与 ESC 取消）+
   benchmark 自动配档阈值；`save\game\options`（SAVEFILEID 0xFEDCBA98、version 37）+ `save/controls/active_control_set<N>`。
5. **HUD**：`HUD_Interface` 作为唯一写入口 + 三种皮肤（`getId()` 决定 Info 板）+ `GameMsgComponent` 大字 +
   `getPointNumbers/getFloatNumbers/getTimeNumbers` 数码渲染。
6. **车/改装/酒吧/下注**：§9 的列表填充公式、槽位表、`Challenge`/`ChallengeOffer`/`Bet` 结构、`Bot.whatsUp` 位掩码。

---

## 12. 未知清单（✗）

| # | 项 | 备注 |
|---|---|---|
| 1 | **联机大厅/房间/聊天窗口整块缺失** | `game/frontend` 69 个类里没有 Lobby/Room/Chat 窗口；`RoomUserInfo`/`RoomUserInfoVector` 除自身定义外**全库无引用** ⇒ 控件树与文案无法给出 |
| 2 | 商店/买卖/赠送链断头 | `CardComponent.BuyButton` 只 `postCustomEvent(SmallBuyPressed=23)`，`GiftButton` 在布局里声明了 `GiftButton_onAction` 但**类里无此方法**；全库找不到 `SmallBuyPressed`/`itemDropped` 的处理者 ⇒ 商店窗口不在伪码集合内 |
| 3 | 卡片字段 `CPLabel/FrayLabel/TrolleyIcon/carLogo/pipaIkon` 的填充者 | 除 `setItemLocked/setXPLabel` 外无写入点 |
| 4 | `phone` 按钮与 `race1_onAction` | 布局声明的方法在类里不存在（遗留） |
| 5 | `Track.enableResultsCountdown` / `ResultsWindow.getBottomItems` 等空块 | 语句丢失；连带 `setTime/canQuitGame/setDisabled/setOff` 的真正调用者不明 |
| 6 | `GameMode.finish()` 连调两次 `createResultsWindow()` | 字段与弹出的可能不是同一实例 |
| 7 | 结果码 2 的产生者 | 全前端无 `close(2)` |
| 8 | `controlOptions` 列 2（idx 20..39）语义 | `defaults()` 全空绑定，无玩家区分字段 |
| 9 | 分辨率/着色器下拉的**标签文本** | 由原生 `SGF_Resolution.getLabels()`/`HGF_ShaderLevel` 提供，Java 侧不可读（`docs/25`、`docs/27` 有实测锚点） |
| 10 | `GfxFeature` 出厂默认值 | 全在原生子类构造里；`Config.video_settings` 无 Java 侧初始化 ⇒ 默认值只能实测 |
| 11 | RPM 两套口径（`(RPM−500)/9500` vs `redline*0.003`）是否等价 | 未验证 |
| 12 | `carConditionComponent` 撞击计数口径（4 轮 tear 之和下降，25 ms 轮询，阈值 0.001）与 `GmRace` 的 0.15 阈值关系 | 可能一次碰撞多帧多次 `addCrash` |
| 13 | `VideoPlay.run()` 的 `System.exit(加密常量)` 实际退出信息、`Scene` 三 FMV 播完行为 | 伪码常量表加密 |
| 14 | `Gamelogic.changeScreen(Window,int)` 第二参 | 方法体内未使用（Pub 传 1、ReplayWindow 传 0） |
| 15 | `HUD_Interface` 的 `GO` 字段、`getTimeNumbers` 内的 `local1[(-1)] = (-1)` | 疑似死代码/伪影 |
| 16 | `Animator` 是否真被使用 | 全库无 `new Animator()` |
| 17 | `debugLocalMode`、`commandLineMode`、`sala_feher_garage`、`majomParade` 等作弊/调试开关的完整影响面 | 分散在各处门控 |

