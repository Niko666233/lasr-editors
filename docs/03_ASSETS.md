# P3 — 素材提取：实测结论

## 1. RPAK 归档 ✅ 已解，可全量解包

```
"RPAK" <u32 index_size> <index_size bytes>
<4 字节 ASCII tag> <u32 size> <size bytes>      ← 资源链，**连续无缝**，无对齐
```

- 所有发行版 `index_size == 0x200`（512）。索引内含子包名（长度前缀）：
  `system.rpk`、`maps`、`global_cubemap`、`global_envmap`、`global_map_visualisation` …
**验证**：`vehicles/Hornet_Wega_2006.rpk` → 156 个资源、起始 `0x2424`、
**99.95% 字节覆盖**、仅 1 处间隙（索引区 8,732 B）。

### 全量提取结果（`--all`，全部 60+ 个 .rpk）

| | |
|---|---|
| 输出体积 | **652 MB** |
| 贴图 `.dds` | **1218 个**（480 MB）—— **1218/1218 头部合法** |
| 网格 `.iscx` | **764 个**（49 MB）—— **764/764 结构合法** |
| 嵌套/间隙 `.bin` | 84 个（124 MB） |
| 未覆盖字节 | 93.4 MB（几乎全在 `maps/*.rpk`，已存成 `gapNN_*.bin`） |

贴图格式分布：**DXT5 ×962、DXT3 ×105、DXT1 ×97**、未压缩 RGB/RGBA ×54；
**39 种不同尺寸，最大 2048×2048**。
网格总计：**1,081,563 个顶点 / 977,258 个三角形**。

实测到的顶点步长（全游戏 1125 个 `kind=4` 块）：
`36`×627、`60`×205、`44`×106、`40`×80、`28`×47、`24`×42、`64`×14、`68`×12、
`48`×8、`52`×3、`32`×2 —— **无一例外全部满足 `size == 16 + vertexCount×stride`**。

> `stride=24` 与 `28` 无 UV（= `pos3+nrm3` 与 `pos3+nrm3+colour`），
> 导出 OBJ 时这两个步长不应写 `vt`。
> `sounds.rpk` / `sound.rpk` / `system.rpk` / `maps.rpk` / `routes.rpk`
> 提取到 **0 个资源** —— 它们不用 `<tag><u32 size>` 链（待查）。

校验工具：`tools/verify_all.py`（全量）、`tools/why_rejected.py`（逐条拒绝原因）。

### 已确认资源标签

| tag | 载荷 | 内部 magic | 示例 |
|---|---|---|---|
| `ISCX` | 网格 | `INVO` | Hornet 车 61 个 |
| `ISCY` | 网格（第二类） | `INVO` | frontend 2 个、boulevard 1 个 |
| `IDDS` | 贴图 | `DDS ` | Hornet 车 95 个 |
| `m_ic` | 嵌套容器块 | — | 例 7.5 MB |
| `RPAK` | 归档头自身 | `RPAK` | 1 |

### 贴图 ✅ 全部可直接使用

`tools/check_dds.py` 验证 `vehicles/Hornet_Wega_2006` 的 95 个 DDS：
**95/95 头部合法**，`ddspf.dwFlags = 0x4`（`DDPF_FOURCC`）、
`dwFourCC = 0x35545844` = **DXT5**，全部 100% 一致。

尺寸分布：`1024×1024`(11)、`512×512`(2)、`320×256`(12)、`256×256`(4)、
`128×512`(24)、`128×448`(12)、`256×128`(12)、`64×128`(12)、`4×4`(6)。
合计 16,438,800 B。

**Pillow 可直接解码**（已实测：1024×1024 DXT5 → RGBA 成功，画面为车身涂装层，
含白色泼墨图形与 logo，非噪声）。

解包器：`tools/rpak_extract.py extracted_rpak --all`
→ `extracted_rpak/<归档>/NNNN_<tag>.dds|.iscx|.bin`，未覆盖的间隙另存 `gapNN_*.bin`。

---

## 2. INVO v4 网格 ⏳ 头部与块目录已解，顶点语义未定

### 头部（**不变量已验证**：`offset[0] == 0x0C + 8N`，6/6 个样本成立）

```
0x00 "INVO"
0x04 u32 version = 4
0x08 u32 N                              // 描述符个数
0x0C N × ( u32 kind , u32 offset )      // kind ∈ {0,1,3,4,5}
0x0C+8N  <尾巴> : u32 0, u32 ?, u32 ?, f32 2.0, u32 9|10,
                  u32 nameLen, char name[nameLen]
```

样本（`N`, pairs, 名字）：

