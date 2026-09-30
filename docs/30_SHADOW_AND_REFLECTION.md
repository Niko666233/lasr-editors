# 30 · 阴影与反射：着色器级实证（本轮权威结论）

> **本文对 `docs/23_MATERIAL_SPEC.md` 的阴影结论做**细化**（不是推翻，是补全）。**
> `docs/23` §199–201 的 `.fx` 源码表列出**四种**阴影模式，其中 `SHADOW_F` = **4 抖动采样 PCF**；
> 但 **`SHADOW_A`（1 次采样 + 1/256 偏差斜坡）才是"出货用"**的那条，
> 本轮读到的 `LMTexShadowFactor.psh`（ps.2.0 汇编版，全文 14 行）正是 `SHADOW_A` 的形态
> ⇒ **软边不是靠接收端内联 PCF，而是靠独立的滤波通道**（§2.2）。
>
> ★★ **两条独立判据同时确认阴影图尺寸 1664 × 1024**：
> ① `.fx` 源码里 `SHADOW_F` 的抖动半径 `(0.00060096, 0.0009765625) = (1/1664, 1/1024)`（docs/23 §201）
> ② 二进制里 `push 0x680` / `push 0x400`（`0x4c1bd5`–`0x4c1c2f`，全 `.text` 仅 3 处），
>    紧跟 `call 0x53d960` 且句柄写入 `0x77a770` / `0x77a774`（本文 §1.2）
> —— 此前"1664 不是任何 push 立即数"的阻塞**就此解除**。

## 1. 阴影图的本体（投射端）

### 1.1 `IntoDepthShadowTexture.fx`（5882 字节，ps_2_0 / vs_2_0）

```hlsl
sampler Sampler0;

void ps_main(in float4 tc : TEXCOORD0, out float4 vColorOut : COLOR)
{
    vColorOut = tc.z;                      // 只输出投影深度
}

void ps_mainuv(in float4 tc : TEXCOORD0, in float2 tex_tc : TEXCOORD1,
               out float4 vColorOut : COLOR, out float vDepth : DEPTH)
{
    float4 col  = tex2D(Sampler0, tex_tc);
    float depth = tc.z + (col.a < 0.3 ? 1.0 : 0.0);   // ★ alpha 测试偏置
    vColorOut = depth;                     // ★ 深度同时写进【颜色】和【深度】
    vDepth    = depth;
}
pixelfragment MainUVPS = compile_fragment ps_2_0 ps_mainuv();
pixelfragment MainPS   = compile_fragment ps_2_0 ps_main();
```

**要点（可进重制规格）**

| 项 | 值 | 说明 |
|---|---|---|
| 深度载体 | **颜色 + 深度双写** | `vColorOut = vDepth = depth` ⇒ 接收端既能读颜色也能读深度 |
| alpha 测试 | **`+ (col.a < 0.3 ? 1.0 : 0.0)`** | 透明片被打到范围外 ⇒ **不投影阴影**（避免树叶/栅栏投出实心影） |
| 阈值 | **0.3** | 硬编码 |
| 投影坐标 | `dp4 oT0.x, r1, c[TEX0_TRANSFORM]` | **只用 .x** ⇒ 一维投影深度 |
| 骨骼槽 | **70** | `float4x3 BoneWorldViewT[70]` / `Slots[70]` |
| 顶点变体 | 6 种 | normal / skinned2（2 骨） / palskinned1–4（1/2/3/4 骨权重） |
| 硬件坑（原文注释） | `iBlendIndices.z * 256.005` | "compensate for the lack of UBYTE on Geforce 256 * 3" |
| `Slots[]` 布局 | `.xyz = axis`，`.w = pos`，第 3 行 `.x = diff_intensity, .y = spec_intensity, .z = variation_index, .w = posz` | 每实例的光照参数 |

### 1.2 阴影图的分配（静态，`0x53d3c0`）

- 请求尺寸 **1664 × 1024**，**两张**（句柄全局 `0x77a770` / `0x77a774`）
- `0x53d960` 是转发桩（`mov ecx,[0x782da0]; jmp 0x53d3c0`）⇒ 真函数 `0x53d3c0`
- `0x53d3c0` 内含 **SEH**（`fs:[0]`）+ **设备特判**：
  `cmp [0x782c90], 0x8086`（厂商 = Intel）、`cmp [0x782c94], 0x2572`（设备 = 82865G 集成显卡）
  ⇒ 命中则走**降级分支**：先算 **二的幂**，再按 `[0x782758]`（宽上限）/ `[0x78275c]`（高上限）夹紧
- ⇒ **1664×1024 是"请求值"，实际分辨率随显卡降级**（重制时应把它当画质档位而非固定常量）

## 2. 阴影的接收

### 2.1 `LMTexShadowFactor.psh`（**全文 14 行**）

```hlsl
ps.2.0
dcl_2d s0
dcl_2d s1
dcl t0.xy
texld  r0, t0, s0
texld  r1, t0, s1
mul r0.a, r1.r, c0.a      ; ★ 阴影因子走【alpha 通道】，再乘常量
mov oC0, r0
```

