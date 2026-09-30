# 23 · 材质规格表（P5-B 续：`.fx` 结构）

> **一句话**：9 个 `.fx` **不是** D3D9 effect 框架文件（里面没有 `technique`/`pass`），
> 而是 **HLSL 函数库 + 编译期 `#define` 开关**；一个材质 = **变换 × 图层 × 光照** 三段组合，
> 与编译产物名字的命名法完全对应。
> 工具：`tools/fx_spec.py`；产物：`out_fx_spec.json`

## 1. 组合模型

```
顶点着色器 = vs_transform_*  ×  vs_layer_*  ×  vs_lighting_*  ×  vs_fog
像素着色器 = ps_layer_*      ×  ps_lighting_*
```

**变换段**（`Complex.fx`）：
`vs_transform_normal`、`vs_transform_skinned2`、`vs_transform_palskinned1..4`、
`vs_transform_intopara`、`vs_transform_slot`
→ 正好对应名字里的 `Skinned / PalSkinned / IntoPara / Slot` ✓

**图层段**：`vs_layer_{col, vcol, tex, vcoltex, coltex, tex2, vcoltex2, coltex2, tex3}`
→ 正好对应 `Col / TexVC(Vcol) / Tex2 / Tex3 / ColTex2 / Masked…` ✓

**光照段**：`vs_lighting_{diffuse, diffuse_lightmap, diffuse_projdepthshadow, spec, specref,
planarspec, ref, pararef, planarref, diffusebump, specularbump}`、
`vs_fog`、`vs_projdepthshadow`；像素侧 `ps_lighting_{diffuse, specref, maskedspecref,
*_projshadow, lightmap_*, *_bump, intopara_*}`

**辅助函数**：`compute_ambient(normal)`、`compute_fresnel(view, normal)`、`GetReflection`、
`GetSpecular`、**`inShadow(projshadow_tc, uniform int method, uniform int inverse)`**、
**`ApplyFog(base_color, …)`**

## 2. 变体轴（`#define` 家族）

| 家族 | 取值 | 是否出现在**着色器名字**里 |
|---|---|---|
| `PERPIXEL` | 有/无 | ✗（编译开关） |
| `LAYERMODE_*` | `MULTIPLY` `MULTIPLY2X` `ADD` `SCREEN` `BLENDTA` `BLENDVAT` `BLENDC` `BLENDVA`（8） | ✗ |
| `REFLECTION_*` | `OFF` `CUBE` `PARA` `PLANAR`（4） | ✗（`Planar` 只在函数名里 ✓） |
| `SPECULAR_*` | `OFF` `NORMAL` `PLANAR`（3） | 部分（`Specular` ✓） |
| `SHADOW_*` | `OFF` `Z` `F` `A`（4） | 部分（`ZOffset/Shadow` ✓） |
| `DEPTHSHADOW_*` | `Z` `FLOAT`（2） | ✗ |

⇒ **名字只编码一部分轴**，其余（层混合模式、反射模式、阴影模式、逐像素开关）
是**运行时编译期开关**。所以 175 个条目不是全部组合，而是**出货资产实际用到的那批组合的快照**。

## 3. 逐材质族的常量寄存器布局（**每族不同**）

