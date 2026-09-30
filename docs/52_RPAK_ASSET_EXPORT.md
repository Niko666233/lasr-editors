# 52 · RPAK 资源导出：命名解包 / 纹理 PNG / 网格 OBJ

> 覆盖面：52 个 `.rpk` 存档的**命名目录**、1,218 张纹理、780 个网格；产物 `assets_raw/`、
> `assets/`、`out_rpak_{inventory,assets,textures,meshes}.json`；工具 `tools/rpak_export.py`（盘点）、
> `tools/rpak_assets.py`（三阶段导出）。
> 标注规则：✓ = 机械核对过（偏移对得上 / 数量自洽 / 目视验证）；✗ = 未解，写清下一步。

## 0. 一句话结论

RPAK 不只是"无名的标签块链"——**索引区之后紧跟一份带名字的目录**，记录里直接给出
`文件偏移 + 长度`。解出它以后，`IDDS`/`ISCX` 这些匿名块就都变成了真名字
（`U_rim_ST.dds`、`FL_door.iscx`、`asphalt.dds`、`coastline_signs.dds`…），
于是纹理和网格可以直接以引擎能吃的形式导出：

| 产物 | 数量 | 位置 |
|---|---|---|
| 命名解包的原始资源 | **2,019** 个条目（带名 **1,952**，96.7%）+ 280 个目录块内独立命名块 | `assets_raw/<存档>/<名字>.<ext>` |
| 纹理 PNG（DXT1/3/5 全部解开） | **1,218 / 1,218 成功（0 失败）** | `assets/textures/<存档>/<名字>.png` |
| 网格 OBJ（INVO v4 → 三角网格） | **764 个**（1,081,563 顶点 / 977,258 三角） | `assets/meshes/<存档>/<名字>.obj` |
| 另有 16 个"场景容器"（无顶点块，见 §4） | 16 | 记在 `out_rpak_meshes.json.scene_containers` |

## 1. 存档结构（本轮补全）

```
"RPAK"  u32 index_size(512)  index[index_size]
index:
  +0        u32  依赖包数量
  +8        ...  依赖包名表（每个名字占 64 字节槽，长度前缀 + NUL）
                 例 frontend.rpk → "system.rpk" / "sound.rpk" / "maps\obstacles.rpk"
  其后      目录记录流（**可能跨出索引区，接着写进数据区**）
数据区：<4B tag> <u32 size> <payload[size]> 的连续链（链中有断口时按白名单重定位）

目录记录（本轮解出，52 个存档共 3,018 条）：
  u16 flags        // 0x0406 / 0x0407（纹理） / 0x0405 …（值域 0x04xx）
  f32 1.0          // 记录标记（全索引里唯一的 00 00 80 3f）
  u32 file_offset  // 该资源在存档中的绝对偏移（指向条目的 tag 处）
  u32 total_size   // = 条目 payload + 8（也就是"含 tag 头的整条长度"）
  u8  len          // 含结尾 NUL
  char name[len]
```

**绑定验证**：`file_offset` 与条目链的偏移**逐条精确对齐**，且 `total_size == 条目 size + 8`。
按此规则绑定，1,952/2,019 个条目拿到名字（另外 67 个是开发残留/无名块）：

| 类型 | 命名率 |
|---|---|
| `IDDS` 纹理 | **1,195 / 1,218** |
| `ISCX/ISCY` 网格 | **746 / 780** |
| `ITEX` | 11 / 11 |
| 其余（`_640`、`g_ds`、`ICFG` 等） | 0 / 10 |

**踩坑（两处，都已修）**：
1. **目录流会跨索引/数据区边界** —— `frontend.rpk` 的目录从索引里就开始了，接着写进数据区前
   14 KB。只在"gap 区"里找记录会漏掉它（原先 0/53 命名 → 现在 51/53）。改成**全文扫描**。
2. **条目链起点不能想当然取数据区开头** —— frontend 的数据区开头其实是目录字节，会被错认成
   条目（`_640`、`g_ds` 这种伪 tag）。现在取"数据区开头 / 命名记录里的偏移 / 启发式扫描"三者的
   **最长严格链**作为起点（`rpak_export.best_start`）。

