# 32 · 音频代码层：Java 子系统规格 + 原生桥接

> 承接 `docs/31_AUDIO_SPEC.md`（素材层）。本轮把**播放模型**从 Java 伪码里完整读出，
> 并定位了原生侧的音高计算。唯一未闭合的是"每帧 RPM→音高 / 负载→选层"的具体公式（§5）。

## 1. `java.sound.Sound` —— 音频子系统总控（伪码全文 66 行）

### 1.1 通道布局（混音器结构）

```java
CHANNEL_EFFECTS     = 0
CHANNEL_MUSIC       = 1
CHANNEL_ENGINE      = 2      // ★ 引擎独立通道
CHANNEL_GEARBOX     = 3      // ★ 变速箱独立通道
CHANNEL_ENVIRONMENT = 4
CHANNEL_SPEECH      = 5
CHANNEL_GUIEFFECTS  = 6
```

⇒ **7 条逻辑通道**，引擎与变速箱**分开**（对应 `vehiclesfx.fsb` 的换挡音）。

### 1.2 音乐集与状态

```java
MUSIC_SET_NONE = -1   MUSIC_SET_MAIN = 0   MUSIC_SET_INGAME = 1   MUSIC_SET_CREDITS = 2
musicFading = false;  changeMusicSet(set);  musicFade(float,int)   // 后者伪码为空体
trackChange = new Object()
```

⇒ `music/` 的 13 首 `.ogg` 按 **3 组**（主菜单 / 比赛内 / 制作名单）组织。

### 1.3 音量模型

```java
increaseVolume(ch, d): v = getVolume(ch) + d;  if (v > 1.0) v = 1.0;  setVolume(ch, v)
decreaseVolume(ch, d): v = getVolume(ch) - d;  if (v < 0.0) v = 0.0;  setVolume(ch, v)
```

⇒ 音量归一化在 **[0.0, 1.0]**，按通道独立。

### 1.4 语音本地化

```java
localizeSpeechFile(name) = "sound/speech/" + speechLanguage + "/" + name + ".wav"
initLang():
    if (File.exists("sound/speech/" + Config.language + "/fx_repairing_1.wav"))
        return Config.language;
    return "en";                     // defSpeechLanguage
```

⇒ 语音是**按语言分目录的 WAV**；用**探测文件 `fx_repairing_1.wav`** 判断语言是否可用，
不可用则回落英文。命名形如 `fx_repairing_1`（= 功能前缀 + 编号）。

### 1.5 队列线程

```java
init():    sfxQueue = new SfxQueue(); sfxQueue.start();   // ★ 独立线程
destroy(): changeMusicSet(NONE); sfxQueue.stop();
queueSfx(SfxRef r)          → sfxQueue.queue(r)
queueSfx(SfxRef r, float f) → sfxQueue.queue(r, f)
```

⇒ 播放请求走**队列 + 专用线程**，不在游戏主线程里同步发声。

## 2. `java.sound.SfxRef` —— 音效引用与播放模型

### 2.1 标志位

```java
SFX_3D       = 0
SFX_2D       = 1
SFX_LOOPED   = 2      // ★ 循环（引擎/环境音）
SFX_STREAMED = 4      // ★ 流式（音乐）
```

**★ 资源根**：
```java
SFX_ROOT = new ResourceRef("system.rpk", 9)
```
⇒ **音效资源挂在 `system.rpk` 归档的第 9 号资源下**（RPAK 格式此前已破解）。

### 2.2 播放调用（`nplay` 的参数排布）

```java
play()                    → nplay(null, 0.0, 1.0, getVolume(CHANNEL_EFFECTS), 0)
play(float f)             → nplay(null, 0.0, 1.0, f, 0)              // f = 音量
play(float f1, float f2)  → nplay(null, 0.0, f2, f1, 0)
play(int i)               → nplay(null, 0.0, 1.0, 1.0, i)            // i = 标志
play(int a, int b)        → nplay(null, 0.0, 1.0, (float)a, b)
play(int a, F b, F c, I d)→ nplay(null, 0.0, c, b, d)
play(Vector3 p, F a,F b, I d)     → nplay(p, a, b, a?, d)
play(Vector3 p, F a,F b,F c, I d) → nplay(p, a, b, c, d)
```

