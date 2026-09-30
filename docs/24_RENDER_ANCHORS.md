# 24 · 渲染锚点与通道顺序（尝试记录）

> **结论先行**：本轮**拿到了可靠的 D3D9 锚点**、"游戏在运行时用 D3DX 编译着色器"的**硬证据**、
> 以及驱动能力门控值；但**渲染通道顺序没有拿到** ✗ —— 并且我找到了**失败的确切原因**，
> 在此如实记录，不用噪声硬凑。
> 工具：`tools/d3d9_device.py`、`tools/device_calls.py`、`tools/d3d9_calls.py`、`tools/pass_names.py`

## 1. ✅ 已证实的锚点（字节级）

| 事实 | 证据 |
|---|---|
| `Direct3DCreate9` 全程序**只被调用 1 次**，在 `0x502a85` | IAT `0x6e7374` → 跳转桩 `0x5f918a`（`FF 25`）→ `call 0x5f918a` 的唯一调用点 |
| 参数 `push 0x20` ⇒ **SDK 版本 32** | 紧随其后的 `push 0x20` |
| 返回值写入 **`[0x781e00]` = `IDirect3D9*`** | `0x502a8c: mov [esi+0x87c], eax` / `0x502a92: mov [0x781e00], eax` |
| `[0x781e00]` 另有 **1 处写、4 处读** | `0x502a93`(写) / `0x4ff152, 0x505bed, 0x509ed1, 0x543654, 0x54367b`(读) |
| 其中 `0x4ff152` 是 `GetAdapterDisplayMode`(slot 14/0x38)；`0x505bec` 是 `GetAdapterIdentifier`(slot 5/0x14) | 反汇编 + 参数个数吻合（3 参 ✓）；输出缓冲 `[0x782868]` |

**注意**：exe 用的是**导入跳转桩**（IAT 全文件只有 `FF 25` 一处引用）⇒ 任何"找 `call [IAT]`"的
写法都会 0 命中 ✗，必须追 `call <桩地址>`（`E8 rel32`，目标精确相等）✓。

## 2. ★★ 游戏**在运行时**用 D3DX 编译着色器（推翻 docs/22 §10）

`d3dx9_30.dll` 的导入表里有完整的 FX/汇编编译与反射 API，且**每个都有精确调用点**：

| D3DX 函数 | 调用点 | 含义 |
|---|---|---|
| `D3DXAssembleShader` | `0x530414`, `0x530510` | 汇编着色器编译（`ps.1.1/vs_1_1` 那批） |
| `D3DXAssembleShaderFromFileA` | `0x530552` | 同上（从文件） |
| **`D3DXGatherFragments`** | `0x530606` | **FX 片段采集 = `compile_fragment` 的实现** |
| **`D3DXGatherFragmentsFromFileA`** | `0x530635` | 同上（从文件） |
| `D3DXCreateFragmentLinker` | （导入即存在） | FX 片段链接 |
| `D3DXGetShaderConstantTable` | — | 从着色器反射常量表（引擎据此设 `cN`） |
| `D3DXSHRotate` / `D3DXSHEvalHemisphereLight` | — | **球谐 + 半球光求值**（独立印证 `compute_ambient` ✓） |
| `D3DXFillTexture` / `D3DXFilterTexture` | — | 程序化填充 / mip 生成 |
| `D3DXCreateTeapot/Sphere/Torus` | — | 调试几何体（开发残留 ✓） |
| `D3DXSaveTextureToFileA` | — | 贴图导出（开发工具残留 ✓） |
| 矩阵：`PerspectiveFovRH` **与** `LookAtLH/...LH` 并存 | — | 右手系为主、混用左手系 |

**⇒ docs/22 §10 的结论是错的 ✗，必须修正**：

* 我当时用「`compile_fragment` / `pixelfragment` / `D3DXCompileShader` 在 exe 里 0 命中」推出
  「编译器不在游戏里 ⇒ shader.dat 是构建期产物」。**错在哪**：这些是 **D3DX FX 语法的关键字**，
  由 `d3dx9_30.dll` 内部处理，**本来就不该出现在 exe 的字符串里** —— 我把"exe 里没有"误当成"游戏里没有" ✗。
* **正确结论**：引擎会**在载入时用 D3DX 编译这些着色器**（`0x5303b0` 附近的着色器子系统，
  正是之前找到 107 个注册点的那个助手 ✓），**编译结果缓存进 `shader.dat`**。
* **因此对复刻的影响**：`.fx` 源码**就是引擎实际编译的东西**，其寄存器声明**是权威的**；
  缓存中的编译产物可能是**上一次构建留下的旧版本**（这正好解释了 docs/23 §6 的寄存器编号矛盾 ✓✓）。

