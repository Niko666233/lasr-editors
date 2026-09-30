# 25 · 渲染后端三档（DX7 / DX8 / DX9）与客户端设置格式

> 起点是用户的一条实机情报（2026-09-28）：
> **「ReShade 注入到游戏的 DX9 模式下整个画面是异常的（哪怕零滤镜），但在设置里改成 DX8 或 DX7 就正常。」**
> 这条情报解释了此前所有关于"渲染管线不普通"的疑点，并且**可静态验证**。

## 1. 设置项 = 渲染模式（源码级证据）

`out_pseudo/java/classes/gfx/GfxEngine.java` —— Java 侧的图形设置引擎，19 个特性项：

```
GFX_FSAA=0  GFX_RESOLUTION=1  GFX_DX_COMPATIBILITY=2   <-- 渲染模式
GFX_REFLECTORDETAIL=3  GFX_VIEWRANGE=4  GFX_WORLDDETAIL=5  GFX_TEXTUREDETAIL=6
GFX_SHADOWDETAIL=7  GFX_OBJECTLODDETAIL=8  GFX_OBJECTDETAIL=9  GFX_PARTICLE=10
GFX_SPRITE=11  GFX_PFX_BLUR=12  GFX_PFX_GLOW=13  GFX_PFX_NOISE=14
GFX_PFX_CONTRAST=15  GFX_DYNENVMAP=16  GFX_MIRROR=17  GFX_GAMMA=18
```

`GfxEngine.init()I`（Java 包装）把模式当**参数**交给原生实现：

```
local0 = Config.video_settings[GFX_DX_COMPATIBILITY];     // 缺省 = 2
local1 = Config.video_settings[GFX_FSAA];
videoMode = new VideoMode(Config.videoMode.width, .height, .depth, .windowed);
local2 = GfxEngine.init(videoMode.width, videoMode.height, videoMode.depth,
                        videoMode.windowed, local1, local0);   // 6 参原生调用
```

初始化失败时的错误串直接点名两套后端：

```
GFX_INIT_OK = 0            GFX_INIT_NO_DX9 = 1
GFX_INIT_NO_DX7_CARD = 2   GFX_INIT_NOT_ENOUGH_MEMORY = 4
GFX_INIT_TOO_SLOW_CPU = 8  GFX_INIT_OLD_DRIVER = 16
"$100|DX9.0c not found..."  "$101|This game requires at least DX7 compatible graphics card."
```

⇒ **三档后端**：DX7（固定功能）/ DX8（ps.1.1、ps.1.4）/ DX9（ps.2.0、.fx）。
缺省值 **2 = DX9**。

## 2. 这一发现解释了什么

| 现象 | 解释 |
|---|---|
| ReShade 在 DX9 下画面异常、DX8/DX7 正常 | DX9 路径**非标准**（引擎自建渲染接口，见 docs/24），DX8/DX7 路径走标准 API |
| `shader.dat` 175 条首行是 `ps.1.1`×50 + `ps.1.4`×6 + `ps.2.0`×17 + HLSL(`#define`)×26 | **不是**"多次构建残留"，而是**两套后端各自的着色器**（DX8 用 1.1/1.4，DX9 用 2.0/HLSL） |
| docs/23 §6 的"寄存器布局矛盾（`.fx` 源码 vs 编译产物）" | 同一素材的 DX9 声明与 DX8 汇编变体并存在一个容器里 |
| `GFX_PFX_BLUR/GLOW/NOISE/CONTRAST` | ↔ 容器里的 `blur` / `mblur` / `effect_apply*` 后处理着色器 |
| `GFX_MIRROR` | ↔ 材质变体轴 `REFLECTION_PLANAR` |
| `GFX_GAMMA`（本机值 = 3） | ↔ `effect_apply_gamma0/1/2` **三档** gamma |
| `GFX_DYNENVMAP` | ↔ `LMPointLightCube`（点光立方图捕捉）与 `REFLECTION_*` 动态分支 |

## 3. 客户端设置文件格式（`save\game\options`）

来自 `java.util.Config.save()/load()`，**不是猜的**：

```
"SDAT"        4 B
00 xx xx      3 B
u32           文件大小（360）
u32           SAVEFILEID = 0xFEDCBA98 (-19088744)
u32           SAVEFILEVERSION = 37
u32           featureCount = GfxEngine.getFeatureCount() = 19
u32 × 19      各特性当前值（顺序同 §1 的编号）
u32 × 4       videoMode.width / height / depth / windowed
u32 …         车辆细节、各路音量、玩法选项（省略）
```

**本机实读**（`tools/options_edit.py --show`）：

```
[ 0] GFX_FSAA=2   [ 1] GFX_RESOLUTION=19   [ 2] GFX_DX_COMPATIBILITY=2  (DX9)
[ 3..11] 各项细节=2   [12] PFX_BLUR=1  [13] PFX_GLOW=1  [14] PFX_NOISE=0
[15] PFX_CONTRAST=2   [16] DYNENVMAP=1  [17] MIRROR=0  [18] GAMMA=3
videoMode = 1024×768×32, windowed=1
```

⇒ 可以直接**程序化切换渲染后端**（`tools/options_edit.py --set 2=1`，自动备份 ✓），
不必驱动游戏 UI。

## 4. 原生侧的锚点（静态）

- **`Direct3DCreate9` 唯一调用点 `0x502a85`**，所在函数起点 **`0x5026d0`**（SEH 序言 `6a ff 68 22 ff 6d 00`）。
  ⇒ **`0x5026d0` = DX9 后端初始化**。
