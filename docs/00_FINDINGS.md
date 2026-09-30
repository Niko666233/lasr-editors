# 已证实的事实（含证据）

凡标「实测」的，都有工具输出或二进制地址支撑；标「推测」的明确标注。
地址写法：`LASR.exe` 的 **文件偏移 == RVA**（`.text` 的 RAW=VA=0x1000），
绝对虚拟地址 = `0x400000 + RVA`（ImageBase = 0x400000，SizeOfImage = 0x51D000）。

---

## 0. 环境

| 项 | 值 |
|---|---|
| 游戏 | `C:\Games\LASR`，457 MB / 609 文件 |
| 可执行 | `LASR.exe` 3,739,648 B，PE32 i386，ImageBase 0x400000 |
| 依赖 DLL | `d3d9.dll`, `d3dx9_30.dll`, `fmodex.dll`, `fmodex.dll`+`fmod_event`(FMOD), `msvcr71.dll`, `dbghelp.dll` |
| 编译器 | MSVC（`.?AV...@@` RTTI 符号） |
| 物理 | **ODE 0.5**（源码路径字符串 `D:\work\ODE-0.5\ode\src\collision_trimesh.cpp`，配置路径 `rnd_bouboullon`）|
| 压缩 | zlib 1.1.4（`inflate 1.1.4 Copyright 1995-2002 Mark Adler`）、Info-ZIP unzip 0.18 |
| 图像 | libjpeg（`Copyright (C) 1996, Thomas G. Lane`） |
| 反汇编工具 | **仓库内 venv**：`.capenv/Scripts/python.exe`（Python 3.14.7；capstone 5.0.7 / unicorn 2.1.4 / pillow 12.3）—— 所有 `tools/`、`remaster/tools/` 脚本都用它跑 |

---

## 1. 架构：不是标准 Java，是自研 `JavaMachine`

**实测**：在 `LASR.exe` 中搜索 JVM 标识字符串，
`defineClass` / `JNI_CreateJavaVM` / `jvm.dll` / `HotSpot` / `java/lang/Object` /
`ClassFormatError` —— **全部 0 命中**。

**实测**：命中的是这些（`LASR.exe` 字面量）：

```
JavaMachine::isProductive: unknown parent node type:
JavaMachine::isProductive: unknown node type:
JavaMachine::loadClass: failed to load
JVM::stringConversion: cannot convert
parentclass cannot be specified for java.lang.Object
.\Script\Natives\java_render_gfxengine.cpp
.\Script\Natives\java_render_pointer.cpp
.\Script\Natives\java_sound_sound.cpp
.\Script\Natives\java_util_resource.cpp
.\Game\Natives.cpp
```

**实测**：全盘搜索 `CA FE BA BE`（Java class 魔数）→ **整个游戏 0 处**。

**结论**：游戏用一套自研的、语法类似 Java 的语言写逻辑，
编译成自研类格式 **TUFA**，由 `LASR.exe` 内的 `JavaMachine` 解释执行
（`isProductive` + "node type" 说明它执行的是**节点树**，不是标准 JVM 字节码）。
原生侧通过 JNI 风格的本机方法（`.\Script\Natives\*.cpp`）向脚本层暴露引擎能力。

**实测**：`LASR.exe` 里注册的本机方法签名（节选，共 300+ 条）揭示了完整的引擎 API：

```
java.game.Vehicle / Gamelogic / GameLogic / GameMode / Replay / Navigator
java.game.parts.{Chassis, Wheel, WheelRef, SfxTable, CarDifferential, Part, DynoData}
java.gui.*        70 个类：Component, Window, Button, Label, Listbox, TabList, Combobox,
                  PageControl, VSlider, HSlider, Gauge, Browser, View3D, ViewVideo, Template…
java.gfx.{GfxEngine, ParticleSystem, Animation, Viewport, HardGfxFeature, SkidMark, LightType, Texture}
java.sound.{Sound, SfxRef}
java.util.resource.{ResourceRef, GameRef, RenderRef, PhysicsRef, GroundRef, RenderType, GameType}
java.io.{File, FindFile, Input, Hotkey, Controller, Pointer}
java.net.{Friend, MetaServer, HardServer, Network}
java.lang.{Object, String, Integer, Integer64, Float, Math, Vector3, Matrix, Ypr, Thread, Runnable, Class, System}
java.util.{Vector, Config, MemBuffer, BoneAssign, resource.Spring}
```

---

## 2. 容器普查

**实测**（`tools/survey.py`，609 个文件 + 全部 ZIP 成员）：