| 文件 | 布局（`cN: 名称`） |
|---|---|
| `Chassis.fx` | c0:`WorldViewProjection/Projection/ParaboloidProjection/diffuse_color` · c1:`ParaboloidD0_ZBias/render_reflection_intensity/dirt_intensity` · c4:`WorldViewT` · c7:`FogBetaRayleighMie` · c8:`FogHG` · c9:`BetaDashMie` · c10:`BetaDashRayleigh` · c11:`SunDirection` · c12:`SunDiffuse` · c13:`SunSpecular` · c21:`MaterialSpecular` · c22:`FresnelFactor` · c23:`ViewIT` · c26:`ProjectedDepthShadowMatrix` · c30:`World` |
| `BreakableGlass.fx` | 同上（+ c2:`sun_direction` c3:`sun_diffuse` 备用组） |
| `Complex.fx` | c0:`WorldViewProjection/Projection/diffuse_color` · c1:`layer_const` · c2:`ParaboloidProjection/specrefmask_weights` · c3:`ParaboloidD0_ZBias/spec_mat_x_light` · c4:`WorldViewT/diff_light` · c5:`bump_intensity_spec/layer_tiling` · c6:`render_reflection_intensity/shadow_depth_offset/specrefmask_const` · c7:`FogBetaRayleighMie/sun_color` · c8:`FogHG/paratr` · c9:`BetaDashMie` · c10:`BetaDashRayleigh` · c11:`SunDirection` · c12:`SunDiffuse` · c13:`SunSpecular` · c21:`SunDirectionForPlanarSpecular` · c22:`MaterialDiffuse` · c23:`MaterialEmissive` · c24:`MaterialSpecular` · c25:`FresnelFactor/BumpIntensity` · c26:`TileUV12` · c27:`TileUV3` · c28:`Tex1Transform` · c29:`Tex2Transform` · c30:`Tex3Transform` · c31:`ViewIT` · c34:`ProjectedShadowMatrix` |
| `Rim.fx` | c0:`WorldViewProjection/Projection/ParaboloidProjection/diffuse_color` · c1:`ParaboloidD0_ZBias/beta_dash_mie` · c2:`beta_dash_rayleigh` · c4:`WorldViewT` · c7:`FogBetaRayleighMie` · c8:`FogHG` · c9:`LightDirection/SunDirection` · c10:`LightUp/SunDiffuse` · c11:`LightDiffuse/SunSpecular` · c12:`LightAmbientDown` · c13:`LightAmbientUp` · c14:`LightSpecular` · c19:`MaterialDiffuse` · c20:`MaterialEmissive` · c21:`MaterialSpecular` · c22:`FresnelFactor` · c23:`Tex1Transform` · c24:`ViewIT` · c27:`ProjectedShadowMatrix/ProjectedDepthShadowMatrix` · c31:`World` |
| `Water.fx` | c0:`WorldViewProjection/ParaboloidProjection/water_color` · c1:`ParaboloidD0_ZBias/perturbation_factor` · c2:`reflection_color` · c4:`WorldViewT` · c6:`beta_dash_mie` · c7:`FogBetaRayleighMie/beta_dash_rayleigh` · c8:`FogHG` · c9:`LightDirection/SunDirection` · c10:`LightUp/SunDiffuse` · c11:`LightDiffuse/SunSpecular` · c12:`LightAmbientDown` · c13:`LightAmbientUp` · c14:`LightSpecular` · c15:`LightDirection2` · c16:`MaterialDiffuse` · c17:`MaterialEmissive` · c18..c21:`Tex1..Tex4Transform` · **c22:`WaveHeight` · c23:`WaveSpeedMulTime` · c24:`WaveDirX` · c25:`WaveDirY` · c26:`SinConst` · c27:`CosConst`** |
| `Tree.fx` | c0..c4 同上 · c7:`FogBetaRayleighMie` · c8:`FogHG` · c9:`SunDirection` · c10:`SunDiffuse` · c11:`SunSpecular` · c19:`MaterialDiffuse` · c20:`MaterialEmissive` · c21:`Tex1Transform` · **c22:`AnimScalePhase`** · c24:`DiffuseOffset/AlphaFade` · c25:`BetaDashMie` · c26:`BetaDashRayleigh` |
| `TexAnimGlow.fx` | c0:`WorldViewProjection/Projection/ParaboloidProjection/beta_dash_mie` · c1:`ParaboloidD0_ZBias/beta_dash_rayleigh` · c2:`glow_intensity` · c4:`WorldViewT` · c7:`FogBetaRayleighMie` · c8:`FogHG` · c9:`SunDirection` · c10:`SunDiffuse` · c11:`SunSpecular` · c19:`MaterialDiffuse` · c20:`MaterialEmissive` · c21..c22:`Tex1/Tex2Transform` |
| `TexVC.fx` | c0:`WorldViewProjection/Projection/ParaboloidProjection/render_reflection_intensity` · c1:`ParaboloidD0_ZBias` · c4:`WorldViewT` · c8:`Tex1Transform` · c9:`FogBetaRayleighMie` · c10:`FogHG` · c11:`BetaDashMie` · c12:`BetaDashRayleigh` · c13:`SunDirection` |
| `IntoDepthShadowTexture.fx` | c0:`WorldViewProjection/Projection`（写阴影图，仅 2 个常量） |

