# 31 · 音频规格：素材、格式、引擎发声模型

> 本轮把音频从零开题做到**素材层全通**。全部 264 条采样已导出为可回读的 WAV（见 §7）。
> 代码层（FMOD 调用链、参数映射）已定位到地址，见 §6，留作下一轮。

## 1. 容器格式：FSB3（FMOD Sound Bank v3）

实测头部布局（16 个音库逐条验证）：

```
主头（24 字节，全部小端）
  0   char[4]  "FSB3"
  4   uint32   numSamples
  8   uint32   hdr_total     采样头表总字节数      ← 注意见 §1.1
  12  uint32   dataSize      数据块总字节数
  16  uint32   version       实测 0x00030001 (= 3.1)
  20  uint32   mode
采样头表（从 24 开始，**每条长度由该条自身的 uint16 size 字段给定**）
  0   uint16   size          该条头部长度（普通库 = 80 = 0x50）
  2   char[30] name          ★ 明文，形如 "highload.wav"
  32  uint32   lengthsamples
  36  uint32   lengthcompressedbytes
  40  uint32   loopstart
  44  uint32   loopend
  48  uint32   mode
  52  int32    deffreq
  56  uint16   defvol
  58  int16    defpan
  60  int16    defpri
  62  uint16   numchannels
  64  float    mindistance      ← ★ 3D 衰减参数，可直接用于重制
  68  float    maxdistance
  72  int32    varfreq
  76  uint16   varvol
  78  int16    varpan
数据块（紧随采样头表）
```

### 1.1 ★ 踩过的坑：采样头长度**可变**，绝不能用均值走表

`roadnoise.fsb` 的表总长 `hdr_total = 3760`，14 个采样 ⇒ 均值 268.57 **不是整数** ✗ ——
因为它的首条头部自报 **`0x364 = 868` 字节**，且条目内嵌 **`SYNC`** 块（FSB3 的可选同步点数据）。
按均值走表会把 14 条全部解析成空名字、0 字节。

**可靠做法（已实现并自校验）**：
1. 数据起点由 **文件尾反推**：`data_off = len(file) − dataSize`
   （roadnoise：1430078 − 1426294 = **3784** = 24 + 3760 ✓ 与 `hdr_total` 吻合）
2. 从 24 开始**按每条自身的 `size` 逐条推进**
3. **自校验**：走完必须正好落在 `data_off`，且 Σ`lengthcompressedbytes` 必须等于 `dataSize`
   —— 16 个音库全部通过 ✓；任何一条不通过就报 ✗ 而不是猜。

## 2. 素材清单（16 个音库 / 264 条 / 32.5 MB 原始 PCM）

| 位置 | 音库 | 条数 | 用途 |
|---|---|---|---|
| `frontend/sounds/` | `challenge` | 26 | **赛前对手语音**（"Okay 01 / Alright / You're On / Let's Do It / Let's Go" 各带编号变体；`Alright 01/02` 各重复两次 = 不同角色版本 ⇒ 重制时按 (库,索引) 索引，不能按名字） |
| | `garage` | 61 | **菜单旁白** + 角色语音（`menu1_race`/`menu2_tuning`/`menu3_carSelect`/`menu4_userMan`/`menu5_options`/`menu6_credits`/`menu7_replay`/`menu8_multiplayer`/`menu9_ranking` ⇒ 菜单结构一览；`Zorejek NN.wav` = 角色名） |
| | `ingame` | 5 | 比赛内提示 |
| | `menu` | 9 | 菜单音效（`screenshot.wav` 等） |
| `sounds/` | **9 个车辆音库** | 5 each | ★ 见 §3 |
| | `crash` | 66 | 碰撞 |
| | `roadnoise` | 14 | ★ **路面材质音频**（见下）—— **带 SYNC 块**（§1.1 的坑就出在这个库） |
| | `vehiclesfx` | 38 | 车辆通用音效 |

**采样率/声道分布**（由标准库 `wave` 回读统计 ✓）：
`44100 Hz 单声道 × 133`、`22050 Hz 单声道 × 119`、`44100 Hz 立体声 × 10` —— 两档采样率 + 少量立体声。

## 3. ★ 车辆引擎发声模型（重制直接可用）

**每个车辆音库 = 5 层，按"负载"切换**：

| 层 | 含义 |
|---|---|
| `idle.wav` | 怠速 |
| `low|mid|high + load.wav` | **带负载**（油门）时的三个档位 |
| `low|mid|high + offload.wav`（部分库写 `off`） | **松油门/滑行**（发动机制动）时的对应档位 |

- 大多数车：`midload` + `midoffload` + `highload` + `highoffload`
- `hornet`、`phoenix`：用 **`lowload`/`lowoffload`**（低档引擎）
- ★ **`trend` 全部前缀 `trueno`**（`truenoidle` / `truenolowload` / `truenolowoff` / `truenohighload` / `truenohighoff`）＝ AE86 Trueno
- 与 `docs/19_PHYSICS_FORMULAS.md` 的 **RPM → 音高** 曲线配合即构成完整发声链
  （音高随 RPM、层随负载 ⇒ 重制时的实现方式）

**车辆 → 音库映射**：`buggy / corus2 / cracer4x4 / fujin / hornet / phoenix / quadro2 / raptor / trend`
（与配置里的车名一致）

## 3.5 ★ 路面材质音频（`roadnoise.fsb`，14 条）

**每种路面都是"滚动 + 打滑"一对**，命名用**匈牙利语**（Invictus Games = 匈牙利工作室 ✓）：