| 数量 | 格式 | 说明 |
|---|---|---|
| 2225 | **FLZD** | 自研压缩容器，包裹所有 TUFA 类 + `shader.dat` |
| 287 | PNG | 贴图 |
| 52 | **RPAK** | 资源包（`RPAK` v0x200） |
| 43 | DDS | 贴图 |
| 32 | RIFF/WAV | 音效 |
| 32 | ZIP | 存放 FLZD 类 / PNG 的壳 |
| 16 | FSB | FMOD 音频库 |
| 15 | FMOD geometry | `maps/*/*_fmod.geo`，声音遮挡几何 |
| 13 | Ogg Vorbis | 音乐（38 MB） |
| 11 | **INVO v4** | 网格（`.scm` 内嵌 / `.scx` / RPAK 内嵌） |
| 8 | `.matrixdata` | 骨骼动画矩阵 |
| 8 | `.bon` | **纯文本**骨骼层级 |
| 3 | `.fmv` | 自研视频（magic `84 10 FF FF`，非 Bink） |
| 25 | `.gtmp` | **纯文本** GUI Editor 模板 |
| — | `.scm` | **纯文本**材质表（`materials 17 / material 0 fu / type 1 …`）|
| — | `.spl2` | **ASCII** 路径样条，制表符分隔浮点数 |
| — | `.shz` | `shadowz` 光影遮罩（magic `01 00 00 00`）|
| — | `.ptx` | 点云/粒子（`skydome.ptx`）|
| — | `.als` | 纯文本 UI 字体/颜色样式表（`formats.als`）|

### 体积分布（实测 `du`）

```
maps       235 MB   ← maps/texture.rpk 54 MB + 各赛道 *.rpk
vehicles    81 MB
frontend    41 MB   ← frontend.rpk 32 MB
music       38 MB
gui         13 MB
sounds      12 MB
fmv         11 MB
drivers    4.8 MB
java       1.5 MB   ← 全部游戏逻辑只有 1.5 MB
```

---

## 3. FLZD —— 已完全破解 ✅

### 3.1 容器格式（实测，由 `LASR.exe` 机器码直接读出）

13 字节头，小端：

| 偏移 | 类型 | 含义 |
|---|---|---|
| 0 | char[4] | `"FLZD"` (0x445A4C46) |
| 4 | u32 | `payloadSize + 4`（== 文件长度 − 9） |
| 8 | u32 | 解压后大小 |
| 12 | u8 | level，必须 ∈ [9,13] |
| 13 | … | 压缩数据 |

证据 —— 写入端 `LASR.exe` RVA `0x1D00`（打包函数）：

```
001d22  call 0x1850                  ; flzd_encode
001d31  mov dword ptr [esi], 0x445A4C46    ; 'FLZD'
001d37  mov dword ptr [esi+4], ecx          ; payloadSize + 4
001d3a  mov dword ptr [esi+8], edi          ; srcSize
001d3d  mov byte  ptr [esi+0xC], bl         ; level
001d40  add eax, 0xD                        ; total = payload + 13
```

读取端 RVA `0x1D50`（校验 + 调用解压）：

```
001d54  cmp dword ptr [eax], 0x445A4C46
001d69  mov dl, byte ptr [eax+0xC]      ; level
001d6c  sub ecx, 4                      ; payloadSize = [eax+4] - 4
001d89  cmp dl, 9  / cmp dl, 0xe        ; 只接受 9..13
001d9d  add eax, 0xD                    ; 压缩数据起始 = 13
001da2  call 0x1AC0                     ; flzd_decode
```

实际 `flzd_decode(const u8* src, int srcLen, u8* dst, int dstCap, int level)`。

### 3.2 编解码算法

**实测**：不是 LZW（reshax 论坛上的猜测是错的），不是 zlib/FastLZ/LZMA。
是 **Huffman + 二叉树匹配器 + 「符号→字符串」字典链**：

* RVA `0x1570` 初始化一张全局表 `0x75D394[level]`（**已逐项验证**）：
  `1, 3, 5, 11, 17, 37, 67, 131, 257, 521, 1031, 2053, 5021, 9029, 18041`
* RVA `0x1AC0` `flzd_decode`：按 level 分配 3 个 `table[level]` 大小的表 + 4 KB 串缓冲；
  符号 `< (1<<level)-1` 为字面量，否则为匹配
* RVA `0x1710` 「符号展开」：`idx ≤ 255` → 直接输出一个字节；
  `idx > 255` → 输出 `bytes[idx]` 并沿 `syms[idx]` 递归（最多 3998 步）→ 说明符号表里
  存的是**多字节字符串**，不是单纯的距离/长度对
* RVA `0x1680` 二叉树匹配器（`[edx] == -1` 空节点判据，LZMA BT4 风格）
* RVA `0x1850` 与 `0x1760`/`0x17E0` 为编码侧与位读写