**★ 关键结论：布局是"每个材质族自己一套"，不是全局统一。**
但 `c0`(世界×视×投影 / 抛物面投影)、`c4`(WorldViewT)、雾块、太阳块、材质块
（`MaterialDiffuse/Emissive/Specular` + `FresnelFactor`）在各族**语义一致、编号不同**。

**★ 水面是正弦波模型**：`WaveHeight`、`WaveSpeedMulTime`、`WaveDirX/Y`、`SinConst/CosConst`
—— 复刻水面照这 6 个参数做即可。
**★ 车身有 `dirt_intensity`** —— 与 §`docs/22` 的泥污层对上 ✓（独立印证）。

## 4. 逐文件采样器

| 文件 | 采样器（`//` 注释即角色） |
|---|---|
| `Chassis.fx` / `BreakableGlass.fx` | 0:`layer1` 1:`layer2`(注释掉) 2:`layer3` 3:`layer4` 4:`lightmap/hemi1` 5:`hemi2` 6:`specular cubemap` 7:`reflection1` 8:`shadow tile` |
| `Complex.fx` | 0:`layer1` 1:`layer2` 2:`layer3` 3:`bumpmap` 4:`lightmap` 5:`projected shadow` 6:`specular cubemap` 7:`reflection1` 8:`tile_shadow` 9:`tile` |
| `Rim.fx` | 0:`layer1` … 4:`lightmap/hemi1` 5:`hemi2` 6:`specular cubemap` 7:`reflection1` 8:`reflection2` |
| `Tree.fx` | 0:`layer1` 1:`lightmap` |
| `Water.fx` | 0:`normalmap` 1:`reflection` |
| `TexAnimGlow.fx` | 0:`layer1` 1:`layer2` |
| `TexVC.fx` | 0（无注释） |
| `IntoDepthShadowTexture.fx` | 0（注释掉） |

## 5. 名字 → 构建块 映射 + 双向核对

`tools/fx_spec.py --map` 用 18 条关键词规则把 **175 个已验证名字**反查到 `.fx` 构建块：

* **规则对应的构建块 0 缺失 ✓**（18/18 在 `.fx` 函数表里真实存在）；
* 175 个名字中 **111 个被归类**，关键词命中统计：
  `layer_tex` 60 / `lighting_specular` 42 / `lighting_lightmap` 34 / `lighting_reflection` 32 /
  `layer_tex2` 25 / `layer_col` 24 / `lighting_bump` 20 / `lighting_masked` 10 /
  `lighting_shadow` 9 / `transform_slot` 6 / `lighting_anim` 6 / `transform_skinned` 4 /
  `layer_vcol` 4 / `transform_palskinned` 2 / `layer_tex3` 2 / `transform_intopara` 2；
* 剩下 **64 个未归类**（不含 `.fx` 本身的 6 个被关键词顺带命中的）经独立复核分为四类，
  **其中 31 个是一整族此前没记录的子系统**：

| 类别 | 数量 | 例 |
|---|---|---|
| 整份 `.fx` 源 | 6 | `Chassis.fx`、`BreakableGlass.fx` … |
| **★ 光照贴图/SH 烘焙 + 精灵 + 后处理族** | **31** | `LMSH` `LMSkydome` `LMPointLightCube` `LMImportance` `LMPosNormal` `LMDepth1/2` `FOLNormal` `Sprite_Normal` `SpriteRotate_Normal[_SAFE]` `Triangle_Normal` `projected_light[0]` `downsample` `effect_apply[_gamma0/1/2]` `clear_below` `Layered_Normal` |
| 族专属（不套通用命名法） | 16 | `Chassis_*` `Rim_*` `water_*` `TexVC_*` `mblur*` `foam_*` `Tree_*` … |
| 开发/工具残留 | 11 | `Benchmark*` `LMDepthTest` `blur*` `*_old` |