⇒ **单次采样** ⇒ 接收端**没有** PCF ✗。阴影因子（阴影图的 **R 通道**）乘进 **alpha**，
再交给**固定功能混合**去变暗 ⇒ 与 `docs/23` §8 的 8 种混合模式衔接（阴影是靠**混合**生效的）。

### 2.2 软边从哪来：独立滤波通道

| 着色器 | 采样数 | 作用 |
|---|---|---|
| **`LMTexRadFilter.psh`** | **16** | 8 个纹素坐标（`t0..t7`，各自 `.xyzw` 打包两组 UV）各采 2 次；权重 `c0=0.1`、`c1=0.2` ⇒ **中心加权的径向滤波** |
| `LMTexMin.psh` | 5 | 5 个采样取 `min`（取最暗）⇒ 阴影/层合并 |
| `tile_shadow.psh` | 0 | `mov oC0, c0` ⇒ 地块阴影是**平涂常量色** |

`LMTexRadFilter` 的取样模式（原文）：
```hlsl
mov r0.xy, t0.wzyx      ; ★ 一个 4 分量插值器里打包了两组 UV
texld r0, r0, s0
```
⇒ **用一个纹理坐标寄存器承载两组 UV**，是 2006 年的插值器带宽节省技巧。

## 3. 反射：512×512 那个每帧一次的离屏通道（定性完成）

### 3.1 判据（着色器侧，独立于二进制侧）

`Tex2MaskedSpecularReflection_Lightmapped1.psh`（ps.1.4）：

```hlsl
texld r4, t4_dw.xyw   //reflection cubemap      ← ★ `.xyw` 投影采样
...
mul r4, r4, c5
mad r0.rgb, r4, r5.a, r0 //add envmap
```

`water_Normal2.psh`（ps.1.4）注释原文：
```
// T2 : Projective Texture Coordinates for Reflection/Refreaction Maps
```
且 `texcrd r4.xy, t4_dw.xyw // renderable textures` ⇒ **"renderable texture" = 渲染出来的纹理**。

### 3.2 与二进制侧互证

| 判据 | 二进制侧 | 着色器侧 |
|---|---|---|
| 尺寸 | **512×512**（`push 0x200`×2 @ `0x509097`/`0x5090b9`） | 投影采样（`.xyw` / `_dw`） |
| 格式 | `D3DFMT_A8R8G8B8`（`push 0x15`） | 颜色贴图（非深度） |
| 缓冲数 | 成对创建（ping-pong） | 每帧一次渲染后当纹理用 |
| 频率 | 每帧恰好 1 次（`0x504a20`，实机 953 帧统计） | 反射要跟相机走 ⇒ 必须每帧更新 |

⇒ **结论：该通道 = 投影反射/环境贴图（动态反射）** ✓ —— **不是**阴影通道（1664×1024）

## 4. 顺带坐实的：8 种图层混合模式（着色器级）

`Tex2SpecularReflection_Lightmapped1.psh` 原文（`LAYER2MODE_*`）：

```hlsl
#if defined(LAYER2MODE_MULTIPLY)     mul r0.rgb,r0,r1
#elif defined(LAYER2MODE_MULTIPLY2X) mul_x2 r0.rgb,r0,r1
#elif defined(LAYER2MODE_ADD)        mad r0.rgb,r1,c7.a,r0
#elif defined(LAYER2MODE_SCREEN)     mad r0.rgb,1-r1,r0,r1
#elif defined(LAYER2MODE_BLENDTA)    lrp r0.rgb, r1.a,r1,r0
#elif defined(LAYER2MODE_BLENDVA)    lrp r0.rgb, v0.a,r1,r0
#elif defined(LAYER2MODE_BLENDC)     lrp r0.rgb, c7.a,r1,r0
#endif
+mul r0.a, r0.a, c0.a                // opacity
mul_x2_sat r0.rgb, r0, r2            // ★ 乘光照贴图（×2 饱和）
mad r0.rgb, r3, c1, r0               // 加镜面（specular cubemap）
mad r0.rgb, r4, c1.a, r0             // 加环境（reflection cubemap）
```

⇒ `docs/23` §8 的 8 种混合公式**逐条对上** ✓（含 `MULTIPLY2X` 的 `mul_x2` 与光照贴图的 `mul_x2_sat`）。

## 5. 遗留（✗）

- `0x53d3c0` 里"二的幂 + 夹紧"的**具体公式**（`[0x6ebfa0]` / `[0x6e766c]` 两个常量值）未读
- 两张阴影图（`0x77a770`/`0x77a774`）是**双缓冲**还是**两个光源**未定
- `IntoShadowTexture_Alpha.psh` 是 **ps.1.1** 版投射端，与 ps.2.0 版（`IntoDepthShadowTexture.fx`）的
  分支条件未定（推测与 `docs/25` 的三档渲染模式对应，未验证）