### 3.3 我们的做法：**不重写算法，直接跑游戏的代码**

`tools/lasr_flzd.py` 用 **Unicorn x86-32** 把 `LASR.exe` 整幅镜像（含 .bss）
按 `ImageBase` 映射进模拟器，hook 掉 CRT 的 `malloc`/`free`，
然后**调用游戏自己的 `flzd_decode`**，并用 `0x1570` 的初始化例程填表。

这保证输出**逐字节正确**（而不是「我猜的算法大概对」）。

**实测验证**：
* 解出的 Java 类内容与 `LASR.exe` 自己的**写入代码**逐字节吻合：
  写入端 RVA `0x25104A` 构造 `"TUFA" / 4 / 0x1451E / "CONS"`，
  与我们的输出 `54 55 46 41 | 04 00 00 00 | 1e 45 01 00 | 43 4f 4e 53` 完全一致
* `shader.dat` 解出 439,209 B 的 **HLSL/着色器汇编源码**
  （`"ISHDBenchmarkPS11.psh"`, `ps.1.1`, `def c0, 0, 0, 0, 0.375`, `tex t0`, `mad r0, c1, t1, r0` …）
* 每个文件解压后大小与头部声明字段**完全相等**

### 3.4 全量结果

`tools/extract_flzd.py`：**2225 个文件，0 失败，5.1 秒** → `extracted/`

---

## 4. TUFA v4 —— 容器已解，节点树待破 ⏳

### 4.1 分块结构（实测，2224 个类全部自洽闭合）

```
0   char[4] "TUFA"
4   u32     version = 4
8   u32     signature = 0x0001451E   （所有类都相同）
12  …       分块序列，每块 = char[4] tag + u32 size + size 字节数据
```

**实测**：5 个块，顺序固定，解析后偏移正好等于文件长度：

| tag | 内容 |
|---|---|
| `CONS` | 常量池。首 u32 = 条目数（`Bet` = 97），其后为长度前缀字符串等 |
| `FILD` | 字段表 |
| `MTHD` | 方法表 |
| `CLSS` | 类头：`0xFFFFFFFF` + 计数 + 父类/接口索引 |
| `TREE` | **可执行部分**：JavaMachine 的节点图（bytecode 的替代品）|

例（`game/Bet.class`，2183 B）：`CONS@12+1178` → `FILD@1198+168` →
`MTHD@1374+148` → `CLSS@1530+24` → `TREE@1562+613` = 2183 ✅

**实测**：`TREE` 帧结构形如 `<opcode u32> <operand...>`，
如 `Model_Coupe_TornadoR` 的 TREE 开头
`12 000000 | 06 000000 | 14 b4000000 | 16 49000000 | 12 f9020000 | 20 f7020000`

### 4.2 类清单（`out_class_inventory.md`，仓库根，生成物）

**实测**：2224 个类 / 解压后 6,434,427 B，其中
`CONS` 4.10 MB、`FILD` 141 KB、`MTHD` 338 KB、`CLSS` 54 KB、
**`TREE` 1.45 MB（= 真正的逻辑体量）**。

| 组 | 类数 |
|---|---|
| 车辆部件（`vehicles/**`） | 1884 |
| 引擎/逻辑（`java/**`） | 304 |
| 赛道逻辑（`maps/*/classes`） | 28 |
| NPC 驾驶 AI + 着色器（`drivers/*/Main.class`, `shader.dat`） | 8 |

**最大的几个（按 TREE 体积 = 逻辑量）**：
`game/Gamelogic` 33.5 KB、`game/item/IVehicle` 21.3 KB、
`maps/hills/Hills` 18.0 KB、`game/frontend/videoOptions` 15.0 KB、
`game/frontend/controlOptions` 11.8 KB、`game/GameMode` 11.8 KB …

> 注意：`IVehicle` / `Model_*` 这类「车辆部件类」不是网格，
> 而是**车辆参数与零件装配定义**（字段类型 `PartDecal[] / Texture / RenderType /
> ResourceRef / IPart`，方法 `getPrestige` 等）。这正好是重制要的数值数据。

### 4.3 后续 ✅ 全部已完成

* TUFA 解析器已反汇编 → 权威字段定义（`docs/02_VM_INTERNALS.md`）
* `JavaMachine::isProductive` 节点分派表已定位 → 操作码表 100% 定案（`docs/08_VM_OPCODES.md`）
* 反编译器已出：TREE → 可读伪码（`out_pseudo/`，2,216 类 / 90,651 行，`docs/15_CONTROL_FLOW.md`）

---

## 5. RPAK —— 资源包（结构已知）⏳

**实测** 头部（`RPAK` v0x200）：

