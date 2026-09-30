# 57. 车身网格装配链（外观怎么绑上去）

> 承 `docs/55`（零件装到哪个槽）+ `docs/56`（槽在哪儿）之后的最后一环：**零件长什么样、用哪张网格、贴哪张图、怎么变形**。
> 工具：`tools/mesh_assembly.py` → `out_mesh_assembly.json` → `remaster/data/mesh_assembly.json`（22 个数据集之一）。
> 全部证据来自 `out_pseudo/vehicles/**`（伪码层直接可读，**不需要原生**）。

## 0. 结论

零件的**外观**由 5 处资源绑定 + 一组 `configureType` 配置行决定，全都写在**零件类**（`<车>_<件名>_<变体>`）里：

```java
// ① 类静态字段：涂装遮罩 / 阴影贴图 + 贴花对象
….maskTexture   = new java.util.resource.ResourceRef.<init>("vehicles/Takura_Tornado_2002.rpk", 193);
….shadowTexture = new java.util.resource.ResourceRef.<init>("vehicles/Takura_Tornado_2002.rpk", 215);
….mypd          = new java.game.parts.PartDecal.<init>(0, 0, 59647);
// ② createType()：网格 → 视觉类型 → 贴图
….configureMesh(new java.util.resource.ResourceRef.<init>("vehicles/Takura_Tornado_2002.rpk", 142));   // ★ 网格
….configureVisual(new java.util.resource.RenderType.<init>("vehicles/Takura_Tornado_2002.rpk", 143), 0,0,0,0,0,0);
….configureTexture(new java.util.resource.ResourceRef.<init>("vehicles/Takura_Tornado_2002.rpk", 18));  // 主体贴图
// ③ 配置行（45 种键）：几何 / 物理 / 外观 / 相机 / 座舱 / HUD
….configureType("slot\t\t0.0 0.0828369 -0.0221924\t0.0 0.0 0.0\t1000\t; F_bumper");
….configureType("body\t\t0.0 -0.0626514 -0.182948\t3.14159 0.174533 3.14159\t1.2\tbox\t0.378828 0.142034 0.0550222");
….configureType("lods\t\t6 0.001 0.025 0.1 1.1 2.5 3.5 0x01 0x02 0x04 0x08 0x100 0x200");
….configureType("flags\t\t0x400"); ….configureType("use_mesh\t0 0"); ….configureType("lod\t\t1 4");
….configureType("dirt_texture\t0x00000104\t3\t0x000000C9 0x000000CA 0x000000CB");
….configureType("wing\t\t4\t0.0 0.0266137 -0.203017\t0.0 0.326431 -0.694356\t0.468132 -0.468132");
….configureType("damage\t\t1.7"); ….configureType("bone"); ….configureType("noclick"); ….configureType("nocollision");
```

数一览（`remaster/tools/validate.py` 已断言）：

| 量 | 值 |
|---|---|
| 零件类（含 `configureType`/`configureMesh`） | **671** |
| 其中带 `configureMesh`（有独立网格） | **447** |
| `Model_*` 车辆模型类 | 20 |
| `configureType` 键种数 | **45**（+ 拼接式配置的尾段归并后） |
| `configureMesh` 的 id → 材质表名解析 | 467/467（**0 未解**） |
| 该名 → 导出 OBJ | 454（13 个无 OBJ：阴影/发光辅助网格） |
| **网格名含零件族关键词**（语义校验） | 271 ✓ / 176 ✗ / 0 跳过 |

## 1. 资源引用机制（`ResourceRef` / `RenderType`）

- **id 空间 = 车包内的资源 id**（`vehicles/<Car>.rpk` 里那个 id），同一个数字在不同车包指向不同网格。
- 两个类：`ResourceRef(rpk, id)`（数据引用）与 `RenderType(rpk, id)`（渲染类型）。
- **配置行也可以拼资源引用**（座舱仪表针就是这么写的）：

```java
configureType((("cockpit_rpm\t0x22 " + ((S)new java.util.resource.RenderType.<init>(
        "vehicles/Takura_Tornado_2002.rpk", 55).id())) + "\t-0.436896 0.428532 -0.563101\t…"));
```