**★ `LM*` 族 = 光照贴图/球谐烘焙 + 天空捕捉子系统**（已抽查源码确认）：

* `LMSkydome.psh` 注释里直接列出常量语义：
  `c0 - FogBetaRayleighMie`、`c1 - FogHG`、`c2 - beta_dash_mie`、`c3 - beta_dash_rayleigh`、
  `c4 - sundirection`、`c7 - 1/log(2.0f)`
  ⇒ **天空就是用 Rayleigh/Mie 大气模型渲染的**（这是**独立于 `.fx` 的第二处印证** ✓）；
* `LMPointLightCube.psh`：`c0 light pos / c1 light atten / c2 light color /
  c3..c5 cubemap orientation x/y/z` + `dcl_cube s0` ⇒ 点光源立方图捕捉；
* `LMSH.psh`：直通写顶点色 ⇒ 输出 SH 系数（烘焙用）；
* `LMImportance.psh`：重要性/前缀和通道。

**两条规则没被任何名字用到**，且都有解释：`transform_normal`（默认变换所以不写进名字 ✓）、
`lighting_planar`（平面反射是 `#define REFLECTION_PLANAR` 编译轴，不进名字 ✓）。

## 6. ⚠ 未解：`.fx` 源码与编译产物**寄存器布局互相矛盾**

`Chassis.fx` 声明 `c7:FogBetaRayleighMie c8:FogHG c9:BetaDashMie c10:BetaDashRayleigh
c11:SunDirection c12:SunDiffuse c13:SunSpecular`；
但同一个容器里的编译产物 `Chassis_Normal0_0.vsh` 写着
`SUN_DIRECTION 7, SUN_DIFFUSE 8, SUN_SPECULAR 9, SH_RED/GREEN/BLUE 10/11/12, FOG 17,
MAT_EMISSIVE 18, MAT_SPECULAR 19`。

⇒ **两者不是同一修订版**：`.fx` 里雾块占了 c7–c10、把太阳块推到 c11–c13；
编译产物则是太阳 c7–c9 + 球谐 SH c10–c12、雾在 c17。
佐证：`Chassis.fx` 第 467/468 行还留着**被注释掉的另一套** `beta_dash_* : register(c2/c3)`
—— 同一文件里就有多版本痕迹。

**结论（未解）**：容器里存的是**多次构建的混合产物**。
- 若要 1:1 复刻**出货时的实际行为**，应以**编译产物（`.vsh`/`.psh` 的 `#define`）为准**；
- 若要理解**设计意图与语义**，以 `.fx` 为准；
- 待办：找到**运行时编译路径**（`D3DXCompileShader` 调用点 + 常量表的实际填充处），
  才能确定引擎在启动时到底按哪套布局设置常量。

## 7. 重制落地建议

1. **按 §1 的三段模型搭材质系统**：变换/图层/光照各自是可选函数，用组合而不是 175 个硬编码着色器；
2. **变体轴照 §2 实现**（层混合 8 种 + 反射 4 种 + 高光 3 种 + 阴影 4 种 + 逐像素开关）；
3. **水面照 §3 的 6 个波参数**（正弦波 + 扰动 + 反射贴图）；
4. **车身照 §3 的 `dirt_intensity` + `render_reflection_intensity`**，损伤/泥污层如 `docs/22 §5`；
5. **常量布局按材质族分表**（§3），别用一个全局布局硬套；
6. 雾/天空按 `docs/22 §4b` 的 Rayleigh+Mie+`FogHG` 相位函数做。

## 8. ★ 混合模式的精确公式（`Complex.fx` 源码逐条摘出）

`LAYERMODE_*` 是 **1..8** 的编译期实参（`ps_layer_coltex(LAYERMODE_MULTIPLY,false)`），
三处实现：`ps_layer_coltex`（顶点色 × 贴图）、`ps_layer_tex2`（贴图 × 贴图）、
`ps_layer3`（第三层，叠加到已累积的 `oLayerColor`）。