```
0   char[4] "RPAK"
4   u32     version = 0x200
8   u32     n_deps          ; 依赖包数
12  u32     0
16  …       n_deps 个定长记录，每条含包名（长度前缀），如 "system.rpk", "maps.rpk"
            ; 例如 boulevard.rpk 依赖 system.rpk / maps.rpk / maps\obstacles.rpk / maps\texture.rpk
```

**实测**：资源以 `<u32 标签><u32 大小><数据>` 内嵌。已观察到的标签：

| 标签 | 内容 |
|---|---|
| `ISCX` / `ISCY` | 内嵌 INVO 网格（`.scx` / 变体）|
| `IS..` | 其余内嵌资源同族 |

例：`vehicles\Takura_Tornado_2002.rpk`（19.9 MB）内含 **60 个 INVO 网格**；
`maps\boulevard.rpk`（47.5 MB）内 11 个；`maps\texture.rpk` 54 MB；
`vehicles.rpk` 7.2 MB / 28 个；`particles.rpk` 4 个。

**✅ 已完成**：索引表与解包器全通，命名导出见 `docs/03_ASSETS.md` / `docs/52_RPAK_ASSET_EXPORT.md`
（52 个存档 / 2,019 条目 / 1,218 纹理 PNG / 764 网格 OBJ）。
另有 `frontend.rpk` 内嵌 61 个 DDS + 5 个 PNG（部分资源直接内嵌图片）。

---

## 6. INVO v4 —— 网格格式（头部已解）⏳

**实测** 头部（`L_tailight_glow.scx`，1566 B）：

```
00  49 4e 56 4f   "INVO"
04  u32 4         版本
08  u32 4         ?              （计数）
0C  u32 0
10  u32 0x2c = 44
14  u32 1
18  u32 0xbc = 188
1C  u32 4
20  u32 0xc8 = 200
24  u32 5
28  u32 0x534 = 1332
2C  u32 0
30  u32 0x90 = 144
34  u32 0
38  float 2.0
3C  u32 9
```

即 `<offset, count>` 对序列（子流索引）——与 `LASR.exe` 中
`"Invalid mesh version! -> %s"` 的检查点对应。

**实测** 网格总数（含 RPAK 内嵌）：`.scx/.SCX` 独立文件 11 个 +
`maps/*/meshes/*.scm`（纯文本材质表，非网格）+
RPAK 内嵌 200+ 个（车 60×10、赛道 10×12）。

**✅ 已完成**：顶点 / 索引布局已解并全量导出（`docs/52`），网格 ↔ 贴图材质表绑定见 `docs/53`。
骨骼权重不存在 —— **本游戏没有骨骼动画系统**（类清单实证，`docs/54 §6.1`）。

---

## 7. 其它已识别格式

| 格式 | 状态 | 备注 |
|---|---|---|
| `.bon` | ✅ 明文 | 骨骼层级，可直接读 |
| `.matrixdata` | ⏳ | magic `19 00 00 00`；动画矩阵关键帧 |
| `.spl2` | ✅ 明文 | 制表符分隔浮点路径点（AI/赛道路线）|
| `.scm` | ✅ 明文 | 材质定义表 |
| `.gtmp` | ✅ 明文 | `//GUI Editor template`，界面模板 |
| `formats.als` | ✅ 明文 | 字体/颜色样式表 |
| `locale/LASR.*` | ✅ 明文（UTF-8 BOM）| 多语言文本 |
| `.fmv` | ⏳ | 自研视频（`84 10 FF FF`）；3 个片头 |
| FMOD `.fev`/`.fsb` | ⏳ | FMOD Designer 工程 + FSB 音频库；用 `fsbext`/`fmod_extr` 或 FMOD SDK 可解 |
| `.shz` | ⏳ | `shadowz` 光影遮罩 |
| `.ptx` | ⏳ | 点云（`skydome.ptx`）|
| `.tga`（routes）| ⏳ | 非标准 TGA，magic `00 00 02 00` |
| `shader.dat` | ✅ | FLZD 包裹的着色器源码集（439 KB） |

---

## 8. 明确标注为「推测」的

1. `TREE` 帧的 opcode 语义（`0x12/0x14/0x16/0x20`…）——**尚未验证**。
2. FLZD 里「符号 256..2^L−2 对应多字节字符串」是基于 RVA `0x1710` 展开逻辑的推断，
   未逐步跟踪确认。
3. `TUFA` 头 offset 8 的 `0x0001451E` 在所有类中恒定，推测是引擎/格式签名或哈希，
   **未证实**。
4. `JavaMachine` 的执行模型（树遍历解释 vs. 树→本地代码）——**未证实**。