- `Model_*` 里只有 `cockpit_rpm` / `cockpit_speed` 两处用这种写法（40 处 = 20 个 Model 类 × 2，含 WB 变体）。

## 2. `configureType` 键词表（45 种，按语义分组）

| 组 | 键 | 次数 | 形态 / 语义 |
|---|---|---|---|
| 装配 | `slot` | 1906 | `pos(3) rot(3) id`（docs/56）|
| 装配 | `slottype` | 220 | 槽类型号 |
| 装配 | `slotdmgmode` / `slotdeform` | 80 / 30 | 槽的损伤模式位 / 形变开关 |
| 外观 | `use_mesh` | 619 | `<N> <b>`：把**接下来的视觉类型挂到第 N 个网格**（N = 该类里 `configureMesh` 的调用序号，Model 类实测 0…6 递增；零件只有 1 个网格故恒 `0 0`）。**不是**"选变体/选名字"的键 |
| 外观 | `lods` | 634 | `6 <6 个距离> <6 个级标志>`，**全库只有一种取值** |
| 外观 | `lod` | 911 | `1 4` 或 `0 5`：LOD 生效区间 |
| 外观 | `flags` | 757 | 位标志（0x400 / 0x004 / 0x404 / 0x401）|
| 外观 | `dirt_texture` | 457 | 泥污贴图组 + 变体数 + 变体 id |
| 外观 | `damage` | 660 | 损伤倍率（1.7 可损 / 0.0 不可损）|
| 外观 | `flexible` | 570 | 柔性：刚度 + 阻尼（可动件形变）|
| 外观 | `bone` | 680 | 骨骼绑定标记（无参）|
| 外观 | `noclick` / `nocollision` | 1810 / 637 | 关点选 / 关碰撞（无参）|
| 外观 | `flap` | 86 | 可动盖板/翼：位置 + 轴向 + 开合量 |
| 物理 | `body` | 1810 | 碰撞体：`pos rot 质量因子 形状 尺寸`（`sphere` 半径 / `box` 三边）|
| 物理 | `wing` | 646 | 气动/受力点：类型号 + pos + 方向 + 2 系数 |
| 物理 | `wheel` / `wheelbones` | 80 / 80 | 轮位硬点 / 轮骨骼开关 |
| 物理 | `spring` | 80 | 弹簧：刚度 + 行程 + 预压 |
| 物理 | `type` | 80 | 质量/形状类型（`10.000 sphere 0.650`）|
| 物理 | `controller` / `linked` | 60 / 2 | 控制器索引组 / 联动标记 |
| 物理 | `steering` `pedals` `seat` `shifter` | 20 各 | 座舱件位姿 |
| 物理 | `steerhelp` `maxsteer` `steerspeed` | 20/20/14 | 转向助力 / 最大角 / 速度 |
| 相机 | `camera` / `ext_camera` | 122 / 20 | 相机位 + FOV/标志 / 外部相机 + 距离 |
| 座舱 | `cockpit_rpm` / `cockpit_speed` | 20 / 20 | 仪表针网格（`RenderType` 拼接式）|
| HUD | `osd_gauge` `osd_rpmpin` `osd_spdpin` `osd_speed` `osd_gear` `osd_gearplate` `osd_gearlever` | 各 2 | HUD 仪表网格 + 位置 + 格式串（`%03.0f` / `NabcdefR`）|

> 键的计数含**同一零件类里多行**（如 `body` 一个前杠就有 6 个碰撞体、`wing` 有 3 个受力点）。

## 3. LOD

```
lods\t\t6 0.001 0.025 0.1 1.1 2.5 3.5 0x01 0x02 0x04 0x08 0x100 0x200   ← 634 处，取值完全一致
lod\t\t1 4    ← 621 处（= LOD 1..4）      lod\t\t0 5  ← 290 处（= 全 6 级）
```
- 6 级 LOD，距离阈值 `0.001 / 0.025 / 0.1 / 1.1 / 2.5 / 3.5`（引擎的内部单位），级标志按位 `0x01…0x200`。
- `lods` 是**全库常量**（只有一条取值）⇒ 重制侧可以直接硬编码这张表；`lod` 给生效区间。
- `flags 0x400` 与 `use_mesh 0 0` 的出现次数相同（467）⇒ `0x400` 很可能是「用默认网格/由车体网格提供」位（✗ 未证）。