- 它唯一的调用者 **`0x6e53e5`**：`mov ecx, [0x781e80]` → `call 0x5026d0`。
  同区域（`0x6e5390`–`0x6e53f5`）是**一排同构小桩**，每个换一个对象全局（`0x77cddc` / `0x77cde8` / `0x781e80`）
  再调一个 init ⇒ 这一排就是**各后端的入口**。
- **渲染器单例 `0x781e80`**：全文件 **853 处引用**，且有 getter（`0x4c3db1: mov eax, 0x781e80; ret`）。
- 相邻的全局状态块：`0x781e00` = `IDirect3D9*`、`0x781e04`（1658 引用，引擎自己的渲染接口）、
  `0x781e0c` / `0x781e10`（在 `0x4ffef55` 的渲染器初始化里被赋值）。
- ⚠ 相对调用陷阱：`0x5026d0` 的调用是 `E8 rel32`，**用 4 字节立即数搜引用会得 0 处**（我踩过）。

## 5. 仍未闭合

1. **DX 模式值 → 后端的映射：未定，且我猜错过一次。**
   - 推断依据（弱）：默认值 2、错误串只点名 DX9/DX7。
   - ⚠ **实测否定**：把 `[2]` 改成 **1** 后运行，游戏**连窗口都不出现**、CPU 只走 **0.125 s** 就彻底停住
     ⇒ 1 不是"能用的 DX8"（或触发了阻塞式报错框）。
   - ⚠ **另一处推断也要撤回**：DX9 模式下 `d3d9.dll` **在 0.0 s 加载**，这**不能**作为"处于 DX9 模式"的证据
     —— `d3dx9_30.dll` 是静态导入，它自己就依赖 d3d9。**任何模式都会加载 d3d9.dll**。
   - 下一步：试 **0**（若 0=DX9 成立，说明映射是倒序的 `0=DX9/1=DX8/2=DX7`），
     判据 = 游戏**是否出现窗口 + 是否加载 `d3d8.dll`/`ddraw.dll` + 像素是否变化**。
   - ★ **实测（值 0）**：**游戏真的在渲染** —— 窗口 1024×768 出现，像素指纹每 15 s 都在变（连续 12 次）。
     但加载的图形 DLL 仍只有 `d3d9.dll` + `d3dx9_30.dll` + NVIDIA `nvd3dum.dll`/`nvldumd.dll`
     （**没有** `d3d8.dll` / `ddraw.dll`）。⇒ **0 是"能用档"，但它仍走 d3d9.dll**，
     三档映射**依然未定**（0/1/2 与 DX7/8/9 不是简单的一一对应）。
   - ★★ **探针漏洞（已定位）**：值 0 下游戏在渲染，但 **170 s 内 `Direct3DCreate9` 断点从未命中**。
     原因：`Direct3DCreate9` 发生在**启动最初**（`d3d9.dll` 刚加载就调用），而我的断点是在
     收到 `LOAD_DLL` 事件**之后**才装上的 —— **LOAD_DLL 通知晚于游戏代码执行** ⇒ 竞态漏抓。
     修法：断点改插在**静态已知的调用指令 `0x502a85`**（LASR.exe 内，进程第一刻即可下）。
   - ★ 更可靠的做法：**让用户在设置界面里切一次**，然后 diff `save\game\options` 的第 32 字节 ——
     一次操作即可定死映射（这也是唯一能把"值→后端"钉死的低成本实验）。
2. **原生方法表缺 `GfxEngine.init`**（1,523 条里参数最多 4 个 int，签名 `(IIIIII)I` 零命中）
   ⇒ 存在**第二条原生注册路径**（非 `registerNative` 那条），未找到。
3. **游戏在本机卡在启动阶段**（CPU 忙但从不进入 D3D；DX9 值下 330 s、DX8 值下更早），
   与模式无关地存在 ⇒ 环境/前置条件问题，原因未定（见 §6）。
4. 三个后端各自的**通道顺序**（动态工具链已就绪但还没跑到能采集的状态，见 docs/24）。

## 6. 动态工具链（本机无编译器/调试器，纯 Python 实现）

| 工具 | 作用 |
|---|---|
| `tools/d3d9_tracer.py` | 迷你调试器：`CreateProcess(DEBUG_ONLY_THIS_PROCESS)` + **硬件执行断点**（Dr0–Dr3，无需注入代码）→ 挂 `d3d9!Direct3DCreate9` → 顺 vtable 找到 `CreateDevice` → 设备 vtable 的 4 个槽（Present/BeginScene/Clear/DrawIndexedPrimitive）→ **每次命中读 `[esp]` = 调用者返回地址** = 通道顺序。含 `--nohook`（对照）、`--probe`（外部探活）、断点组轮换、逐条落盘 |
| `tools/run_probe.py` | 不挂调试器的健康探针：CPU 时间、`EnumWindows` 窗口标题/类名、模块表、**窗口像素指纹**（BitBlt+GetDIBits，判断是否真在绘制） |
| `tools/options_edit.py` | 读/改 `save\game\options`（含备份、`--restore`） |

**已经用它们确证的事实**：

- 游戏窗口标题 = **`LA Street Racer build 1183 (Jan 24 2007 16:12:55)`**，窗口类 `INVICTUS`（⇒ 构建日期 2007-01-24 ✓）
- **挂调试器本身不影响游戏**（`--nohook` 对照：CPU 与窗口行为同不调试时一致）
- DX9 模式下：`d3d9.dll`/`d3dx9_30.dll` 在 **0.0 s** 就加载（被 d3dx9 依赖带入），
  但 **330 s 内从未调用 `Direct3DCreate9`**，CPU 却在忙 ⇒ **DX9 路径在本机卡在进入 D3D 之前**
- 该结论与用户情报（DX9 模式不普通）**互相印证**