| 模式 | 值 | 公式（`A`=下层/已累积色，`T`=本层贴图，`k`=`layer_const`） |
|---|---|---|
| `MULTIPLY` | 1 | `o = A * T` |
| `MULTIPLY2X` | 2 | `o = (A * T) * 2`（"premultiplied for modulate2x lighting"，见 §9 菲涅尔 `y*=2`） |
| `ADD` | 3 | `o = A + k·T`（`.b` 用于第二层、`.a` 用于第三层） |
| `SCREEN` | 4 | `o = A + T − T*A` |
| `BLENDTA` | 5 | `o = lerp(A.rgb, T.rgb, T.a)`（用**贴图 alpha** 混合） |
| `BLENDVA` | 6 | `o = lerp(A.rgb, T, layer_color.a)`（用**顶点/材质 alpha** 混合） |
| `BLENDVAT` | 6 | `v = layer_color.a − lerp(A.a, 1−T.a, k.b); f = saturate(v*4+0.5); o = lerp(A.rgb, T.rgb, f)` ← **软阈值透明裁剪**（宽 0.25 的过渡带） |
| `BLENDC` | 7 | `o = lerp(A.rgb, T, k.b)`（第三层用 `k.a`） |

其它关键细节：
* `layer_const` = **float4，分量按层复用**：`.b` = 第二层混合量、`.a` = 第三层混合量
  （同时兼作 `ADD` 的缩放与 `BLENDVAT` 的阈值 —— 一个常量三用 ✓）；
* 图层 alpha：`o.a = T.a * diffuse_color.a` ✓；
* **tiling**：`mtc = tc + layer_tiling.x/y/z * tex2D(Sampler9, tile_tc)` —— 用一张
  tile 贴图**扰动 UV**，每层一个缩放（`.x` 第 1 层、`.y` 第 2、`.z` 第 3）；
* 图层掩码输出：`oMaskValues.x/y/z` = 各层 alpha（供后续通道用）；
* 第三层 UV：`is_first_col ? tc1.xy : tc0.wz`（UV 打包在插值器里）。

## 9. ★ 光照 / 阴影 / 雾的精确公式

**光照合成**（`vs_lighting_diffuse`）：
```
Ambient = compute_ambient(viewNormal)          // 9 系数球谐辐照度
Diffuse = SunDiffuse * max(-dot(viewNormal, SunDirection), 0)
diffuse_color = Ambient + Diffuse + MaterialEmissive
```
`render_slots` 分支改用**逐顶点烘焙值**：`Ambient = iambient`、`Diffuse = iintensities.r * SunDiffuse * …`。

**SH 环境光**（`SH[7]` @ c14–c20，经典 Ramamoorthi–Hanrahan L2）：
```
x1 = dot(SH[0..2], N)
x2 = dot(SH[3..5], N.xyzz * N.yzzx)
x3 = SH[6].rgb * (N.x² − N.y²)
ambient = max(0, x1+x2+x3)
```

**菲涅尔**：
```
angle = min((1 − dot(view, normal)) * 1.25, 1.0)   // 源码自注 "little patch"
v = FresnelFactor.g * angle²
return (FresnelFactor.r + v,  1 − v)               // .x=反射, .y=漫反射；随后 y *= 2
```

**阴影**（`inShadow(projshadow_tc, method, inverse)`）：

| 方法 | 值 | 实现 |
|---|---|---|
| `SHADOW_OFF` | 0 | 不查表 |
| **`SHADOW_A`** | 1 | **出货用**：`saturate( S(tc) − saturate((tc.z − S(tc).a) * 256) )` —— 1 次采样，alpha 存深度，`×256` = 宽 1/256 的**自阴影偏差斜坡** |
| `SHADOW_Z` | 2 | 简单 `tex2Dproj` z 比较（`inverse` 取反）；**源码里明写 `//TODO: cascaded shadow map`** —— 即级联**没做成**，用单张 |
| **`SHADOW_F`** | 3 | **4 抖动采样 PCF**：抖动半径 `(0.00060096, 0.0009765625)` = **`1/1664, 1/1024` ⇒ 阴影图 1664(宽)×1024(高)**（`1/1664` 对应 x 轴 ⇒ x 向 1664 像素；注释里被砍掉的 PCF 块也写 `float2(1024.0,1664.0)`，双重印证 ✓），方向 `(0.2588,0.9659)/(0.7071,−0.7071)/(−0.9659,−0.2588)`，权重 `dot(0.4,0.2,0.2,0.2)`（和为 1.0 ✓，即无损归一化） |

