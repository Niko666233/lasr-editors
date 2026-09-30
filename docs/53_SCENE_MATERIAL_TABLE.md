# 53 · 场景块的材质表（网格 ↔ 贴图绑定）

> 覆盖：**材质表格式**（`mesh` / `flags` / `shd_*` / `texture`）、**资源记录流**（带名字的资源表）、
> **id 页模型**、以及把三者接起来的**网格 → 贴图**绑定结果。
> 工具 `tools/material_table.py` → `out_material_tables.json`；接入 `remaster/data/materials.json`。
> 标注：✓ = 机械核对（覆盖率 / 逐字节 / 名字互印证）；推断 = 有证据但未唯一确定。

## 0. 一句话结论

`docs/52` 留下的「网格↔贴图绑定」缺口补上了 ✓。每个美术存档里都有一块 **ASCII 材质表**，
逐 `mesh` 列出它用的贴图；`mesh` 的 id 与**资源记录流**里带名字的记录同一个 id 空间，
所以链路是：

```
存档里的记录流（带名字表）
   index=439  name='track_trees'  type=2      ← 网格/子件（车件、地图场景网格…）
   index=163  name='track_comb.png' type=99   ← 贴图资源
材质表（ASCII）
   mesh 0x01B7 → texture 0x000000A3            ← 439 用 163
解出：mesh id 439 = 'track_trees' → 贴图 'track_comb.png'
```

**实测规模**：39 个存档有材质表 / 1,034 条材质（1,019 条能对回网格记录名）/
4,230 条 `texture` 引用，其中 **1,614 条是 `0x00000000`（空槽）**；
剩下 **2,616 条真引用里 2,615 条解出文件名（99.96%）**。

## 1. 两个二进制/文本结构

### 1.1 资源记录流（带名字的资源表）✓

```
u16 flags        // 0x0405/0x0406/0x0407 …（**不总是** 0x04xx，如 0x000e，不能当判据）
f32 1.0          // ← 唯一稳定的记录标记（DDS/网格数据里不会恰好出现 + 后面跟合法长度）
u32 file_off     // 该资源在 .rpk 里的绝对偏移
u32 size         // 载荷长度（条目型 = payload + 8）
u8  len          // 含结尾 NUL
char name[len]
u32 kind         // (group << 16) | type
u32 index        // **该资源在本存档里的 id** —— 材质表引用的就是它
```

固定 15 字节头 + 8 字节尾 ⇒ 每条 `23 + len(name)` 字节、记录之间**无间隙**。
一个存档可能有多条记录流（`frontend.rpk` 就是多条，共 428 条）。

`type` 实测取值（名字与类型互印证的）：

| type | 含义 | 例（`frontend.rpk` / 车 / 图） |
|---|---|---|
| 1 | 全球地图贴图池条目 | `maps/texture.rpk`：`asphalt.dds`…（64 条） |
| 2 | 地图场景网格（赛道面/镜面/远景…） | `track_trees` / `mirror` / `far` |
| 7 / 8 | 分组 / 实例对象 | `ccw_mirror` / `skydome` |
| 11 | 车辆杂项件 | `_MISC_` |
| 30 | 地图物件 | `korfuggo`（匈牙利语"圆环"） |
| 33 | 音效（SfxRef 用的就是这批 id） | `letsdoit`(414) / `msgBox`(357) |
| 76 | 车轮 | `rims` / `U_rim_ST` |
| 95 | 车灯 | `light_glows` / `L_headlight_glow` |
| 99 | 地图贴图 | `track_comb.png` / `skydome.png` / `cubemap.dds` |
| 200 | 前端贴图 | `g3cucc.png` / `szurke.dds` |
| 280 | 车身件 | `chassis` / `F_bumper` / `hood_2` / `FL_door` |

**交叉印证**（两个独立方向对上同一批数字）：`letsdoit` 的 index=414、`msgBox`=357，
而伪码里 `ResultsWindow` 的 `SfxRef("frontend.rpk", 414/413)` 正好是"输/赢"音效
（`out_pseudo/java/classes/game/frontend/ResultsWindow.java:43-44`）。

### 1.2 材质表（纯文本）✓

```
mesh 0x000001B7          ← 网格 id（= 记录流的 index）
flags 2048               ← 渲染标志（bit 位待查，见 §4）
shd_center 0.000 0.000 0.000    ← 阴影投影基：中心
shd_diru / shd_dirv             ← 两个切向轴
shd_vbase / shd_vup             ← 视点/上方向
texture 0x000000A3       ← 贴图引用：0x<page><id>
```

- 地图存档的换行是 `\r\n`、条目之间还可能夹 `NUL`；**车包是 `\r\r\n`** ⇒ 解析按 token 扫，不能按行切。
- 一条材质可以有 1–31 条 `texture`（最多的是赛道主面：31 层）。

## 2. `texture 0x<page><id>` 的 page 模型 ✓

`page` 高 16 位选**资源池**，`id` 低 16 位是池里的资源号。逐存档做覆盖率探测的结论：

| page | 池 | 依据（每个引用方存档独立探测） |
|---|---|---|
| **0** | **本存档自己的资源表** | 39 个引用方里本档自解覆盖率 0.83–1.00，且明显高于其它候选 |
| **2** | 本存档（车件第二层：mask/glow…） | `Hornet` 的 page-2 四个 id 在本档表 4/4 命中，名字是 `R_wing_6_mask.dds` / `L_taillight_glow` 这类 |
| **3 / 4 / 5** | **`maps/texture.rpk`**（全球地图贴图池，64 张） | 所有地图存档的 page 4/5 id 覆盖率 **1.00**，解析出的名字 94–97% 是贴图文件，内容对得上（`asphalt.dds`/`sidewalk.dds`/`advertises.dds`…） |