## 2. 载荷类型与覆盖率

| tag | 载荷 | 数量 | 说明 |
|---|---|---|---|
| `IDDS` | DDS（DXT5 962 / DXT3 105 / DXT1 97 / 未压缩 54） | 1,218 | 全部是完整 DDS 文件 |
| `ISCX` / `ISCY` | INVO v4 网格 | 780 | 见 §4 |
| `ITEX` | 前端纹理（另一容器） | 11 | |
| `ICFG` | 配置（system.rpk，4–8 B） | 5 | |
| 无 tag 的整块 | 目录流 + 场景块 | — | 见 §5 |

**覆盖**：数据区合计 680,735,701 B，条目链覆盖 583,406,119 B = **85.702%**。
未覆盖的 97 MB 主要是三样：目录记录流本身、地图场景块（`maps/*.rpk` 里 15 MB 级的整块）、
以及 `sound.rpk`/`maps.rpk` 这类"整个数据区就是目录"的存档（它们条目数 0）。

## 3. 纹理（`assets/textures/`）

- **1,218/1,218 全部解开，0 失败**（PIL 直读 DDS：DXT1/3/5 + 未压缩）。
- 尺寸分布 top：`128×512`(239)、`256×256`(152)、`1024×1024`(139)、`128×128`(90)、`320×256`(60)。
- **BC1 一比特透空修正**：Pillow 会把 DXT1 的透明纹素解成纯洋红 `(255,0,255)`（实测
  `maps/texture/sign.png` 的路牌四周就是洋红条）→ 导出时把这色替换成 `alpha=0`。
- 目视验证 ✓：`maps/texture/coastline_signs.png` 是完整可辨的洛杉矶路牌图集
  （San Diego Fwy / Santa Monica / SPEED LIMIT 45 / 405 NORTH / 加油站标志），无错位、颜色正常。

## 4. 网格（`assets/meshes/`）

INVO v4 顶点布局（本轮扩充）：

| stride | 布局 | 出现场景 |
|---|---|---|
| 36 / 60 / 64 / 68 | pos(12) + normal(12) + 色(4) + … + **uv 恒为最后 8 字节** | 车件、粒子、驾驶舱等主体 |
| **24** | pos(12) + 打包色(4) + uv(8)，**无 normal** | `maps/boulevard/{far,mirror}.iscx` |
| **28** | pos(12) + 中间 8B + uv(8)，无 normal（无法线时 OBJ 只写 `f v/vt`） | `mirror_black.iscx`（15,558 顶点）、`mirror_7.iscx` |

- 导出 764 个 OBJ（1,081,563 顶点 / 977,258 三角），**0 失败**。
- 尺寸自洽验证 ✓：`vehicles/Hornet_Wega_2006/chassis` 的包围盒 = x ±90.31、
  y −18.14…105.87、z −222.22…209.54（厘米）→ 车长 4.32 m / 宽 1.81 m / 高 1.24 m，符合真车。
- 目视验证 ✓：软件渲染（`tools/invo_obj.py <iscx> <png>`）能看到正视图（挡风/大灯/保险杠/轮眉）
  与侧视图（三厢车身轮廓），无噪点。
- **16 个"场景容器"没有顶点块**（`frontend/garazs00.iscx`、各图 `map.iscx`、`plane.iscx`…）：
  它们的子流全是 kind=0 分组节点（96–244 B/个，带计数），真正的几何在别的资源里 —— 这批不是
  导出失败，已单列在 `out_rpak_meshes.json.scene_containers`。

## 5. 目录块内独立命名块（280 个）

有些命名记录**不对应任何条目**（它们指向文件里没有 tag 的裸块），已按名字导出为 `.bin`：

| 存档 | 数量 | 例 |
|---|---|---|
| `frontend.rpk` | 112 | 前端 UI/头像相关裸块 |
| `sound.rpk` | 105 | `collision` / `_Buoy` / `_Hydrant` / `chassis` / `ironhits` / `metalhits` |
| `vehicles.rpk` | 17 | `cockpit` / `lightbar` / `general_wheel` / `minimap_icon` / `osd` / `gauge` |
| `maps/hills.rpk` | 15 | 路线相关块 |
| `maps.rpk` | 8 | `global_cubemap` / `global_envmap` / `route_textures` / `global_*_visualisation` |