## 3. ✅ 其它附带证据

* **驱动能力门控**：`cmp [0x7827c4], 0xfffe0101` / `cmp [0x7827cc], 0xffff0101`
  ⇒ 引擎按**驱动版本**决定是否启用某些功能（`0x4ffb74`/`0x4ffbb9`/`0x4ffc0b` 三处）；
  默认值在 `0x502bef`/`0x502bf9` 被写成 `0xfffe0000` / `0xffff0000`。
* **厂商门控**：`0x505bff: cmp [0x782c90], 0x8086`（Intel 的 VendorId）⇒ **针对 Intel 驱动的特判**。
* **着色器路径/画质选择**：初始化函数里成对调用
  `0x530180(1,1)` / `0x5301a0(1,1)` / `0x530180(0,2)` / `0x5301a0(0,2)`
  ⇒ 两个函数 × (模式, 档位) 的 2×2 组合（**推断**：着色器路径与画质档位，未定论）。

## 4. ✗ 渲染通道顺序：**没拿到**，以及确切原因

我试了三条路，全部失败，原因如下（记录下来避免重复踩）：

1. **靠 `call [reg+disp]` 的 disp 反推 D3D 槽位** ⇒ 失败。
   全 `.text` 里有 4254 处形似命中，但筛完仍是噪声：
   报出「`WheelRef.setForce` 里调用 `Present`、Δ=32 KB」这种明显荒谬的归属 ✗。
   根因：MSVC 把 vtable 项**缓存**到寄存器/栈槽后 `call ebx` /
   `call [ebp-x]`，`disp` 字段与对象**毫无关系** ✗。
2. **按"（函数, 寄存器）分组 + 核心槽位"过滤** ⇒ 仍失败：引擎把 D3D 包在**自己的接口**里，
   `[0x781e04]`（1658 处引用）的 vtable 槽号**碰巧与 D3D 编号部分对齐**
   （44/89/90/92/103/107 对 BeginScene/顶点声明/FVF/流/索引 ✓），一度骗到了我；
   但用**数据流精确追踪**（`mov reg,[0x781e04]` → `mov vreg,[reg]` → `call [vreg+N]`，91 个加载点、
   25 处调用）后，得到的是 `SetClipStatus`×9、`GetLightEnable`×5，
   且 `BeginScene` 位置上**带了 2 个参数**（D3D 的 BeginScene 是 0 参 ✗）
   ⇒ **该对象不是 IDirect3DDevice9**，只是**槽号相似** ✓ —— 这条判别（**用参数个数否证槽位映射**）
   是有效的，值得记住 ✓。
3. **指望 Java 侧给顺序** ⇒ 失败：全库 `render|draw` 只命中 6 个文件
   （`Track/Vehicle/Camera/IVehicle` 等），渲染循环在原生侧 ✓。

**要拿到通道顺序，下一步需要**（二选一）：

* **静态路线**：先定位**引擎自己渲染器对象**的 vtable
  （找构造里写 vtable 的 `mov [obj], offset` 或 `[0x781e04]` 被写入处），
  再用**参数个数 + 参数特征**逐槽位命名（本轮已验证这套判别可行 ✓），
  最后按帧函数的 `call` 目标序列排序；
* **动态路线（需要实机）**：在调试器里对 `IDirect3DDevice9::DrawIndexedPrimitive` 下断点，
  读返回地址栈即可直接得到"每帧按顺序经过哪些函数" —— 这是**唯一又快又准**的路子。
  ⚠ 这一条**需要你实机**（本机无法运行游戏），是否走这条请示意。

## 5. 本轮工具（都可复用）

| 工具 | 作用 |
|---|---|
| `tools/d3d9_device.py` | 导入表解析（IAT VA 修正：第 5 字段才是 FirstThunk）、追导入跳转桩、`refs`、capstone 反汇编 |
| `tools/d3d9_calls.py` | D3D9 vtable 槽号表（**从真 d3d9.h 解析**，含 `DrawIndexedPrimitive`=85/0x154、`SetRenderState`=60/0xf0 等） |
| `tools/device_calls.py` | 按**数据流**追踪某全局对象的 vtable 调用（本轮判定"不是设备"的关键工具 ✓） |
| `tools/pass_names.py` | 用 `out_native_methods.csv` 的 **1523 个真实函数入口**给调用点归属命名 |

**教训（已写进技能）**：vtable 槽位**不能只靠 disp 反推** ——
一是 MSVC 会缓存 vtable 项、二是引擎可能把 API 包一层而槽号**碰巧对齐**；
必须用**参数个数/参数特征**二次否证 ✓。