| 文件名 | 含义 | 对应接触面 |
|---|---|---|
| `asphalt.wav` | 沥青 | **Asphalt** |
| `fulevel.wav` / `fulevelslide.wav` | `fű` = 草 | **Grass** |
| `homok.wav` / `homoklide.wav` | `homok` = 沙 | **Sand** |
| `kavicsagy.wav` / `kavicsslide.wav` | `kavics` = 砾石 | **Gravel** |
| `snowalap.wav` / `snowslide.wav` | `snow alap` = 雪地基础 | **Snow** |
| （冰面缺独立条目，可能复用 snow 或 `slip_*`） | — | Ice |
| `slip_d2.wav` / `slip_c.wav` | 打滑（两种强度/类型） | 打滑通用 |
| `kerekveto.wav` | `kerékvető` = 减速带（**仅 1504 采样** = 极短撞击音） | 路缘/减速带 |
| `air.wav` / `water.wav` | 空气 / 水 | 腾空 / 涉水 |

★★ **与轮胎物理模型一一对应**：`docs/20_TYRE_MODEL.md` 的
`CONTACT_Asphalt=0 … Ice=5, Count=6`（**6 种接触面**）⇒ **接触面索引 → 音频对** 的映射即为
重制的实现依据（两条独立判据：物理侧枚举 vs 音频侧文件名）。

采样率：全部 **22050 Hz 单声道**；循环点均为 `0 → N-1`（整段循环）；3D 衰减 `min/max = 1.0/10000.0`。

## 4. 分区环境音（`frontend/sounds/<分区>/`）

| 目录 | 素材 |
|---|---|
| `suburb/` | `cityloop`（循环）、`cricketloop`（循环）、`forest`、`coyote`、`owl`、`owl2`、`dog01-03` |
| `harbor/` | `foghorn1-2`、`seagull1-2` |
| `highway/` | `atmosphere.wav` |
| `shops/` | `shops01-02.wav` |

⇒ **循环底噪 + 随机点缀音**的设计（`*loop.wav` 是循环层，其余是随机触发）。

## 5. 音乐

`music/*.ogg` **13 首**（Ogg Vorbis，已带可读名字）：
`01. Burn` / `02. Crunch Time` / `03. The Last Run` / `04. Till The End` / `05. Ready To Go` /
`06. Close To The Edge` / `07. Ready for the Ride` / `08. 5th Gear` / `09. South Central Bounce` /
`10. West Coast Ridin'` / `11. Get Yo Whip` / `12. Melrose Nights` / `14. StreetParty`
（编号 13 缺失）

## 6. 代码层：FMOD 调用点（已定位，未逆向）

由 `tools/ff25_stubs.py` 的 FF 25 跳转桩索引得到 **72 个静态调用点**，聚成两团：

| 区段 | 角色 |
|---|---|
| **`0x5642xx – 0x5666xx`** | 引擎的 **FMOD 包装类**（`fmodex` + `fmod_event` 双 API） |
| **`0x53exx – 0x53fxx`** | **游戏级音效管理器**（`playSound` / `stop` / `createSound` / `setPaused`） |

用到的 API 面（节选，说明引擎做到了哪一层）：
`createSound` / `playSound` / `setPaused` / `setVolume` / `setPan` / `setFrequency` / `setPriority` /
`set3DAttributes` / `set3DMinMaxDistance` / `set3DConeOrientation` / `setReverbProperties` /
`setSpeakerMode` / `setHardwareChannels` / `setSoftwareChannels` / `getDriverCaps` / `getHardwareChannels` /
`loadGeometry` / `set3DListenerAttributes` / `FMOD_Memory_Initialize` / `EventSystem_Create` /
`setPluginPath` / `getLength` / `getOpenState` / `getCPUUsage`

## 7. 产物

| 文件 | 内容 | 校验 |
|---|---|---|
| `out_audio/<音库>/*.wav` | **262 个 WAV**（264 条 − 2 条同名，见 §2） | 标准库 `wave` **262/262 回读成功** ✓，总时长 7.41 分钟 |
| `out_fsb.csv` | 逐条元数据（名字/采样数/采样率/声道/音量/声像/优先级/循环点/3D 距离） | 解析自校验全绿 |
| `out_fsb_report.txt` | 可读报告 | — |
| `tools/fsb_parse.py` | FSB3 解析（只读） | — |
| `tools/fsb_extract.py` | FSB3 → WAV（循环点写进标准 `smpl` 块） | 自校验 ✓ |

**编码判定**（不猜 mode 位，用体积比 + 数据首字节）：全部 16 个音库均为 **16-bit PCM**
（2.00 B/采样/声道；数据首字节 `ec ff` = 有符号负值）⇒ 提取无需任何解码器。
非 PCM 的条目会被**原样导出为 `.raw` 并标 ✗**，不伪造。

## 8. 遗留（✗ 下一轮）

- **代码层映射**：负载/RPM 如何选层、音量与音高的具体曲线、`0x53exx` 管理器的结构
- `mindistance` / `maxdistance`（3D 衰减）已导出到 CSV，但引擎实际用哪组值未定
- **FMOD 事件系统**（`fmod_event.dll`）的用法：音乐/环境音是否走 event 而非 API
- 13 首 `.ogg` 的播放逻辑（随机？按赛事？）
- `vehiclesfx`(38) / `crash`(66) / `roadnoise`(14) 的逐条用途分类