## 4. 碰撞体与气动点

- `body`：一个零件可有多条（前杠 6 条：1 个 `sphere` 兜底 + 5 个 `box`），字段 = `pos(3) rot(3) 质量因子 形状 尺寸/半径`；
  注释里带形变体名（`; // F_bumper_01 //`），与网格变体一一对应。
- `wing`：`类型号 pos(3) 方向(3) 系数(2)`，前杠 3 条（`F_bumper_F/L/R`）；`类型号 4` = 受力点，`5` = 另一类（86 处 `flap` 与之配套）。
- `flexible\t\t0.0004333 0.9`：刚度 + 阻尼，用在可动件（车门/盖板）形变。

## 5. 装配链全景（重制侧照着搭即可）

```
零件类 <车>_<件名>_<变体>
 ├─ configureMesh(ResourceRef(车包, mesh_id))      → 网格（变体靠 id 区分，如 style_II → id 142 = F_bumper_2）
 ├─ configureVisual(RenderType(车包, visual_id), 6×float) → 渲染/视觉类型
 ├─ configureTexture(ResourceRef(车包, tex_id))    → 主体贴图（多数 = item_icons(18)）
 ├─ maskTexture / shadowTexture（类静态）          → 涂装遮罩 / 阴影
 ├─ mypd = PartDecal(0, 0, 59647) + applyDecal(...) → 贴花（贴纸/涂装走这条）
 └─ configureType("slot …")                        → 装到哪个槽、摆在哪（docs/56）
    configureType("body/wing/flexible/damage …")   → 物理与损伤
    configureType("lods/lod/flags/dirt_texture …") → LOD 与外观开关
```

**网格变体与名字的对应（同族 style 变体）**：

| 零件族 | style_I | style_II | style_III | style_IV |
|---|---|---|---|---|
| Fantasy `F_Bumper_*` | id 71 = `F_bumper` | 219 = `F_bumper_2` | 221 = `F_bumper_3` | 223 = `F_bumper_4` |
| Fantasy `Hood_*` | 73 = `hood` | 75 = `hood_2` | 225 = `hood_3` | 227 = `hood_4` |
| Tornado `L_sideskirt_*` | 148 = `L_sideskirt_0` | … | 152 = `L_sideskirt_2` | … |

⇒ **命名是 1-based（style_I 用基名）或 0-based（sideskirt）不一致**，但**id 与变体顺序严格对齐** ✓ —— 所以重制侧要按 **id** 取网格，不要按名字拼。

## 6. 重制侧规则

1. 零件外观 = `configureMesh` 网格 + 3 张贴图（主体/遮罩/阴影）+ 视觉类型 + 贴花；**几何摆放另看 `slot`**（docs/56）。
2. **按 id 取网格**：`(车包, id)`；名字只作提示（见 §8）。
3. 无 `configureMesh` 的 224 个零件（原厂盖板/内饰/纯参数件）没有独立网格 ⇒ 属于车体网格或完全不可见。
4. LOD 表可硬编码（`lods` 全库恒定），`lod` 给区间、`flags` 给开关位。
5. 碰撞体（`body`）与气动点（`wing`）是**零件自带**的 ⇒ 换件会改碰撞盒与受力点（不只是改外观）。

## 7. 产物与断言

| 文件 | 说明 |
|---|---|
| `tools/mesh_assembly.py` | 提取器（`--json` / `--report`）；stdlib only |
| `out_mesh_assembly.json` | 全量：45 键词表 + 671 零件类（网格/视觉/贴图/贴花/配置）+ 20 Model 类 |
| `remaster/data/mesh_assembly.json` | 重制数据层（紧凑版：键词表 + 447 个带网格零件的绑定表 + 统计）|
| `tools/mesh_id_map.py` | **资源 id 映射器**（目录记录流 + 材质表 + OBJ 包围盒）→ `out_mesh_id_map.json`；含 WB 区重绑 |
| `remaster/data/mesh_id_map.json` | 第 23 个数据集：10 车包 / 602 网格条目（id→名→type→bbox→几何标签）+ 偏移扫描 + 归因 + WB 重绑表 |
| `remaster/tools/validate.py` | 新增断言（键表规模 / 447 带网格 / id 解析率 / 族匹配率 / LOD 常量唯一；§8 再加 6 条：车包与网格计数 / 偏移扫描最优 / 归因五类 / WB 全有解 / 链条单调 / 几何标签覆盖）⇒ **80 项全通过** |