**返回值是 `int`** ⇒ ★ **通道句柄**：先 `play` 拿到句柄，后续用它改音量/音高 —— 这正是
"引擎声播放一次循环 + 每帧调整"的实现方式。

调用前一律 `cache()`（把音效预载进内存，避免运行中卡顿）。

### 2.3 目录扫描

```java
scanDirectory(dir) → scanDirectory2("sound/speech/" + speechLanguage + "/" + dir)
scanDirectory2(d):
    ref = ResourceRef().create(SFX_ROOT, d)
    FindFile.first(d + "/*.wav") … next() … close()
```

⇒ 环境音/语音是**按目录枚举 `*.wav`** 批量注册的。

### 2.4 从文件创建

```java
SfxRef(int i, String s1, String s2) → createFromFile(SFX_ROOT, s1, s2)   // (根, 路径, 标志)
SfxRef(ResourceRef r, String s)     → createFromFile(r, s)
```

⇒ 音效寻址 = **(资源根, 路径名, 标志)**。

## 3. 原生侧：音高计算（汇编，`0x564327`–`0x564379`）

```asm
call  [0x6299ac]                 ; 取通道当前值（FMOD 导入桩，紧邻 setFrequency）
fld   [0x6ea580] / fld [esi+0x28] / fcompi
jbe   随机分支
  movss xmm0,[esi+0x28] ; mulss xmm0,[esp+0x10]     ; ★ 频率 = 基准 × 输入
随机分支（基准较小时）：
  call 0x6674f8  (= rand) ; and eax,0xfff           ; ★ 0..4095 的抖动
  fadd [0x6e8b08] / fadd [esp+0x10] / fsub [0x6f5d30]
push ecx ; push edi ; call [0x6299a6]               ; ★ setFrequency(通道, 频率)
```

- `[esi+0x28]` = 该音效对象的**基准频率/音高刻度**
- 随机量对应 FSB3 头里的 **`varfreq`** 字段（已导出到 `out_fsb.csv`）
- FMOD 导入桩区：**`0x6299a6` = `setFrequency`**，`0x6299ac` = 紧邻的取值函数（6 字节宽 = `FF 25` 桩）

**桩的三个入口**（被 Java 原生层调用，`0x415xxx–0x419xxx` 区间）：
`0x564230` / `0x564240` / `0x564270` —— 对应音效对象上的不同操作，尚未逐一命名（§5）。

## 4. 分层结论：声音逻辑横跨两侧

| 层 | 位置 | 已拿到 |
|---|---|---|
| 游戏逻辑 / 点播 | **Java**（`Sound` / `SfxRef` / `GUI.playSoundFX`） | ✓ 通道、音乐集、音量、语音本地化、播放模型、标志位、资源根 |
| 原生 FMOD 包装 | C++ `0x5642xx–0x5666xx`（fmodex + fmod_event 双 API） | ✓ 形状与关键调用点，✗ 未逐方法命名 |
| 游戏级音效管理器 | C++ `0x53exx–0x53fxx` | ✗ 结构未读 |
| **每帧车辆音频更新** | C++（**不在** Java `sound` 包里） | ✗ **未定位**（§5） |

★ 注意：`highload` / `offload` / `roadnoise` / `.fsb` 在二进制里**0 处出现** ⇒
**采样名不做字符串查找**，层选择走**音库内索引**（`.fsb` 内的排列顺序即层顺序）。

## 5. 遗留（✗ 下一轮的入口）

1. **每帧车辆音频更新**：在 C++ 车辆模块里找"读 RPM/负载 → 写频率/切层"的代码。
   入口候选：`0x53exx` 管理器、`0x564230/0x564240/0x564270` 三个入口的调用者
   （调用者位于 `0x415xxx–0x419xxx` = Java 原生分发区）。
2. **`system.rpk` 第 9 号资源**：用已破解的 RPAK 格式把 `sound/` 整棵树解出来，
   与磁盘上的 `.fsb` 对照（可能含 `sound/speech/<lang>/*.wav` 语音包）。
3. `SfxQueue` 类本体未在导出集中（被引用但类文件不在 `sound` 包）。
4. `vehiclesfx.fsb`(38) / `crash`(66) 的逐条用途分类。
5. 13 首 `.ogg` 的分组归属（MAIN/INGAME/CREDITS 各几首）。
