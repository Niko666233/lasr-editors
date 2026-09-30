# 22 · 渲染管线（P5-B）

> **一句话**：`shader.dat` 是**完整的着色器源码库**（**175 个**：95 `.psh` + 71 `.vsh` + 9 `.fx`，
> D3D8/9 汇编 + HLSL），命名法直接写明材质构成（`Col`/`TexN`/`Bump`/`Specular`/`Reflection`…
> × `Normal`/`Lightmapped`），光照是 **1 个方向光 + 球谐(SH)环境光 + 半球环境**，
> 车身材质内建 **wreck(撞损)/dirt(泥污) 层**。
> 工具：`tools/shader_dump.py`；产物：`out_shaders/`（175 个源码）、`out_shaders.json`

## 1. `shader.dat` 容器格式

```
<name>\0<u32 size><body>

record_start = 名字起点
body_start   = 名字结束(\0) + 5      (= \0 + u32)
record_end   = body_start + size     ⇒ size == 正文长度
```

**判定方式（穷举变体，不靠猜）**：把 6 种可能读法各自走一遍全文件，只有一种同时满足
三条硬判据 —— **名字全部合规 / 逐条接续精确 / 链尾精确等于文件尾**：

| 读法 | 条目 | 名字合规 | 接续 | 链尾 |
|---|---|---|---|---|
| **`body=名字末+5，end=body+size`** | 175 | **175/175** ✓ | **174/174** ✓ | **0x6b3a9 = 439,209 ✓** |
| `end=名字末+size` | 175 | 3 | 174/174 | 少 5 B ✗ |
| `body=名字末+1，end=body+size` | 175 | 5 | 174/174 | 少 4 B ✗ |
| `end=名字末+1+size` | 175 | 5 | 174/174 | 少 4 B ✗ |
| 其余两种 | 175 | 5 | 174/174 | 少 4 B ✗ |

**踩坑记录（重要）**：第一版用「正则找名字 + ±4 字节容差窗口判定」，得到
**120 条**、`slack {0:120}`、链尾也「恰好在文件尾」——**看起来完全自洽**，
实际漏了 55 条（**9 个 `.fx` 一个没进**），因为：
① 名字正则限死 `.psh|.vsh` ⇒ `.fx` 全被过滤；
② **±4 容差窗口正好把 4 字节的偏移错误吸收掉** ⇒ 错误被掩盖成 `slack=0`；
③ 它当成「假阳性」剔掉的名字里混着真条目。
⇒ **教训：容差窗口不能用来掩盖偏移；用穷举变体 + 多条独立判据让数据自己选。**

**首行分布**：`ps.1.1`×62 / HLSL(`#define`)×42 / `ps.2.0`×24 / `vs_1_1`×18 / `//`×10 /
`ps.1.4`×8 / `//diffuse`×6 / 其它×2

⇒ **基线是 PS1.1（DX8 级硬件）+ 高端走 PS1.4/2.0**。重制时按 ps.1.1 语义复刻即可保证一致，
高版本只是同效果的优化路径（同一材质有两套同名不同版本）。

## 2. 材质命名法（79 个材质族）

```
[前缀]核心[Reflection][Specular][Bump][TexN][Masked]_<光照模式>
```

| 片段 | 含义 |
|---|---|
| `Col` | 顶点色参与 |
| `TexN` / `TexAnim` | N 层贴图 / 序列帧贴图 |
| `Bump` | 法线贴图（配套 `dcl_tangent`/`dcl_binormal`） |
| `Specular` | 高光 |
| `Reflection` | 环境反射（`REFLECTION` 常量） |
| `Masked` | alpha 遮罩 |
| `Layered` / `LayeredV` | 多层地形混合（`LayeredVSpecularReflection` 等） |
| `PalSkinned` / `Skinned` | 骨骼蒙皮（角色） |
| `Slot` | 贴图槽变体 |
| `Rim` | 车体轮廓光 |
| `ZOffset_Normal` / `IntoPara` | 深度偏移 / 抛物面投影（水面、反射） |
| `Normal0/1` | 逐像素光照（0/1 变体） |
| `Lightmapped0/1` | 乘光照贴图 |

代表族：`Layered[V][Specular][Reflection]`、`ColTex2BumpSpecular`、`Tex2MaskedSpecularReflection`、
`TexAnim`、`Chassis`、`water{,_IntoParaboloidNormal0,_Normal1,_Normal2}`、`foam`、`effect_apply[_gamma1/_gamma2]`。

## 3. 顶点输入（法线贴图是标配）

```asm
dcl_position v0      dcl_normal v1      dcl_texcoord0 v2
dcl_tangent v3       dcl_binormal v4    dcl_color0 v5
dcl_texcoord1 v6     dcl_texcoord2 v7
```
⇒ 顶点里带 **切线/副法线**（`Bump` 族）与**顶点色**（`Col` 族 + 车身损伤）。

