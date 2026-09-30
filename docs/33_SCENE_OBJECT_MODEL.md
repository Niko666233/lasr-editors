# 33 · 场景对象模型与明文配置格式（`system.rpk` 实证）

> 本轮本来是查音频，顺路撞开了引擎的**类型注册表**和**明文序列化格式**。
> 全部证据出自 `C:\Games\LASR\system.rpk`（仅 **1532 字节**，明文，无加密 / 无压缩）。

## 1. 先纠正一个格式误判：`.rpk` 不是资源包，是索引

游戏里 52 个 `.rpk`，全部以 `RPAK` + `u32 index_size`（统一 `0x200 = 512`）开头，
**并且内部字符串都写着 `system.rpk`** ⇒ 它们是 **RPAK 虚拟文件系统的清单**，
真正的素材是**磁盘上的散装文件**（`sounds/*.fsb`、`frontend/sounds/*.wav`、`music/*.ogg`）。

| 文件 | 大小 | 内容 |
|---|---|---|
| `system.rpk` | 1532 B | ★ **类型注册表 + 默认场景明文配置** |
| `sound.rpk` | 13499 B | 清单（含 `res_sound` 等条目） |
| `vehicles/<车>/sounds.rpk` | ~585 B | 清单 |
| `frontend.rpk` / `particles.rpk` / `maps.rpk` | 大 | 真资源包（`ISCX` 网格 / `IDDS` 贴图） |

## 2. 引擎的类型注册表（`system.rpk` 索引区 + 条目区）

**类型名表**（索引区 512 字节里的可打印串，按出现顺序）：
```
typ_game_object      bot        camera      Controller     game        map        trigger
typ_physics_body     typ_render_object        ins_game     ins_physics  ins_render
res_mesh             res_texture              res_sound    res_force_fx
typ_render_light     typ_render_camera        typ_physics_constraint  typ_physics_particle
res_animation        res_viewport
ins_render_sprite    ins_render_text          ins_render_horizon      ins_render_sound
```

★ **命名规范（可直接用于重制）**：
- `typ_*` = **类型**（`typ_render_light`、`typ_physics_body`、`typ_render_camera`、`typ_physics_constraint`、`typ_physics_particle`）
- `ins_*` = **实例**（`ins_render_sprite` / `_text` / `_horizon` / `_sound`、`ins_game`、`ins_physics`、`ins_render`）
- `res_*` = **资源**（`res_mesh` / `res_texture` / **`res_sound`** / `res_animation` / `res_viewport` / `res_force_fx`）

**条目区结构**（每条 = 长度前缀名 + 若干 u32 索引）：
```
0c "res_texture"   …  09 00 00 00  06 00 00 00 00 00
0a "res_sound"     …  0a 00 00 00  04 00 00 00 00 00
0d "res_force_fx"  …  0b 00 00 00  0d 00 00 00 00 00
11 "typ_render_light"     …  0c 00 00 00  0c 00 00 00 00 00
12 "typ_render_camera"    …  0d 00 00 00  0a 00 00 00 00 00
17 "typ_physics_constraint" … 0e 00 00 00  0b 00 00 00 00 00
15 "typ_physics_particle"   … 0f 00 00 00  13 00 00 00 00 00
0e "res_animation"  …  10 00 00 00  12 00 00 00 00 00
0d "res_viewport"   …  11 00 00 00  0f 00 00 00 00 00
12 "ins_render_sprite"    …  12 00 00 00  10 00 00 00 00 00
10 "ins_render_text"      …  13 00 00 00  11 00 00 00 00 00
13 "ins_render_horizon"   …  14 00 00 00  14 00 00 00 00 00
11 "ins_render_sound"     …
```
⇒ 每条带**两个递增索引**（疑似"类型 ID / 基类 ID"）⇒ `ResourceRef(name, index)` 的 index
就是**这张表里的序号**（Java 侧 `SfxRef.SFX_ROOT = ResourceRef("system.rpk", 9)` 即第 9 号 = `res_sound` 一族）。

**`ICFG` 对象类名记录**（另一段，每条 = `ICFG` + u32 长度 + 名）：
```
ICFG 04 "bot"    ICFG 07 "camera"    ICFG 07 "player"    ICFG 07 "ground"    ICFG 08 "trigger"
```
⇒ ★ **场景里的对象类别**：`bot` / `camera` / `player` / `ground` / `trigger`。

## 3. ★ 明文配置格式：光照与阴影（数据驱动）

### 3.1 阴影投影（5 个参数）

```
shd_center 0.000 0.000 0.000
shd_diru   0.000 0.000 0.000
shd_dirv   0.000 0.000 0.000
shd_vbase  0.000 0.000 0.000
shd_vup    0.000 0.000 0.000
```

⇒ **阴影投影完全由数据定义**：中心点 + 两个方向向量 + 基点 + 上向量。
与 `docs/30` 的着色器侧证据吻合（`ProjectedShadowTexture1.vsh` 里的 `SUN_DIR` 与
`TEX0/1_TRANSFORM` 就是把这里的值传进投影矩阵）。

### 3.2 光源定义（完整块）

```
type directional
diffuse     0.000 0.000 0.000 0.000
specular    0.000 1.000 0.000 0.000
ambient     1.000 0.039 0.277 0.444
position    0.000 0.000 0.000
direction   0.707 -0.707 0.000        ← 45° 太阳方向
range       1000.000
attenuation 0.000 0.000 0.000         ← D3D 的 3 个衰减系数
lf_glow_color     0.000 0.000 0.000 0.000
lf_flare_distance 1.000               ← ★ 镜头光晕（lf_*）参数
```

★ 字段清单可直接作为重制的 **light 组件**参考实现，
且与 `docs/23` §8–§11 的着色器常量块（太阳/雾/材质）互相印证。

## 4. 对重制的直接价值

| 项 | 用法 |
|---|---|
| `typ_*` / `ins_*` / `res_*` 三类命名 | 引擎对象模型的分层（类型/实例/资源），可直接映射到 ECS 或组件系统 |
| `ICFG` 类名（bot/camera/player/ground/trigger） | 场景对象的**最小集合** |
| `shd_*` 五参数 | 阴影投影的**数据驱动接口**（不必硬编码） |
| 光源块字段 | light 组件字段清单（含 `lf_glow_color`/`lf_flare_distance`） |
| `ResourceRef(name, index)` | 资源寻址 = (清单文件, 表内序号) |

## 5. 遗留（✗）

- `.rpk` 的**条目区完整语义**（那两个递增 u32 的确切含义：类型 ID？基类？实例上限？）
- `system.rpk` 里**其余板块**（`shd_*`/light 之后是否还有更多配置块；本轮只 dump 了 29 个可打印段）
- `maps/*.rpk` 里的 `ISCX` 网格与这些 `typ_*` 的绑定关系
- `sounds.rpk` 清单（13 KB）里的具体条目与 `res_sound` 的对应
- 音频侧遗留仍见 `docs/32` §5