`sound.rpk` 的自检很干净 ✓：131 条目录记录的 `file_offset` **相邻首尾相接 130/130**
（4454+97=4551 → `_Buoy`…），一路排到文件末尾（13,499 = 文件大小），所以这批块的位置是真偏移。

### 5.1 同存档重名条目（38 处，不是解析错误）

同一存档里允许出现同名条目，两类成因都核实了：

| 成因 | 例（`maps/test.rpk` / `vehicles/Fantasy_Corus_2005.rpk`） |
|---|---|
| **同名不同扩展名**（一张图/一个件的贴图+网格） | `skydome.iscx`(11,204 B) 与 `skydome.dds`(524,416 B) 同名同图；每张图都有一对 `skydome.iscx`/`.dds` |
| **同名同扩展、不同偏移**（hi/lo 或开发残留） | `maps/test.rpk` 里 **两份** `skydome` 网格记录（11,204 B @0x1f2402 与 524,416 B @0x7fe4c7，相差 46×）——test 是开发图 |

计数关系（机械核对）：**780 个网格条目 = 764 个落盘 OBJ + 16 个场景容器**（§4）；
38 处同存档重名里，多数是"同一名字的贴图与网格"（落盘成 `.dds`/`.iscx` 两个不同文件，不冲突）。
重制侧若要用 `test` 图那份 46× 的 hi 版 `skydome`，得按 `out_rpak_assets.json` 里的 `off`/`size`
单独导出 —— 现在落盘规则会覆盖，记在 §6。

## 6. ✗ 未解 / 下一步

| 项 | 现状 | 下一步 |
|---|---|---|
| **网格↔贴图的材质绑定** | ✗ 780 个网格**内部没有任何 `.dds` 名字串**（已全量 grep：0 命中），纹理名只出现在存档目录里，所以按名字牵手做不了 | 材质表在地图/车辆的**场景块**里（`gap00_*.bin`，车包 8,732 B、地图 15 MB）——那里 `item_icons`/`glow`/`lightbar` 与纹理名成对出现，需解它的节点树 |
| 未覆盖的 97 MB（14.3%） | 目录流 + 场景块 + `sound.rpk` 型存档 | 场景块已有部分解析（`tools/map_scene.py` → `out_scene_instances.json`，15,179 实例），剩下的是材质/贴图表 |
| `sound.rpk` 那 105 个块的语义 | 只有名字 | 名字已足够对照 `java.game.Sound`/`SfxRef`（`docs/50 §8`）里的引用 |
| 同存档 hi/lo 重名（38 处，其中 `maps/test` 的 `skydome` 差 46×） | 落盘按名字覆盖，只留一个 | 导出器加 `--keep-dups`：同名加 `_lo`/`_hi` 后缀按 `size` 排序 |
| `ITEX` 载荷格式 | 11 个，未解 | 前端专用纹理容器，重制可先跳过 |
| `.rpk` 里的脚本/字节码 | 无（TUFA 另有来源） | 不适用 |

## 7. 怎么重跑

```bash
PY=./.capenv/Scripts/python.exe

$PY tools/rpak_export.py --audit                    # 52 存档盘点 → out_rpak_inventory.json（含覆盖率）
$PY tools/rpak_assets.py --extract                  # 命名解包 → assets_raw/ + out_rpak_assets.json
$PY tools/rpak_assets.py --extract --archive maps/texture.rpk,frontend.rpk   # 只跑指定存档
$PY tools/rpak_assets.py --textures                 # DDS → PNG → assets/textures/ + out_rpak_textures.json
$PY tools/rpak_assets.py --meshes                   # INVO → OBJ → assets/meshes/ + out_rpak_meshes.json
```

内存/时间（实测）：`--extract` 全量约 1 分钟；`--textures` 约 3 分钟（1,218 张）；
`--meshes` 约 15 秒。三个阶段都可单独重跑，互不依赖（`--textures/--meshes` 读 `assets_raw/`）。