回退链（每一步都记在输出的 `pool` 字段里，便于审计）：

```
page 0     : 本存档
page 2     : 本存档 → vehicles.rpk            （推断：只有 2 台车的 3 个 id 用到）
page 3/4/5 : maps/texture.rpk → 本存档 → 完整图
             其中「完整图」= maps/xxx_b.rpk 引用 maps/xxx.rpk 的图集（实测 4/4 命中）
```

## 3. 解出来的东西长什么样 ✓

**地图**（`maps/boulevard.rpk`，19 条材质）：

| mesh id | 记录名（type） | 解出的贴图 |
|---|---|---|
| 2 | （无记录，主赛道面） | `glow_yellow.dds` `track_buildings_comb.png` `sandgrass.dds` `race_racetruck.dds` `sidewalk.dds` `asphalt.dds` `advertises.dds` …（21 层） |
| 25 | `track_buildings` (2) | `garden_bush.dds` `track_soho_comb.png` `garden_palma.dds` `asphalt_detail.dds` `train_track.dds` |
| 439 | `track_trees` (2) | `container.dds` `track_comb.png` |
| 668 | `track_black` (2) | `skydome2b.dds` `track_other_comb.png` |
| 818 | `far` (8) | `cubemap.dds` |

**车**（`vehicles/Hornet_Wega_2006.rpk`，61 条材质，与导出的 `.iscx` 同名）：

| mesh id | 记录名（type） | 解出的贴图 |
|---|---|---|
| 107 | `light_glows` (95) | `U_rim_TR.dds` |
| 109 | `chassis` (280) | `light_brk_L_taillights` `stock_interior` `dirt_snow` `placeholder` |
| 158 | `F_bumper` (280) | `steering_wheel` `L_taillight_glow` `light_rev_R_taillights` `stock_interior` `dirt_snow` `placeholder` |
| 220 | `U_rim_ST` (76) | `glow` |
| 119 | `muffler` (280) | `stock_interior` `dirt_snow` `placeholder` |

车身件共享同一组层（`stock_interior`/`dirt_snow`/`placeholder` + 各灯贴图）是**合理的**：
LASR 的车漆是运行时叠上去的 —— 伪码里
`Vehicle.java:518`：`new java.gfx.Texture(new ResourceUtil.ResourceRef("frontend.rpk", 1280 + (paintjobAspect-1)*3 + i))`
即涂装贴图在 `frontend.rpk` 的 1280+ 号段，不在车包里。

## 3b. 渲染验证（能不能直接用）✓

`tools/preview_textured.py` 把 `.obj` + `--mtl` 产物做仿射贴片渲染（纯 PIL，逐三角面贴图）：

```bash
$PY tools/preview_textured.py assets/meshes/vehicles/Hornet_Wega_2006/chassis.obj --view front --size 700
$PY tools/preview_textured.py assets/meshes/maps/boulevard/mirror_black.obj --view top --size 600 --max-faces 6000
```

看到的结果（逐项核对，不夸大）：

- `chassis.obj`：车前脸成形，挡风玻璃/圆形大灯位置正确，图集（`stock_interior.png`，车里视图集）
  贴上去后**没有拉伸条纹、没有整片乱色** ⇒ UV 与图集对得上 ✓。但该图集本身偏黑，
  所以画面是"深色车壳 + 局部细节"，不适合当美术水准的验证。
- `mirror_black.obj`（boulevard，抽 6,253 面）：俯视是**清晰的街区/路口格网**，
  贴的是 `track_other_comb.png`（2048²）✓；同样没有 UV 错乱。
- 价格：6,253 面 ≈ 50 秒（纯 Python/PIL），**6.8 万面的整图网格不建议全量渲染**。

## 4. ✗ 未解 / 待办

| 项 | 现状 | 下一步 |
|---|---|---|
| `flags`（最常见 24、256、2、3、2048、4100…）位含义 | 只解出是渲染标志，位义未定 | 与 `docs/17–30` 的渲染管线（pass 顺序、混合模式）对照，或实机改值观察 |
| `shd_*` 五组阴影投影基 | 1,034 条材质里 **232 条有非零值**（其余为 0，即"自动/不投影"） | 与 `docs/19`（阴影）对照；有非零值的那些正好是投影体（车、建筑） |
| `texture` 的**顺序**语义（第 1 层/第 2 层…） | 顺序保留在 `out_material_tables.json`，未标层义 | 对照 `docs/22`（pass 顺序）猜层义，或实机屏蔽某一层看差别 |
| frontend 的 1 条未解 `(0, 242)` | 全库唯一未解引用 | 单独查 frontend 记录流里 id 242 是否存在（可能在别的子表） |
| 材质表是否也用于**粒子/驾驶员** | `particles.rpk`/`drivers/*.rpk` 也有表（type 自成一系） | 本轮已解析出来，语义（粒子参数）未展开 |

## 5. 怎么重跑

```bash
PY=./.capenv/Scripts/python.exe

$PY tools/material_table.py            # 全量 → out_material_tables.json（含 page_map / stats）
$PY tools/material_table.py --stats     # 覆盖率 + 未解清单
$PY tools/material_table.py --dump maps/boulevard.rpk      # 人类可读
$PY tools/material_table.py --dump vehicles/Hornet_Wega_2006.rpk
```

耗时：全量约 90 秒（要读全部 52 个 .rpk 并全文扫记录标记）。