## 8. 资源 id 映射与 WB 区错位（★ 重解结果，`tools/mesh_id_map.py`）

**问题**：零件 `configureMesh(ResourceRef("<车包>.rpk", id))` 的 id 查到材质表名字后，269 条对得上零件族、176 条对不上（例：`Hatch_S2_FL_Door_stock` 引用 id 158，而材质表 `mesh 0x9E`=158 的名字是 `F_bumper_5`）。到底是**配对错**还是**引用本身跨族**？

### 8.1 三重独立证据

| # | 证据 | 做法 | 结果 |
|---|---|---|---|
| ① | **逐字节** | 直接从 rpk 原始字节走目录记录流（15B 头 + 名字 + 8B 尾），逐条核对 `index / type / file_off / size / name` | 236 条记录 **index 全唯一**、name 与 off/size 自洽；`158 → F_bumper_5(73224 B)`、`160 → FL_door(51606 B)` 可逐字节复现 |
| ② | **几何** | 读导出 OBJ 的包围盒（cm），与名字语义对表 | `FL_door` = 35.5×102.6×124.4 cm（**门**）、`F_bumper_5` = 33.3×56.5×168.0（**杠**）、`chassis` = 119×171×365（**车壳**）、`hood` = 43.5×126×143（**盖**）⇒ **名字与几何一致**，名字可信 |
| ③ | **偏移扫描** | 把 ref id 在目录顺序上 ±4 平移，算族关键词命中率 | `all`：**k=+0 60.6%**（最高）、`style` 件 **k=+0 73.7%**（最高）⇒ **不存在全局固定偏移** |

⇒ **结论：id 空间与"id→名字"映射都是对的**（变体 1–4）。相符率不是 100% 的原因分两类。

### 8.2 类别一：变体 5/6（WB 宽体）**整体平移一件** ★

63 个 `_style_WB` / `_stage_WB` 零件里 **60 个**的网格与视觉类型同族成对（`configureMesh(id)` / `configureVisual(id+1)` 或同名前缀），说明资源本身自洽；但**名字属于相邻的另一个零件**。按 id 升序排开，Fantasy 呈现完美链条：

| 零件 | ref id | 材质表查到的名字 | 应为 | 真身 id |
|---|---|---|---|---|
| `L_sideskirt_style_WB` | 69 | `steering_wheel` | `L_sideskirt_5` | 85 |
| `R_sideskirt_style_WB` | 85 | `L_sideskirt_5` | `R_sideskirt_5` | 87 |
| `F_Bumper_style_WB` | 87 | `R_sideskirt_5` | `F_bumper_6` | 91 |
| `Hood_style_WB` | 91 | `F_bumper_6` | `hood_6` | 104 |
| `Muffler_stage_WB` | 104 | `hood_6` | `muffler_6` | 115 |
| `R_Bumper_style_WB` | 115 | `muffler_6` | `R_bumper_6` | 123 |
| `R_wing_style_WB` | 123 | `R_bumper_6` | `R_wing_6` | 136 |
| `FL_Door_style_WB` | 162 | `chassis_6` | `FL_door_6` | 166 |
| `FR_Door_style_WB` | 166 | `FL_door_6` | `FR_door_6` | 170 |

⇒ **每格的名字属于"前一件"**（`ref_id` 与真身 id 的差 = 各件的目录跨度，故不是常数）。**修法**（`wb_rebind`）：族前缀精确匹配 + 后缀 `_5`/`_6` + 取 id 与 ref 最近者 ⇒ **73 个 WB 件全部有解**（唯一 25 / 取最近 40 / 无候选 8），其中 **65 条真的改了名**。

### 8.3 类别二：原厂(stock)件引用车体/他族网格（**原版设计，不是错**）