## 4. 常量寄存器约定（两套，逐着色器 `#define` 已交叉印证）

| 约定 A（多数材质） | | 约定 B（同族高版本） | |
|---|---|---|---|
| `WORLD_VIEW_PROJ` | 0 | `VIEW` / `PROJ` | 0 / 4 |
| `WORLD_VIEW_T` | 4 | `WORLD_T` | 4 |
| `SUN_DIRECTION` | 7 | `SUN_DIRECTION` | 4 |
| `SUN_DIFFUSE` | 8 | `SUN_DIFFUSE` | 5 |
| `SUN_SPECULAR` | 9 | `SUN_SPECULAR` | 6 |
| **`SH_RED` / `SH_GREEN` / `SH_BLUE`** | **10 / 11 / 12** | 7 / 8 / 9 |
| `TEX0/1/2_TRANSFORM` | 13 / 14 / 15 | | |
| `FOG` | 17 | | |
| `MAT_EMISSIVE` | 18 | | |
| `MAT_SPECULAR` | 19 | | |
| `VIEWIT`（世界→视空间转置） | 20 | | |
| `CONST` / `CONST2` | 30 / 31（`0.5,1,2,0` / `0.333`） | | |

**★ 最关键的一条：环境光是球谐（SH）** —— `SH_RED/GREEN/BLUE` 各占一个常量 ⇒
重制时若把环境光当常数色，明暗会明显不同（这是本作观感的一部分）。

另有：`LIGHT0_DIRECTION/UP/DIFFUSE/SPECULAR/AMBIENTDOWN/AMBIENTUP`（**半球环境**，天/地两色）、
`NORMAL_SCALE`、`CLIPPLANES`、`CAMPOS_WORLD`、`D0_ZBIAS`、`REFLECTION`、`ALPHA_FADE`、
`ANIM_SCALE_PHASE` / `ANIM_SCALE2` / `SINCOS0..2`（**植被风摆动画**）、`WORLD_VIEW_T_1/_2`、`WORLD_VIEW_Z`。

## 4b. ★ 9 个 `.fx` 才是渲染器的**正式规格**

`shader.dat` 里除了汇编，还有 **9 个完整 HLSL effect 源文件**（体积最大、信息最密）：

| 文件 | 大小 | 内容 |
|---|---|---|
| `Complex.fx` | 91.3 KB | 材质总库（大部分材质的 effect 定义） |
| `Chassis.fx` | 23.8 KB | 车身 |
| `BreakableGlass.fx` | 23.7 KB | 可破坏玻璃 |
| `Rim.fx` | 20.3 KB | 轮廓光 |
| `Tree.fx` | 18.0 KB | 植被 |
| `Water.fx` | 16.1 KB | 水面 |
| `TexAnimGlow.fx` | 14.0 KB | 序列帧发光 |
| `IntoDepthShadowTexture.fx` | 5.9 KB | 写阴影图 |
| `TexVC.fx` | 5.7 KB | 顶点色驱动 |

它们给出**汇编里看不到的语义**，同一批常量在这里是**带名字的声明**（独立印证了 §4）：

```hlsl
float4x4 WorldViewProjection : register(c0);
float4x4 Projection          : register(c0);   //skinned/slot transform
float4   ParaboloidProjection: register(c0);   // .z = halfspace sign, .w = 1/farplane
float4   ParaboloidD0_ZBias  : register(c1);
float4x3 WorldViewT         : register(c4);
float3   FogBetaRayleighMie  : register(c7);   // BETARAYLEIGHMIE (sum of the two)
float4   FogHG               : register(c8);   // HENYEYGG; [1-g^2, 1+g, -2g]
float3   BetaDashMie         : register(c9);
```

**三个此前没看到的关键点**：

1. **大气散射（fog）是物理模型** —— Rayleigh + Mie 双系数（`FogBetaRayleighMie`）、
   **Henyey-Greenstein 相位函数**（`FogHG`，存 `[1-g², 1+g, -2g]`）、
   `BetaDashMie`。复刻雾/天空必须照这个做，否则远景色调完全不对。
2. **抛物面（dual-paraboloid）环境贴图** —— `ParaboloidProjection` + `D0_ZBias`，
   对应 `water_IntoParaboloid*` / `TexVC_IntoPara` 系列。
3. **`//#define PERPIXEL`** —— 逐像素/逐顶点光照**是同一个 effect 的编译开关**（注释掉的开关）。

采样器有完整职责注解（同一份文件里）：

```hlsl
sampler Sampler0;  //layer1        sampler Sampler4; //lightmap/hemi1
//sampler Sampler1 //layer2        sampler Sampler5; //hemi2
sampler Sampler2;  //layer3        sampler Sampler6; //specular cubemap
sampler Sampler3;  //layer4        sampler Sampler7; //reflection1
                                   sampler Sampler8; //shadow tile
```