| 文件 | N | kind 序列 | 名字 |
|---|---|---|---|
| `drivers/crcman2/body.SCX` | 11 | `0,3,4,5,3,4,5,3,4,5,3` | — |
| `maps/harbor/meshes/clouddome.scx` | 4 | `0,1,4,5` | `felho`（匈牙利语"云"） |
| `maps/harbor/meshes/near.SCX` | 4 | `0,1,4,5` | `11 - Default` |
| `maps/highway/meshes/water.SCX` | 4 | `0,1,4,5` | `water_jo` |
| `vehicles/…/L_tailight_glow.scx` | 4 | `0,1,4,5` | `glow` |
| RPAK 内 Hornet 第 95 号 | 4 | `0,1,4,5` | `interior` |

**每个 region 自身也是一个自描述块**：`<u32 kind><u32 payloadSize><u32 count><u32 x>`。

实测（`near.SCX`）：

| i | kind | region 范围 | 块头 |
|---|---|---|---|
| 0 | 0 | `0x2c..0xbc` (144 B) | `00 00 00 00` `90 00 00 00` `4d 00 00 00` … |
| 1 | 1 | `0xbc..0xc8` (12 B) | `01 00 00 00` `0c 00 00 00` `00 00 00 00` `04 00 00 00` |
| 2 | 4 | `0xc8..0x4c8` (1024 B) | `04 00 00 00` `00 04 00 00` `2a 00 00 00` `81 02 00 00` |
| 3 | 5 | `0x4c8..0x5c4` (252 B) | `05 00 00 00` `fc 00 00 00` `78 00 00 00` `00 00 01 00` |

`kind=1` 块在 4 个文件里**逐字节相同**（`01 000000 0c 000000 00000000 04000000`）
→ 疑似顶点格式/流声明（12 字节：kind、size、?, 分量数=4）。

### ✅ 顶点布局已解出（60 个网格一致性全部通过）

**`kind=4` = 顶点缓冲**
```
u32 kind=4 ; u32 size ; u32 vertexCount ; u32 flags
vertexCount × stride 字节,  stride = (size - 16) / vertexCount
```
| 顶点内偏移 | 内容 |
|---|---|
| `+0` | `float3` **位置** |
| `+12` | `float3` **法线**（单位向量，实测 \|v\|=1.000） |
| `+24` | `u32` 打包颜色（RGBA，如 `ff 7f 7f 80`、`0c 0c 0c ff`） |
| 中段 | `float3` 切线 / `float3` 副切线（宽步长才有） |
| **末 8 字节** | `float2` **UV** |

**步长分布**（`Takura_Tornado_2002` 全部 77 个 `kind=4` 块）：
`60`×53、`36`×19、`68`×4、`64`×1，**size 与 stride 不一致的块：0 个**。

**`kind=5` = 索引缓冲**
```
u32 kind=5 ; u32 size ; u32 indexCount ; u32 flags
indexCount × u16 三角形列表
```
**验证**：60/60 个网格满足 `max(index) < vertexCount`，且
`size == 12 + indexCount*2`、`size == 16 + vertexCount*stride` **逐字节精确相等**。

**目视验证**：`tools/invo_obj.py` 导出 OBJ 并用内置软件光栅器渲染，
`0153_ISCX.iscx`（11218 三角形）渲染出**可辨识的整车**——正面（四圆灯组、
挡风玻璃、前保险杠）与侧面（80 年代楔形跑车轮廓）。

> ⏳ 仍缺：`kind=0`（网格信息块）/`kind=3` 的完整字段语义；
> 多材质切分（`body.SCX` 的 11 个描述符 = 多个子网格 + 各自材质名）；
> 骨骼/蒙皮（`*.bon` 已有明文层级，但顶点里未找到权重字段）。
> **纹理绑定**需要配合明文 `.scm` 材质表 + 归档尾部的 `mesh 0x..`/`texture 0x..` 引用。

加载器报错串：`"Invalid mesh version! -> %s"`（用于定位解析器）。
另有 RVA `0xC64A5` 附近一处网格加载相关函数（先前 `xref_scan` 发现）。

---

## 3. 附带收获：资源引用是明文

`maps.rpk` 等归档尾部是**纯文本场景描述**，直接可读：

```
mesh 0x00000016
texture 0x00000017
shd_center 0.000 0.000 0.000
shd_diru 0.000 0.000 0.000
shd_dirv 0.000 0.000 0.000
shd_vbase 0.000 0.000 0.000
shd_vup 0.000 0.000 0.000
sourcefile groundtype\kavics\snd.evt      ← "kavics" = 匈牙利语"碎石"
volume 1.000
instances 16.000
mindist 5.000
maxdist 15.000
flags 2.000
```

→ 场景由 **`mesh <hex id>` / `texture <hex id>`** 引用，配合 `.scm` 材质表
（也是明文）即可重建"哪个网格用哪张贴图"的映射，**不需要**先解出顶点格式。

例：`wehicles/Fantasy_Corus_2005.rpk` 尾部的 `texture 0x0000000D/0x19/0x17` 序列。