| 归因 | 条数 | 说明 |
|---|---|---|
| 同族命中 | **271** | 名字含零件族关键词 ⇒ 正常 |
| `style→他族网格` | **93** | 全部是 WB 变体 ⇒ 即 §8.2 的平移（已重绑 65 条）|
| `stock→他族网格` | **69** | 原厂件并入车体/共用网格（`F_Bumper_stock` → `chassis`）|
| `stock→车体网格` | **10** | 名字就是 `chassis` / `NORMAL` / `_MISC_` |
| 名字无族关键词 | **4** | 装饰/发光网格 |

⇒ **111 条"不符"其实是原版的数据组织方式**：原厂件没有独立造型网格（造型并进车体网格 `chassis`/`NORMAL`/`_MISC_`），换 `style_*` 才引入独立网格。这与 `docs/56` 的"19 个死槽 + 原厂件"结论一致。

### 8.4 重制侧取网格的正确流程

```python
x = fixes[车包][类名]                 # WB 件优先（见 data/mesh_id_map.json 的 wb_rebind.fixes）
mesh_id = x["resolved_id"] if x else 零件.configureMesh 的 id
name    = archives[车包].meshes[str(mesh_id)]        # 名字只作注释
geo     = archives[车包].meshes[str(mesh_id)].geo    # 几何语义标签（门/杠/盖/车壳…），可当兜底校验
```
**变体 1–4 直接按 id**；**变体 5/6 走 `wb_rebind`**；`stock` 件的 id 指向车体网格属正常。

### 8.5 本轮新确认的其它事实

- **目录记录流的 `type`**：`142` = 网格（`configureMesh` 引用）、`31` = 视觉类型（`configureVisual`/`RenderType` 引用）、`19` = 污渍贴图、`91` = 图标/贴图、`95` = 灯类网格、`57` = 轮毂、`6` = 杂项。同一资源的两类记录**名字相同、id 相邻或任意**（如 `F_bumper_5` 网格 158 / 视觉 159；`FL_door` 网格 160 / 视觉 263）。
- **`use_mesh\t<N> <b>` 的 N = `configureMesh` 调用序号**（Model 类里 0…6 递增，`Model_Hatch_S2` 有 7 个网格/视觉对）；零件类只有 1 个网格 ⇒ 恒 `0 0` ⇒ 这也解释了为什么早期统计"`use_mesh` 全是 `0 0`"。
- **`Model_*` 类的 `configureMesh`** 只列"整车固定件"（灯/发光面/车壳 `NORMAL`），默认件与造型件在**零件类**里（与 `docs/56` 一致）。
- 网格条目规模：**10 个车包 / 602 个网格条目**；几何标签覆盖 559/602（43 个网格未导出 OBJ）。

## 9. 未决（✗）

| # | 项 | 证据与下一步 |
|---|---|---|
| 1 | ~~材质表 id↔名配对错位~~ | **✅ 已解（见 §8）**：变体 1–4 配对正确（偏移扫描 k=+0 最优）；**变体 5/6（WB 宽体）区整体平移一件**，已给出重绑表（65/73 条改名）。剩余 111 条"不符"是 stock 件引用车体/他族网格 —— 原版设计，不是错误 |
| 2 | `configureVisual` 的 id 空间 | 478 处，id 与网格 id 相邻（142/143）但**大量不在材质表里** ⇒ 属另一张表（渲染类型），未读 |
| 3 | `use_mesh\t0 0` 的确切语义 | 与 `flags 0x400` 同现 467 次；非零值（`1 0`/`3 0`/`4 0`）对应什么未定 |
| 4 | `flags` 各位（0x400/0x004/0x404/0x401）与 `slottype`/`slotdmgmode`/`slotdeform` 的位含义 | 只知出现分布，未读消费者（疑在原生渲染/损伤层）|
| 5 | `PartDecal(0, 0, 59647)` 的三个参数 | 59647 是全局常量（所有零件相同）；贴纸链路（docs/50 §6.6 ISticker）可交叉 |
| 6 | `wing` 类型号 4 vs 5 的区分、`flap` 的开合量单位 | 分布已知（646 / 86）|