> ★ 该尺寸已由**第二条独立判据**确认：二进制 `0x4c1bd5`–`0x4c1c2f` 的 `push 0x680`/`push 0x400`
> 即 1664×1024 的创建参数（全 `.text` 仅 3 处），句柄落在全局 `0x77a770`/`0x77a774`。
> 详见 **`docs/30_SHADOW_AND_REFLECTION.md`**（含"出货用 `SHADOW_A` 是单采样、软边来自独立滤波通道"的细化）。

共同细节：`Sampler8`(shadow tile) 给出 4 个参数，`tc_d = tc * tr.xyzw + tr.wzyx` = **一次 MAD 完成
tile→atlas 重映射** ✓；`tc.z = saturate(tc.z + tc.w)` 的 `.w` = **相机距离偏差** ✓；
`inverse` 用于把"阴影"翻成"受光"（写深度图那条路径用）。

**雾 = 单次散射大气**：
```
ApplyFog(base, ext, mieray) = lerp(mieray, base, ext)
```
其中 `mieray` = Rayleigh+Mie 内散射色、`ext` = 消光（透射率）；配合 `FogBetaRayleighMie`(c7)、
`FogHG`(c8, `[1−g², 1+g, −2g]` Henyey–Greenstein)、`BetaDashMie`(c9)、`BetaDashRayleigh`(c10) 使用。

## 10. ⚠ 更正：`shader.dat` 由**运行时**编译产生（原判"构建期产物"是错的）

**原推理（错）**：`compile_fragment` / `pixelfragment` / `vertexfragment` / `ID3DXEffectCompiler`
在 `LASR.exe` 里 0 命中 ⇒ 编译器不在游戏里 ⇒ 构建期产物。

**错在哪**：这些是 **D3DX FX 语法的关键字**，由 `d3dx9_30.dll` 内部处理，
**本来就不该出现在 exe 的字符串里**。把"exe 里没有"当成"游戏里没有" ✗。

**更正的证据（byte 级）**：`d3dx9_30.dll` 的导入表含完整编译与反射 API，且有精确调用点 ——
`D3DXAssembleShader` ← `0x530414`/`0x530510`、`D3DXAssembleShaderFromFileA` ← `0x530552`、
**`D3DXGatherFragments` ← `0x530606`、`D3DXGatherFragmentsFromFileA` ← `0x530635`**、
`D3DXCreateFragmentLinker`、`D3DXGetShaderConstantTable`、`D3DXSHRotate`、`D3DXSHEvalHemisphereLight`
—— 全在**着色器子系统 `0x5303b0` 附近**（正是 107 个注册点调用的那个助手 ✓）。

**⇒ 引擎在载入时用 D3DX 编译这些着色器，并把结果缓存进 `shader.dat`。**
⇒ **`.fx` 源码就是引擎实际编译的东西，其寄存器声明是权威的**；
缓存里的编译产物可能是**上一版构建的遗留**（这正好解释 §6 的寄存器编号矛盾 ✓✓）。
⇒ 详细记录见 **`docs/24_RENDER_ANCHORS.md`**。

## 11. 未解 / 待办

* §10 的寄存器编号差异（工具是否重排 → 需反编译那个外部工具，或用 D3DX 复现编译试比对）；
* `specrefmask_weights` / `spec_mat_x_light` / `paratr` / `layer_tiling.z` 的确切用途（寄存器表里已注明
  `.rgb`/`.a` 等分量约定，公式尚未逐条摘）；
* `Rim.fx` / `Water.fx` / `Tree.fx` 的专有光照（半球光 `LightAmbientUp/Down` 的权重、`AnimScalePhase` 风摆相位）
  尚未与 `Complex.fx` 的通用路径对照；
* 渲染**通道顺序**与 D3D9 状态块（`shader.dat` 不含状态）。