⇒ **重制时应先读 `.fx`（语义），再用同名汇编核对（确切的指令级行为）**，
而不是只看汇编猜常量含义。

## 5. 像素侧：贴图层约定 + 车身样例

车身材质（`Chassis_Normal0_0`）是最能说明问题的样例：

```asm
tex t0 //layer1      #define MAT_BASE_OPACITY 0   //BASE = diffuse color, opacity = .a
tex t1 //wreck       #define DIRT 1               //.a = dirt intensity
tex t2 //dirt
mul r1.rgb, v0, t0.a          // 顶点色 × AO(t0.a)
+mul_sat r1.a, 1-v0.a, t1.a   // wreck 强度：(1−顶点色.a) × 损伤贴图.a
lrp  r0.rgb, r1.a, t1, t0     // 与撞损层混合
+mul_sat r0.a, c1.a, t2.a     // dirt 强度
lrp  r0.rgb, r0.a, t2, r0     // 与泥污层混合
mul_x2 r0.rgb, r0, r1         // 乘光照
+mul r0.a, t0.a, c0.a
```

⇒ **车身 = 基础色贴图(t0, α=AO) + 撞损层(t1) + 泥污层(t2)**，
损伤由**逐顶点 v0.a** 驱动（车壳变形/划痕贴图随之显现），泥污由 `c1.a` 统一控制。
**这是复刻"车越撞越花、越野越脏"的关键**，不是后期叠加。

其它约定：`t0 //layer1`、`t1 //layer2`、`t2 //layer3`、`//diffuse layer`、
`//mask the first layer with the second`（地形多层混合）、`v0.a` 作遮罩。

## 6. 后处理与特殊通道

| 着色器 | 用途 |
|---|---|
| `blur.psh` + `blur.vsh` | 全屏模糊（`//2nd layer`/`//3rd layer` 多 tap） |
| `mblur.psh/.vsh` / `mblur_SAFE.psh` | **运动模糊**（含安全变体） |
| `effect_apply.psh/.vsh` / `effect_apply_gamma0/1/2.psh` | 后期合成 + **gamma 校正（三档）** |
| `clear_below.psh` | 清除某深度之下的缓冲（天空/地平线处理） |
| `Rim_Normal0` 等 | 车体轮廓光 |
| `TexVC*` | 顶点色驱动贴图 |
| `water{,_IntoParaboloid*,...}` / `foam_Normal0` | 水面（抛物面反射）+ 泡沫 |
| `LMDepthTest.psh/.vsh`、`ISHDBenchmarkPS11`、`BenchmarkPS20` | 光照贴图深度测试 / 基准（**开发残留**：未注册进引擎表） |
| `BreakableGlass[_Normal1[_old]]`（含 `.fx`） | 可破坏玻璃 |

## 7. 引擎侧：注册与句柄表

* 助手函数 **`0x5303b0`** = 着色器注册/查询；**107 个调用点**，
  全部落在 **`0x508b92` … `0x510774`**（约 30 KB 的一段连续初始化区）；
* 每次调用形如 `push <名片段A>; push 0x6f1be8; push <名片段B>; call 0x5303b0`，
  返回值写入全局句柄表 **`[0x7844e4]`, `[0x7844e8]`, `[0x7844ec]` …**（步长 4）；
* `Layered` 等片段在 `0x50c908–0x50c996` 被 7 次 `push` ⇒ **名字是运行时拼出来的**。

**交叉核对（诚实记录）**：注册**调用点** 107 vs 源库条目 **175** ⇒ **差 68，未配对**。
可能是表驱动循环注册（一个调用点注册多个），也可能有条目从未被使用。
**这一条目前不构成有效判据**，不能据此断言"引擎只用了 107 个着色器"。

## 8. 重制落地建议（按性价比排序）

1. **先做 §5 的车身材质**（基础色+AO+撞损+泥污 四通道，顶点色驱动损伤）——观感辨识度最高；
2. **环境光用 SH**（§4），否则整体明暗不对；
3. 顶点格式按 §3 准备（切线/副法线 + 顶点色，缺一不可）；
4. 地形用 `Layered*` 的多层混合语义（`//mask the first layer with the second`）；
5. 法线贴图族按 `Bump` 后缀，反射族按 `Reflection` + `REFLECTION` 常量；
6. 后处理先做 gamma（`effect_apply_gamma*`）+ 全屏模糊（`r2blur`）。

## 9. 未解 / 待办

* 渲染**通道顺序**（不透明/alpha 排序/天空/粒子/HUD 的先后）与 D3D9 状态块（`shader.dat` 不含状态）；
* 107 注册点 → 175 条目的配对（是否表驱动循环注册）；
* `effect_apply` 三档 gamma 的切换条件（画质设置？）；
* `Slot` / `IntoPara` / `TexVC` 变体的运行时含义；
* 顶点的确切字节布局（切线是 float3 还是压缩）——需回到网格流（P3 已有 44 B 记录结论，可对接）。
