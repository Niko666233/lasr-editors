# 50 · 数据层：地图内容数据 / 零件系统 / 环境数据

> 覆盖面：§1-§5 地图内容数据（检查点/发车位/横幅/声学盒/昼夜季节，由 `tools/map_data.py` 机械提取，全部带坐标）
> ／ §6 物品·零件系统 ／ §7 赛道类字段语义与引擎消费路径 ／ §8 音频环境·音乐·文本本地化 / §9 未决项汇总。
> 标注规则：✓ = 已回读源码/字节独立核对过；「不确定」= 伪码层读不到，禁止脑补。

> 本轮把重制最缺的一层补上：**每张地图的实际玩法数据**（检查点坐标 / 发车位 / 横幅救援点 / 声学盒 /
> 雾水土光天空反射参数）。此前 49 份文档里 `todNames`/`officialBestLap`/`roadCondition`/`setWater`/
> `customObjects`/`previewFiles`/`blimpCamPos` 等字段 **grep 命中 0 次**。数据全部来自**每张地图包自带的 Java 类**
> （`maps/<图>/classes.zip` → `out_pseudo/maps/<图>/classes/classes/*.java`），不是推测。
>
> **产物**：`out_map_data.json`（原始全字段）、`out_map_tracks.json`（重制直接可用的干净结构）、
> `tools/map_data.py`（提取器，可回归）。

## 0. 伪码读法（继承 docs/48 §0，必读）

1. **形参逆序**：方法第 k 个形参 = `local_(n+1-k)`；`local0` = `this`。
2. **结构化重建吞 `break`、留空块**：空方法体/`return null` 不等于原实现为空。
3. 地图类里 `localN = {...}` 是编译器数组临时量，真数据在 `this.<字段> = localN;`（提取器已自动展开）。

## 1. 地图包结构

盘上 15 个地图目录（10 主图 + 4 张 `_b` 副图 + `test`），每张图 = 磁盘散装文件 + 一个 `<图>.rpk` 索引：

| 地图 | 盘上文件 | 主要扩展名 | `<图>.rpk` | classes.zip 里的类 |
|---|---|---|---|---|
| boulevard | 14 | .spl2×7, .dds×1, .geo×1, .zip×1, .scm×1 | 48630 KB | Boulevard, Boulevard_track_0 |
| business | 14 | .spl2×7, .dds×1, .geo×1, .zip×1, .scm×1 | 33852 KB | Business, Business_track_0 |
| business_b | 4 | .geo×1, .zip×1, .spl2×1, .scm×1 | 1821 KB | Business_b |
| coastline | 15 | .spl2×7, .dds×2, .zip×1, .geo×1, .scm×1 | 33091 KB | Coastline, Coastline_track_0 |
| coastline_b | 4 | .zip×1, .geo×1, .spl2×1, .scm×1 | 1241 KB | Coastline_b |
| harbor | 15 | .spl2×6, .scx×2, .dds×1, .zip×1, .geo×1 | 31023 KB | Harbor, Harbor_track_0 |
| harbor_b | 4 | .zip×1, .geo×1, .spl2×1, .scm×1 | 1466 KB | Harbor_b |
| highway | 15 | .spl2×6, .geo×2, .dds×1, .zip×1, .scm×1 | 36439 KB | Highway, Highway_track_0 |
| hills | 15 | .spl2×6, .dds×1, .zip×1, .geo×1, .rpk×1 | 41286 KB | Hills, Hills_track_0 |
| industrial | 13 | .spl2×6, .dds×1, .zip×1, .geo×1, .scm×1 | 31183 KB | Industrial, Industrial_track_0 |
| observatory | 12 | .spl2×5, .dds×1, .zip×1, .geo×1, .scm×1 | 26069 KB | Observatory, Observatory_track_0 |
| obstacles | 0 |  | 678 KB | — |
| suburban | 16 | .spl2×6, .scx×3, .dds×1, .zip×1, .geo×1 | 40275 KB | Suburban, Suburban_track_0 |
| suburban_b | 3 | .zip×1, .geo×1, .spl2×1 | 2958 KB | Suburban_b |
| test | 8 | .spl2×2, .zip×1, .dds×1, .ptx×1, .scm×1 | 9210 KB | Test, Test_track_0, Test_track_1, Test_track_2 |
| texture | 0 |  | 55584 KB | — |
| urban | 13 | .spl2×6, .dds×1, .zip×1, .geo×1, .scm×1 | 28993 KB | Urban, Urban_track_0 |

**每张主图固定包含**（boulevard 为例）：7 个 `.spl2` 路线、`00.tga` 路线预览图、`<图>_fmod.geo`、
`meshes/track.scm`、`textures/lightset01/{shadowz.shz,lightlet.dat}`、`2.dds` 预览、`classes.zip`。
`_b` 副图只有 3–4 个文件（几何 + spl2 + classes.zip），是主图的**附属区域**（自带音效与几何，`name` 与主图相同）。

## 2. 地图类 `<Map>.java`：环境与表现数据

### 2.1 基本字段

| 地图 | `name` | 可视化边界 min → max | `trackFlags` | `timeLimit` | `totalSpeedTraps` | 预览贴图 |
|---|---|---|---|---|---|---|
| boulevard | `Ventura Blvd` | (-197.5,-9.7,373.9) → (1685.0,17.4,2322.9) | `{'const': 'java.game.item.Item.VCF_STREET'}` | 60.0 | 1 | maps\boulevard\2.dds |
| business | `Grand Avenue` | (-197.5,-9.7,373.9) → (1685.0,17.4,2322.9) | `{'const': 'java.game.item.Item.VCF_STREET'}` | 60.0 | 1 | maps\business\4.dds |
| coastline | `Palos Verdes Drive` | (-197.5,-9.7,373.9) → (1685.0,17.4,2322.9) | `{'const': 'java.game.item.Item.VCF_STREET'}` | 60.0 | 1 | maps\coastline\5.dds |
| harbor | `Peninsula Rd` | (-197.5,-9.7,373.9) → (1685.0,17.4,2322.9) | `{'const': 'java.game.item.Item.VCF_STREET'}` | 60.0 | 1 | maps\harbor\3.dds |
| highway | `San Diego Freeway` | (-197.5,-9.7,373.9) → (1685.0,17.4,2322.9) | `{'const': 'java.game.item.Item.VCF_STREET'}` | 60.0 | 1 | maps\highway\6.dds |
| hills | `Bel Air` | (-197.5,-9.7,373.9) → (1685.0,17.4,2322.9) | `{'const': 'java.game.item.Item.VCF_STREET'}` | 60.0 | 1 | maps\hills\7.dds |
| industrial | `Under the Vincent Thomas Bridge` | (-197.5,-9.7,373.9) → (1685.0,17.4,2322.9) | `{'const': 'java.game.item.Item.VCF_STREET'}` | 60.0 | 1 | maps\industrial\8.dds |
| observatory | `Griffith Observatory` | (-197.5,-9.7,373.9) → (1685.0,17.4,2322.9) | `{'const': 'java.game.item.Item.VCF_STREET'}` | 60.0 | 1 | maps\observatory\9.dds |
| suburban | `W Brightwood St` | (-197.5,-9.7,373.9) → (1685.0,17.4,2322.9) | `{'const': 'java.game.item.Item.VCF_STREET'}` | 60.0 | 1 | maps\suburban\1.dds |
| urban | `Downtown L.A.` | (-197.5,-9.7,373.9) → (1685.0,17.4,2322.9) | `{'const': 'java.game.item.Item.VCF_STREET'}` | 60.0 | 1 | maps\urban\10.dds |
| business_b | `None` | — → — | `None` | None | None |  |
| coastline_b | `None` | — → — | `None` | None | None |  |
| harbor_b | `None` | — → — | `None` | None | None |  |
| suburban_b | `None` | — → — | `None` | None | None |  |
| test | `$1|N/A - Test` | — → — | `{'const': 'java.game.item.Item.VCF_STREET'}` | None | None | maps\test\textures\preview.png |

`todNames`（12 项，**每张图完全相同**）：`$1|Spring Daytime` `$2|Spring Morning` `$3|Spring Sunset`
`$4|Summer Daytime` `$5|Summer Morning` `$6|Summer Sunset` `$7|Autumn Daytime` `$8|Autumn Morning` 
`$9|Autumn Sunset` `$10|Winter Daytime` `$11|Winter Morning` `$12|Winter Sunset`
⇒ 四季 × 早/昼/暮 ⇒ **昼夜时段是可选轴**（谁读、怎么切见 §7）。
⚠ 同一张表里的 `VisualisationBounds_min/max`、`trackFlags`、`timeLimit=60`、`totalSpeedTraps=1` 在**所有地图里都是同一组值**
（5 张抽查去重后只有 1 组：`(-197.485, -9.734, 373.879)` → `(1685.01, 17.411, 2322.89)`）⇒ 又一批**模板残留**，
不能当每张图的可视化边界用（真实边界在赛道类 `visualisationBounds` 里，见 §3.5）。

### 2.2 渲染环境参数

| 地图 | `setFog(...)` | `setWater(x,y,z)` | 尘土 type/level | 辉光阈值 | 环境反射 | 影色 |
|---|---|---|---|---|---|---|
| boulevard | [0, 1350.0, 10000.0, 0.0, 0.0, 0.027, 0.0] | [-100.685997, 200.0, 50.0] | 1/0.63 | 0.25 | [1.0, 1.0] | [11579568, 5987163] |
| business | [0, 1350.0, 10000.0, 0.0, 0.0, 0.027, 0.0] | [-100.685997, 200.0, 50.0] | 1/0.63 | 0.3 | [1.0, 1.0] | [11579568, 5987163] |
| coastline | [0, 500.0, 10000.0, 0.0011, 0.47, 0.07, 21.750002] | [-100.685997, 200.0, 50.0] | 1/0.63 | 0.4 | [1.0, 1.0] | [11579568, 5987163] |
| harbor | [0, 1350.0, 10000.0, 0.0, 0.0, 0.027, 0.0] | [-100.685997, 200.0, 50.0] | 1/0.63 | 0.25 | [1.0, 1.0] | [11579568, 5987163] |
| highway | [0, 1350.0, 10000.0, 0.0, 0.0, 0.027, 0.0] | [-100.685997, 200.0, 50.0] | 1/0.63 | 0.25 | [1.0, 1.0] | [11579568, 5987163] |
| hills | [0, 1350.0, 10000.0, 0.0, 0.0, 0.027, 0.0] | [-100.685997, 200.0, 50.0] | 1/0.63 | 0.3 | [1.0, 1.0] | [11579568, 5987163] |
| industrial | [0, 1350.0, 10000.0, 0.0, 0.0, 0.027, 0.0] | [-100.685997, 200.0, 50.0] | 1/0.63 | 0.3 | [1.0, 1.0] | [11579568, 5987163] |
| observatory | [0, 1350.0, 10000.0, 0.0, 0.0, 0.027, 0.0] | [-100.685997, 200.0, 50.0] | 1/0.63 | 0.35 | [1.0, 1.0] | [11579568, 5987163] |
| suburban | [0, 1350.0, 10000.0, 0.0, 0.0, 0.027, 0.0] | [-100.685997, 200.0, 50.0] | 1/0.63 | 0.5 | [1.0, 1.0] | [11579568, 5987163] |
| urban | [14668988, 1350.0, 10000.0, 0.0, 0.0, 0.027, 0.0] | [-100.685997, 200.0, 50.0] | 1/0.63 | 0.3 | [1.0, 1.0] | [11579568, 5987163] |

★ `setFog` 首参在多数图是 `0`，**coastline 的 near 从 500 起**，**urban 的首参是一个颜色整数 `14668988`(`0x00DFC0BC`)**
⇒ 该参数不是纯数值距离，语义见 §7。`setWater` 全部地图**同值** `[-100.685997, 200.0, 50.0]` ⇒ 疑似模板残留（同 `overallLength` 问题）。

### 2.3 天空 / 全局着色 / 阴影资源（boulevard 为例）

| 项目 | 值 |
|---|---|
| 太阳光源 | `sun = RenderRef(LightType(maps/boulevard.rpk, 10), "sun")` + `setLight(11441513, 0.5, 3758196, 0)` |
| 天穹 5 层 | `skydome[0..4]` = 包内 RenderType **9**(skydome1) / **819**(mirrordome) / **327**(far) / **35**(far mirror) / **40**(fenyek reflect) |
| 全局 cubemap | `ResourceRef("maps/boulevard.rpk", 699)` |
| 阴影图 / 光点表 | `textures/lightset01/shadowz.shz`、`.../lightlet.dat` + `setLightlet(12 floats)` |
| 影色 / 辉光 / 反射 | `setShadowColor(11579568, 5987163)`=`0xB0B0B0,0x5B5B5B`；`setGlowThreshold(0.25)`；`setReflectorColor(0.5,0.5,1.0)` |

### 2.4 横幅 / 救援触发点（`banners`）

`Trigger` 构造 **7 参**（boulevard 第 1 个，逐字）：
```
new java.game.Trigger.<init>(map, new Vector3(-120.941002, 11.303, 94.900002),
                             new Ypr(-0.192, 0.0, 0.0), 565.778992, 12.5, 15.14, "Box01")
```
⇒ `(父地图, 位置, 朝向, ?=565.778992, ?=12.5, ?=15.14, 名字)`，名字是 **`Box01`…`BoxNN` 连续编号**；
**docs/48 已证**这些 banner 触发点就是**救援点**。数量：

| 地图 | 横幅 | 地图 | 横幅 |
|---|---|---|---|
| boulevard | 49 | business | 45 |
| coastline | 97 | harbor | 22 |
| highway | 47 | hills | 124 |
| industrial | 65 | observatory | 60 |
| suburban | 19 | urban | 78 |
| **合计** | **606** | | |

### 2.5 声学盒（`soundSetup()`）

| 地图 | `addRoomBox` | `addReverbBox` | 地图 | `addRoomBox` | `addReverbBox` |
|---|---|---|---|---|---|
| boulevard | 3 | 45 | business | 11 | 26 |
| coastline | 40 | 0 | harbor | 1 | 47 |
| highway | 16 | 57 | hills | 10 | 35 |
| industrial | 0 | 85 | observatory | 1 | 41 |
| suburban | 0 | 3 | urban | 7 | 35 |
| business_b | 0 | 0 | coastline_b | 0 | 0 |
| harbor_b | 0 | 0 | suburban_b | 0 | 0 |

每块 = `addRoomBox(a,b,w,h,d)` + `roomSetPosition` + `roomSetOrientation`（提取器已合成一条记录），reverb 同理。boulevard 首块：
```
addRoomBox(15, 1, 9.31404, 5.93498, 14.0077) @ (424.206024, 5.93498, -41.670097)
addReverbBox(13.239599, 5.93498, 13.810201, 1.0) @ (477.082001, 5.93498, 90.274498)
```
⇒ **y 全等于地面高度（5.93498）**，是沿赛道铺的矩形声学区域（隧道/桥下/建筑间）。

### 2.6 其它每图字段

`winningSceneLocation`（夺冠庆祝机位 Pori）、`blimpCamPos`（boulevard = `Vector3(800,1209,1300)`）、
`music`：**10 张主图全部 `changeMusicSet(Sound.MUSIC_SET_MAIN)`** + `addSfx(citynoise, 0.2)`；
环境循环音 `citynoise = frontend/sounds/suburb/cityloop.wav`（`SFX_LOOPED|SFX_2D`），`_b` 副图另带 `shops01/02`、`forest`、`cricket` 等。

## 3. 赛道类 `<Map>_track_N.java`：玩法数据 ★★★

### 3.1 基本数据（末两列：类里的长度字段是假的）

| 地图/赛道 | `name` | 检查点 | 发车位 | 类里 `overallLength` | **实测 spl2 长度(normal)** | `difficulty`/`direction` |
|---|---|---|---|---|---|---|
| boulevard/track0 | `$1|Ventura Bvd` | 6 | 8 | 5629.0 | 2956.61 | 2/1 |
| business/track0 | `$1|Grand Avenue` | 5 | 8 | 5629.0 | 2465.661 | 2/1 |
| coastline/track0 | `$1|Palos Verdes Drive` | 5 | 8 | 5629.0 | 3834.831 | 2/1 |
| harbor/track0 | `$1|Peninsula Rd` | 5 | 8 | 5629.0 | 2600.519 | 2/1 |
| highway/track0 | `$1|CA 405` | 6 | 8 | 5629.0 | 5100.077 | 2/1 |
| hills/track0 | `$1|Bel Air` | 5 | 8 | 5629.0 | 5221.276 | 2/1 |
| industrial/track0 | `$1|Under the Vincent Thomas Bridge` | 5 | 8 | 5629.0 | 2874.44 | 2/1 |
| observatory/track0 | `$1|Griffith Observatory` | 3 | 8 | 5629.0 | 1391.738 | 2/1 |
| suburban/track0 | `$1|W Brightwood St` | 4 | 8 | 5629.0 | 1604.08 | 2/1 |
| urban/track0 | `$1|5th & 110th` | 6 | 8 | 5629.0 | 3520.168 | 2/1 |
| test/track0 | `$1|Street Autok` | 13 | 8 | None | — | None/None |
| test/track1 | `$1|Track Autok` | 13 | 8 | None | — | None/None |
| test/track2 | `$1|Offroad autok` | 6 | 8 | None | — | None/None |

**★ 已证伪的字段**：所有主图赛道类里 `overallLength = 5629.0`、`difficulty = 2`、`direction = 1`、
`roadCondition = "100% asphalt"`、`officialBestLap = 0.0`。**逐字节验证**：`5629.0` 的 IEEE754 字节 `00 e8 af 45`
在 boulevard 与 harbor 的 .class 里都各出现一次 ⇒ 是游戏自己的数据、不是抬升 bug；
但实测 boulevard=2957m / harbor=2601m / hills=5221m ⇒ **这五个字段是模板残留，不能当每张图的真实属性**。
重制时长度必须从 `.spl2` 几何算（`GmRace.track_length = track.map.getSplineLength(0)`，GmRace.java:74）。

**真·每图可视化边界**（赛道类的 `visualisationBounds`，8 张抽查全不同 ⇒ 这张表才是可信的）：

| 地图 | min (x,y,z) | max (x,y,z) |
|---|---|---|
| boulevard | (-756.5, -10.0, -467.7) | (492.5, -10.0, 213.2) |
| business | (-65.9, -10.0, -665.4) | (411.5, -10.0, 167.3) |
| coastline | (-587.8, -10.0, -708.3) | (719.2, -10.0, 266.6) |
| harbor | (-639.0, -10.0, -432.9) | (-77.8, -10.0, 488.5) |
| highway | (-624.2, -10.0, -149.6) | (1551.2, -10.0, 553.4) |
| hills | (-797.8, -10.0, -1080.3) | (541.7, -10.0, 732.6) |
| industrial | (-342.4, -10.0, -338.5) | (662.7, -10.0, 441.1) |
| observatory | (-186.9, -10.0, -129.5) | (153.0, -10.0, 405.3) |
| suburban | (-554.5, -10.0, -378.9) | (13.5, -10.0, 97.3) |
| urban | (-644.1, -10.0, -599.8) | (374.6, -10.0, 596.8) |

### 3.2 ★ 检查点全表（82 个，逐字坐标）

`CheckPoint(位置 Vector3, 朝向 Ypr, 判定盒 size Vector3)`；判定盒**每张图不同**：

| 尺寸 (x,y,z) | 次数 |
|---|---|
| `[25.0, 7.5, 0.25]` | 29 |
| `[13.0, 3.0, 0.3]` | 22 |
| `[30.0, 7.5, 0.25]` | 4 |
| `[10.0, 7.5, 0.25]` | 4 |
| `[20.0, 7.5, 0.25]` | 3 |
| `[7.761, 3.0, 0.3]` | 3 |
| `[15.0, 7.5, 0.25]` | 2 |
| `[13.1, 7.5, 0.25]` | 2 |
| `[10.0, 3.0, 0.3]` | 2 |
| `[13.0, 3.03, 0.3]` | 2 |
| `[7.751, 3.0, 0.3]` | 2 |
| `[36.5, 7.5, 0.25]` | 1 |
| `[33.525002, 7.5, 0.25]` | 1 |
| `[73.364998, 7.5, 0.25]` | 1 |
| `[37.5, 7.5, 0.25]` | 1 |
| `[40.0, 7.5, 0.25]` | 1 |
| `[108.75, 7.5, 0.25]` | 1 |
| `[7.752, 3.0, 0.3]` | 1 |

⇒ **docs/48 写的「门盒 25/7.5/0.25」只是最常见值（29/82）**：harbor=10、industrial=15、observatory/suburban=20、
business=33.525、test 驾校线=10/13 × 3 × 0.3（y 也不一样：主图 7.5，驾校 3.0）。

#### boulevard / track0 — `$1|Ventura Bvd`（6 个检查点）

| # | 位置 (x,y,z) | 朝向 (yaw,pitch,roll) | 判定盒 |
|---|---|---|---|
| 1 | [-186.223007, 7.5, 36.571499] | [1.38711, 0.0, 0.0] | [25.0, 7.5, 0.25] |
| 2 | [-698.084045, 7.5, -64.568604] | [1.03701, 0.0, 0.0] | [25.0, 7.5, 0.25] |
| 3 | [-683.278992, 7.5, -417.931] | [-0.831918, 0.0, 0.0] | [25.0, 7.5, 0.25] |
| 4 | [-159.643997, 7.5, -185.688004] | [-1.57106, 0.0, 0.0] | [25.0, 7.5, 0.25] |
| 5 | [443.480988, 7.5, -38.885704] | [-2.37202, 0.0, 0.0] | [25.0, 7.5, 0.25] |
| 6 | [448.516998, 7.5, 157.281006] | [2.21039, 0.0, 0.0] | [36.5, 7.5, 0.25] |

#### business / track0 — `$1|Grand Avenue`（5 个检查点）

| # | 位置 (x,y,z) | 朝向 (yaw,pitch,roll) | 判定盒 |
|---|---|---|---|
| 1 | [-0.299257, 14.147901, -85.076698] | [0.009607, 0.0, 0.0] | [33.525002, 7.5, 0.25] |
| 2 | [5.09302, 16.771, -644.542969] | [-0.775792, 0.0, 0.0] | [25.0, 7.5, 0.25] |
| 3 | [255.263992, 6.63438, -437.402985] | [0.009607, 0.0, 0.0] | [20.0, 7.5, 0.25] |
| 4 | [252.848999, -1.12483, -56.286503] | [0.795005, 0.0, 0.0] | [30.0, 7.5, 0.25] |
| 5 | [378.152008, -12.449499, 152.423996] | [-0.863058, 0.0, 0.0] | [30.0, 7.5, 0.25] |

#### coastline / track0 — `$1|Palos Verdes Drive`（5 个检查点）

| # | 位置 (x,y,z) | 朝向 (yaw,pitch,roll) | 判定盒 |
|---|---|---|---|
| 1 | [-257.857971, 19.917299, 124.927002] | [1.56676, 0.0, 0.0] | [25.0, 7.5, 0.25] |
| 2 | [-379.90799, 34.146099, -652.968018] | [2.77289, 0.0, 0.0] | [73.364998, 7.5, 0.25] |
| 3 | [266.812988, 91.541603, -213.013992] | [1.13286, 0.0, 0.0] | [25.0, 7.5, 0.25] |
| 4 | [694.236023, 53.644199, -66.7687] | [0.247812, 0.0, 0.0] | [25.0, 7.5, 0.25] |
| 5 | [661.348938, 29.8972, 47.385902] | [-0.385379, 0.0, 0.0] | [37.5, 7.5, 0.25] |

#### harbor / track0 — `$1|Peninsula Rd`（5 个检查点）

| # | 位置 (x,y,z) | 朝向 (yaw,pitch,roll) | 判定盒 |
|---|---|---|---|
| 1 | [-117.290993, 7.5, -42.480003] | [0.009607, 0.0, 0.0] | [10.0, 7.5, 0.25] |
| 2 | [-540.700012, 7.5, -358.287994] | [-1.56119, 0.0, 0.0] | [10.0, 7.5, 0.25] |
| 3 | [-93.843903, 7.5, -313.266998] | [0.009607, 0.0, 0.0] | [10.0, 7.5, 0.25] |
| 4 | [-95.886398, 7.5, 471.275024] | [-0.863058, 0.0, 0.0] | [10.0, 7.5, 0.25] |
| 5 | [-182.621017, 7.5, 417.208008] | [-0.426726, 0.0, 0.0] | [25.0, 7.5, 0.25] |

#### highway / track0 — `$1|CA 405`（6 个检查点）

| # | 位置 (x,y,z) | 朝向 (yaw,pitch,roll) | 判定盒 |
|---|---|---|---|
| 1 | [328.118011, 7.5, 205.229996] | [-1.57284, 0.0, 0.0] | [25.0, 7.5, 0.25] |
| 2 | [1443.189941, 15.386499, 465.016022] | [-0.504773, 0.0, 0.0] | [40.0, 7.5, 0.25] |
| 3 | [1167.699951, 14.9339, 172.173019] | [2.30967, 0.0, 0.0] | [25.0, 7.5, 0.25] |
| 4 | [332.614014, 7.5, 154.222] | [1.57053, 0.0, 0.0] | [25.0, 7.5, 0.25] |
| 5 | [-559.47406, 10.549399, -89.744598] | [-0.852031, 0.0, 0.0] | [25.0, 7.5, 0.25] |
| 6 | [-559.936035, 10.141001, 154.093002] | [0.760312, 0.0, 0.0] | [25.0, 7.5, 0.25] |

#### hills / track0 — `$1|Bel Air`（5 个检查点）

| # | 位置 (x,y,z) | 朝向 (yaw,pitch,roll) | 判定盒 |
|---|---|---|---|
| 1 | [75.937103, 65.604698, -732.678955] | [3.08471, 0.0, 0.0] | [25.0, 7.5, 0.25] |
| 2 | [238.639999, 72.194992, 710.620972] | [2.19243, 0.0, 0.0] | [15.0, 7.5, 0.25] |
| 3 | [141.405991, 163.360001, 258.92099] | [1.48534, 0.0, 0.0] | [25.0, 7.5, 0.25] |
| 4 | [-758.817017, 231.130005, -66.153] | [-0.704058, 0.0, 0.0] | [25.0, 7.5, 0.25] |
| 5 | [69.359711, 68.423393, -1042.76001] | [1.42401, 0.0, 0.0] | [25.0, 7.5, 0.25] |

#### industrial / track0 — `$1|Under the Vincent Thomas Bridge`（5 个检查点）

| # | 位置 (x,y,z) | 朝向 (yaw,pitch,roll) | 判定盒 |
|---|---|---|---|
| 1 | [577.538025, 6.32813, 303.669006] | [0.494115, 0.0, 0.0] | [15.0, 7.5, 0.25] |
| 2 | [84.825294, 6.41821, 193.464996] | [-1.36754, 0.0, 0.0] | [25.0, 7.5, 0.25] |
| 3 | [-190.608002, 7.5, -304.778015] | [1.03165, 0.0, 0.0] | [108.75, 7.5, 0.25] |
| 4 | [12.2572, 7.5, 288.908997] | [-2.31545, 0.0, 0.0] | [30.0, 7.5, 0.25] |
| 5 | [619.694031, 7.5, 404.574005] | [2.08421, 0.0, 0.0] | [25.0, 7.5, 0.25] |

#### observatory / track0 — `$1|Griffith Observatory`（3 个检查点）

| # | 位置 (x,y,z) | 朝向 (yaw,pitch,roll) | 判定盒 |
|---|---|---|---|
| 1 | [37.141399, 34.883598, 318.481995] | [3.13244, 0.0, 0.0] | [20.0, 7.5, 0.25] |
| 2 | [89.404701, 20.3636, -96.342804] | [1.04693, 0.0, 0.0] | [25.0, 7.5, 0.25] |
| 3 | [-152.16301, 19.626902, 41.376598] | [0.501101, 0.0, 0.0] | [25.0, 7.5, 0.25] |

#### suburban / track0 — `$1|W Brightwood St`（4 个检查点）

| # | 位置 (x,y,z) | 朝向 (yaw,pitch,roll) | 判定盒 |
|---|---|---|---|
| 1 | [-273.272034, 123.590996, 75.742294] | [-1.56119, 0.0, 0.0] | [20.0, 7.5, 0.25] |
| 2 | [-23.7911, 146.757996, -208.667007] | [-0.401774, 0.0, 0.0] | [30.0, 7.5, 0.25] |
| 3 | [-296.362, 171.768997, -357.498993] | [-1.51268, 0.0, 0.0] | [13.1, 7.5, 0.25] |
| 4 | [-523.187988, 118.538002, 61.4771] | [0.031134, 0.0, 0.0] | [13.1, 7.5, 0.25] |

#### urban / track0 — `$1|5th & 110th`（6 个检查点）

| # | 位置 (x,y,z) | 朝向 (yaw,pitch,roll) | 判定盒 |
|---|---|---|---|
| 1 | [-317.561005, 35.917599, -294.237] | [-1.31815, 0.0, 0.0] | [25.0, 7.5, 0.25] |
| 2 | [247.879013, 25.0361, -563.017029] | [-0.931206, 0.0, 0.0] | [25.0, 7.5, 0.25] |
| 3 | [215.617004, 17.8316, -234.016998] | [0.245975, 0.0, 0.0] | [25.0, 7.5, 0.25] |
| 4 | [55.752598, 23.520601, 177.675018] | [0.523333, 0.0, 0.0] | [25.0, 7.5, 0.25] |
| 5 | [-76.088402, 29.322901, 579.697998] | [1.26248, 0.0, 0.0] | [25.0, 7.5, 0.25] |
| 6 | [-607.182007, 35.5084, 48.443703] | [0.513416, 0.0, 0.0] | [25.0, 7.5, 0.25] |

#### test / track0 — `$1|Street Autok`（13 个检查点）

| # | 位置 (x,y,z) | 朝向 (yaw,pitch,roll) | 判定盒 |
|---|---|---|---|
| 1 | [13.59, 3.646, 10.415999] | [0.661, 0.002, 0.0] | [10.0, 3.0, 0.3] |
| 2 | [-49.161999, 1.822, -70.545998] | [0.665, -0.017, 0.0] | [13.0, 3.0, 0.3] |
| 3 | [-141.531998, 0.699, -97.638] | [1.788, -0.007, 0.079] | [13.0, 3.0, 0.3] |
| 4 | [-214.218994, 0.388, -33.274002] | [2.801, 0.003, 0.237] | [13.0, 3.03, 0.3] |
| 5 | [-198.363998, 0.392, 61.964005] | [-2.471, 0.002, 0.192] | [13.0, 3.0, 0.3] |
| 6 | [-107.309006, -0.233, 99.321999] | [-1.464, -0.01, 0.027] | [13.0, 3.0, 0.3] |
| 7 | [-27.993, -1.969, 43.361] | [-0.661, -0.024, 0.0] | [13.0, 3.0, 0.3] |
| 8 | [34.510998, -1.892, -36.796001] | [-0.662, 0.033, 0.0] | [13.0, 3.0, 0.3] |
| 9 | [116.692993, -0.102, -89.93] | [-1.534, 0.001, -0.023] | [13.0, 3.0, 0.3] |
| 10 | [200.255005, 0.39, -40.548] | [-2.672, 0.003, -0.216] | [13.0, 3.0, 0.3] |
| 11 | [190.451996, 0.393, 55.855999] | [2.47, 0.002, -0.182] | [13.0, 3.0, 0.3] |
| 12 | [98.498001, 1.174, 87.521996] | [1.339, 0.014, -0.002] | [13.0, 3.0, 0.3] |
| 13 | [22.841, 3.193, 22.269001] | [0.663, 0.033, 0.0] | [13.0, 3.0, 0.3] |

#### test / track1 — `$1|Track Autok`（13 个检查点）

| # | 位置 (x,y,z) | 朝向 (yaw,pitch,roll) | 判定盒 |
|---|---|---|---|
| 1 | [13.59, 3.646, 10.415999] | [0.661, 0.002, 0.0] | [10.0, 3.0, 0.3] |
| 2 | [-49.161999, 1.822, -70.545998] | [0.665, -0.017, 0.0] | [13.0, 3.0, 0.3] |
| 3 | [-141.531998, 0.699, -97.638] | [1.788, -0.007, 0.079] | [13.0, 3.0, 0.3] |
| 4 | [-214.218994, 0.388, -33.274002] | [2.801, 0.003, 0.237] | [13.0, 3.03, 0.3] |
| 5 | [-198.363998, 0.392, 61.964005] | [-2.471, 0.002, 0.192] | [13.0, 3.0, 0.3] |
| 6 | [-107.309006, -0.233, 99.321999] | [-1.464, -0.01, 0.027] | [13.0, 3.0, 0.3] |
| 7 | [-27.993, -1.969, 43.361] | [-0.661, -0.024, 0.0] | [13.0, 3.0, 0.3] |
| 8 | [34.510998, -1.892, -36.796001] | [-0.662, 0.033, 0.0] | [13.0, 3.0, 0.3] |
| 9 | [116.692993, -0.102, -89.93] | [-1.534, 0.001, -0.023] | [13.0, 3.0, 0.3] |
| 10 | [200.255005, 0.39, -40.548] | [-2.672, 0.003, -0.216] | [13.0, 3.0, 0.3] |
| 11 | [190.451996, 0.393, 55.855999] | [2.47, 0.002, -0.182] | [13.0, 3.0, 0.3] |
| 12 | [98.498001, 1.174, 87.521996] | [1.339, 0.014, -0.002] | [13.0, 3.0, 0.3] |
| 13 | [22.841, 3.193, 22.269001] | [0.663, 0.033, 0.0] | [13.0, 3.0, 0.3] |

#### test / track2 — `$1|Offroad autok`（6 个检查点）

| # | 位置 (x,y,z) | 朝向 (yaw,pitch,roll) | 判定盒 |
|---|---|---|---|
| 1 | [-126.306, 0.0, -83.879005] | [1.571, 0.0, 0.0] | [7.751, 3.0, 0.3] |
| 2 | [-163.889008, 5.969, -12.538] | [-3.14, 0.174, 0.0] | [7.751, 3.0, 0.3] |
| 3 | [-153.672012, 0.593, 79.879005] | [-2.172, 0.026, 0.153] | [7.761, 3.0, 0.3] |
| 4 | [-107.528999, -0.062, 14.938] | [-1.248, 0.012, -0.016] | [7.761, 3.0, 0.3] |
| 5 | [-21.329, 4.689, -6.94] | [0.1, -0.002, 0.242] | [7.761, 3.0, 0.3] |
| 6 | [-79.080002, 0.056, -60.004002] | [0.001, 0.03, 0.014] | [7.752, 3.0, 0.3] |

### 3.3 发车位 `startGrid`（每张赛道 8 格）

每张赛道都有 **8 个 `Pori`**（位置+朝向）= 8 人赛发车位，第 1 格为杆位。前 3 格样例：

| # | boulevard | harbor |
|---|---|---|
| 1 | [-177.515991, 0.0, 32.033195] | [-114.207001, 0.0, -29.805399] |
| 2 | [-178.304001, 0.0, 35.886902] | [-110.315002, 0.0, -29.772202] |
| 3 | [-178.964996, 0.0, 39.817699] | [-115.820999, 0.0, -19.656401] |

### 3.4 路线变体：`spline[]` 与 `complexspline`

| 地图 | `spline[]`（救援/捷径线） | `complexspline` 变体 | 实测长度（m） |
|---|---|---|---|
| boulevard | rescue, shortcut | normal, slow, fast, shortcut | normal=2956.61, slow=2989.264, fast=2935.206, shortcut=2918.442 |
| business | rescue, shortcut | normal, slow, fast, shortcut | normal=2465.661, slow=2537.34, fast=2465.661, shortcut=2259.939 |
| coastline | rescue, shortcut | normal, slow, fast, shortcut | normal=3834.831, slow=3864.446, fast=3825.15, shortcut=3759.344 |
| harbor | slow, shortcut | normal, slow, fast, shortcut | normal=2600.519, slow=2644.816, fast=2599.398, shortcut=2575.813 |
| highway | slow, shortcut | normal, slow, fast, shortcut | normal=5100.077, slow=5194.618, fast=5100.077, shortcut=5095.012 |
| hills | slow, shortcut | normal, slow, fast, shortcut | normal=5221.276, slow=5320.008, fast=5221.137, shortcut=5181.525 |
| industrial | slow, shortcut | normal, slow, fast, shortcut | normal=2874.44, slow=2932.847, fast=2874.44, shortcut=2758.992 |
| observatory | slow | normal, slow, fast | normal=1391.738, slow=1422.204, fast=1391.738 |
| suburban | rescue, slow, fast | normal, slow, fast | normal=1604.08, slow=1607.42, fast=1582.955 |
| urban | slow, shortcut | normal, slow, fast, shortcut | normal=3520.168, slow=3598.625, fast=3520.168, shortcut=3511.837 |

`complexspline = ComplexSpline({normal,slow,fast,shortcut}, {-0.4,-1.0,0.2,1.0}, {0.4,-0.2,1.0,-1.0}, {60,110,50,100}, {10,40,30,99999,0.35,1.0})`（boulevard 逐字）
⇒ 后 4 个数组是每个变体一套参数（前两组像左右偏移、第三组像目标速度、第四组含 99999 上限）——**语义待 §7 确认**。
这 4 条变体即 AI 车流快/正常/慢线与捷径线（几何来源见 docs/21）。

### 3.5 自定义场景物件 `customObjects`

`prepareTrack(Map)` 给赛道挂包内物件，**10 张主图全部同一个**：
```
GameRef(customObjects, GameType("maps/<图>.rpk", 34), "0.0, 0.0, 0.0, 0.0, 0.0, 0.0", "ccw fenyiv")
```
（`fenyiv` = 匈牙利语 fényív「灯光拱门」；`ccw` = 逆时针。）`test` 的 Offroad 线挂 **`GameType("maps/Tokyo.rpk", 752)`
名为 `buoy ` 的浮标**（各带 6 float 变换）——引用了**发货包里不存在的 Tokyo.rpk**，开发期残留。

## 4. 产物与工具

| 文件 | 内容 |
|---|---|
| `out_map_data.json` | 510 KB：15 张图 × (2–4 类) 的**全部字段 + 全部调用** |
| `out_map_tracks.json` | 干净结构：每图 `env` + `tracks`(检查点/发车位/路线变体/长度) + `banners` + `sound` |
| `tools/map_data.py` | 提取器：无参=全量，`--export`=干净版，`<地图名>`=单图摘要 |

提取器踩坑（写工具时踩到的，已修）：`localN` 数组要展开；**`split_top` 必须认引号**（`"0.0, 0.0, ..."` 会被逗号切碎）；
调用表达式不能连结尾分号一起 parse；调用参数里的 `local` 引用也要 resolve。

## 5. 重制落地要点（地图侧）

1. 几何：`out_routes.json`（70 条 .spl2 全几何）+ `out_map_tracks.json` 的长度/变体映射。
2. 玩法线：**检查点表 + 发车位 + 横幅救援点**三张表即可跑一局（配合 docs/48 会话规则）。
3. 判定盒按图取值，别硬编码 25/7.5/0.25。
4. 环境：每图一套 fog/water/cubemap/skydome(5)/shadowmap/影色/辉光/envmap/反射色 + `Box01..NN` 救援点表。
5. 音频：每图 room/reverb 盒表（沿赛道铺）+ 环境循环音 + `MUSIC_SET_MAIN`。
6. 昼夜：`todNames` 12 项（每图同表），重制时留成参数轴。

---

<!-- 以下由子代理结果续接：零件系统 / 字段语义 / 音频与文本 -->

---

## 6. 物品 / 零件系统（`java.game.item`）

> 证据：`out_pseudo/java/classes/game/item/*.java`、`out_pseudo/java/classes/game/parts/*`、`out_pseudo/vehicles/Fantasy_Corus_2005/hatch/classes/classes/*`。
> 本节的常量表、位掩码、方法签名**已由我逐条回读源码核对**（见 §6.1、§6.6 的逐字引用）✓。
> 三路语义子代理的完整带行号证据另存档：`docs/annex/50A_items_raw.md`。

### 6.1 `Item.java` 静态常量全表（逐字，`Item.java:44-75`）

```
Item.java:47  ITF_ALL            = -1
Item.java:48  ITF_KINDOF_SUSP    = 15        // =1|2|4|8，其中 bit3(8) 无具名常量
Item.java:49  ITF_OFFROAD_SUSP   = 1
Item.java:50  ITF_STREET_SUSP    = 2
Item.java:51  ITF_TRACK_SUSP     = 4
Item.java:52  ITF_KINDOF_TYRE    = 240       // =16|32|64|128
Item.java:53  ITF_OFFROAD_TYRE   = 16
Item.java:54  ITF_STREET_TYRE    = 32
Item.java:55  ITF_WINTER_TYRE    = 64
Item.java:56  ITF_TRACK_TYRE     = 128
Item.java:57  VCF_KINDOF_TERRAIN = 7936      // =256|512|1024|2048|4096
Item.java:58  VCF_OFFROAD        = 256
Item.java:59  VCF_RALLY          = 512
Item.java:60  VCF_ROAD           = 1024
Item.java:61  VCF_STREET         = 2048
Item.java:62  VCF_CIRCUIT        = 4096
Item.java:63  VCF_KINDOF_GROUP   = 253952    // =8192|16384|32768|65536|131072
Item.java:64  VCF_GR_S           = 8192
Item.java:65  VCF_GR_A           = 16384
Item.java:66  VCF_GR_B           = 32768
Item.java:67  VCF_GR_C           = 65536
Item.java:68  VCF_GR_D           = 131072
Item.java:69  IFM_ALL = -1 / 70 IFM_BODY = 1 / 71 IFM_STYLING = 2
Item.java:72  IFM_POWER = 4 / 73 IFM_HANDLING = 8 / 74 IPL_DEFAULT = 0
```

- **两个名字族不存在**：任务预设里的 `ILF_*`、`ITEM_*`、`getXPGain` 全工程零命中；`BET_TYPE_*` 属 `Bet.java:2-7`（1=Prestige, 2=PerformPart, 3=StylingPart, 4=IVehicle, 5=WholeStage, 6=WholeStyle）。
- `Item` 实例字段只有 7 个：`id / itemroot / option / lastSessionId(-1) / iconTextureAndUV(null) / trackFlags(ITF_ALL) / filterFlags(IFM_ALL)`（`Item.java:29-32`）。**没有任何 XP / 价格 / 等级 / 解锁字段**。
- ⚠ 一多半方法体是重建产物（`getId()->0`、`dropItem()->0`、`findItem()->this`、`use()->true`、`getTimeLeft()->0`、`getPrestige()->0`、`getDescription()->"Sorry, no info for this item, yet."`），**不能断言原实现就是空的**。

### 6.2 持有关系与槽位

| 关系 | 证据 |
|---|---|
| `Player.items = new ItemRoot()`（玩家物品总根） | Player.java:2 |
| `IVehicle` 持有 `IPart[65] slotParts` + `Vector spareParts` | IVehicle.java:133-134 |
| `IPart.vhc` 反向指车（`IVehicle.getIPart(int)` 里回填） | IVehicle.java:914-915 |
| `IPart.part[]` = 物理侧 `java.game.parts.Part` 实例（轮胎/轮圈各 4 个） | ITyres.java:5、IRims.java:8 |
| 槽位常量 `ITEMSLOT_*` = 0…64（含 `ITEMSLOT_DUMMIESOFTHEDUMMIES=60`） | IVehicle.java:34-98 |
| `SlotMap(int slot, int partIndex, int linkVirtualSlot)`：本槽对应本零件第几个 Part、以及是否挂在另一个"虚拟槽"的零件实例上 | SlotMap.java:1-10 |

`ItemRoot` 用**物品 id 的最高 3 位当种类**：`TYPE_BITS=3, TYPE_SHFT=29, TYPE_MASK=((1<<3)-1)<<29`（ItemRoot.java:2-4），再按 `lists[primary-1]` 分派到 `vehicles[23] / maps[11] / drivers[8] / extras[10] / gamemodes / pets`（ItemRoot.java:26-30）。

**装备链（装）**：`CardComponent.Checkbox1_onAction` → post `cardChecked`（CardComponent.java:89）→ `ItemlistComponent.itemlist_onCustomEvent` → `item.attachItem(part)`（ItemlistComponent.java:243）→ `MetaServer.changeUserItemPosition(id,option)` 上报（244-249）→ `car.endUpdate()`。
`IVehicle.attachItem`（IVehicle.java:955-1103）顺序：延迟队列(`massUpdate`) → 取 `getAttachOptions()`（空则 `System.exit("missing attach data...")`）→ **卸掉将占用的槽上现有零件** → 走 `Vehicle.getSlotLookupTable()` 的 `SlotMap[]` 找安装基体（`linkVirtualSlot>=0` 时取虚拟槽零件，否则 `this.vhc`）→ `base.installPart(...)`（1056）→ `part.status=true` → 重算 `option`（1069-1080）→ `part.onInstall()` → **把被顶替的零件逐层挂回去** → `statChanges[]` 累加进 `vhc.statStates[]` → `part.makeCompatible(lastCompatibilityFlags)`。

**装备链（卸）**：`cardUnChecked` → `removeItemSafe(part)`（ItemlistComponent.java:262）→ 若是动力/操控件则 `attachPreviousStage(part)`（263-265，即**自动退回上一阶的库存件**）。
`IVehicle.removeItemSafe(part,flags)`：取库存件 → `removeItem(part)` → 重新挂库存件 → 被顶替件按 `(getTrackFlags()&flags)!=0` 决定挂回还是继续下卸（IVehicle.java:786-807）。

**整段升级**：`setCarToStage(stage)` 挂上所有 `isPerformancePart() && getStage()==stage` 的件；`stage==4 且挂了 7 件` → `readyToTrial=true`（IVehicle.java:619-633）。

### 6.3 零件分类：四大页 + 等级

| IFM 类 | 零件接口类（写 `filterFlags` 的行号） |
|---|---|
| `IFM_BODY`(1) | IF_Bumper:16、IR_Bumper:16、IHood:16、ISideskirts:16、ITrunkLid:16、IHatchDoor:8、IF_Doors:8、ITrunkRWing:16、IChassRWing:16、ICTF_Lightbar:8 |
| `IFM_STYLING`(2) | IRims:13、IPaintjob:39、ISticker:22、IInterior:8、ISteeringWheel:17 |
| `IFM_POWER`(4) | IEngine:23、ITransmission:15、IMuffler:25、INitrous:16 |
| `IFM_HANDLING`(8) | IRunningGear:22、ITyres:10、IWeightReduction:9 |

改装界面按此分 4 页，入选条件 `(getItemFilterFlags()&flag)!=0 && isDefault()==0`（ItemlistComponent.java:351-354、403）。**另有一个正交概念** `isPerformancePart()`＝instanceof {IEngine, IRunningGear, ITransmission, IMuffler, ITyres, IWeightReduction, INitrous}（IPart.java:74），它决定"赌注能押哪些零件"（Player.java:127,165）。

**等级 = `kind` 字段，读接口 `getStage()`**（IPart.java:103 基类返回 −1）：
`1..5 → "Stage I"/"Stage II"/"Stage III"/"Stage IV"/"Unique"`（IEngine.java:141-154），外观件同值但文案为 `Style I..IV`（IF_Bumper.java:49-63）；**宽体件 = kind 5**（`isWideBody()` 时 `getMaxPossibleStage()` 一律 5，IVehicle.java:400-434），宽体车 id = 基础 id + `(10<<16)`（Gamelogic.java:282）。
文件命名：`*_stock` / `*_stage_I..IV`（动力）/ `*_style_I..IV`（外观）/ `*_{stage,style}_WB`（宽体）。

**另一套"阶"在 id 空间**：零件索引 ≥2048 是升级链，`getUpgradePrecondition()` 给出前置（`2048→0, 2049→2048, …`，IVehicle.java:1460-1484）；这类件装卸时 `option` 被强制成 `7/56` 或 `0`（IVehicle.java:1072-1080、1178-1180）。
`IVehicle.presetFlags` 默认 `9 = IFM_BODY|IFM_HANDLING`，`option` 的 bit0-2 存 body 档、bit3-5 存 handling 档（IVehicle.java:129、1069-1080）。

### 6.4 一个具体零件里到底存了什么（以 Fantasy Corus 2005 / hatch 为例）

| 零件 | 关键字段与**确切值** | 证据 |
|---|---|---|
| IEngine stock | `engine_volume=1548.0`、`idle=900.0`、`starter=50.0`、`redline=6000`、`limiter=6500`、`limiter_reset=500.0`、`inertia=0.125`、`bt={33.0,1.848,0.136,0.031}`、`cl={-40.0,180.0,4.5,0.0}`、曲线 `eRPMs={0,941,2334,3362,4201,5234,5613,5946,7000}` / `eMuls={0,99,142,153,151,148,146,144,96}`、`ClutchF=1.0*380` | Hatch_S2_IEngine_stock.java:28-46 |
| 传动 | `gears=5`；`ratios[0..8]={0,3.133,1.922,1.384,0.99,0.796,0,−3.284,4.28}`；换挡时间 `setTransmissionTimes(0, 0.2, 0.4, 1.0, 0.5, 0.4, 1.0)`；三差速器全 `DIFF_OPEN`（前/后 ±3000、中央 ±100000，`driveFrontRate=1.0`） | IGearbox_stock.java:2-15、IDiffs_stock.java:2-11 |
| 轮胎/轮圈 | 尺寸串 `195/55 R14x7`、`sizes={195.0,55.0,14.0,7.0}`、`configureType("flexible\t0.00002 0.925")`、物理槽 **3240/3241/3140/3141**；轮圈 `sizes={7.0,14.0,60.0,280.0}`、密度 `2.3`、钉密度 `1.7`、品牌 `"Invictus"`、名 `"Corus Factory 7J14 ET+60 BD 280"` | Hatch_S2_Tyre_U_ST_stock.java:2-20、Hatch_S2_Rim_U_ST_stock.java:2-33 |
| 减重 | **stock 车身 394.000 kg**（`"body 0.000 0.044 -0.1125 … 394.000 box 0.826 0.600 1.875"`）→ stage I **250.000 kg** | Hatch_S2_WeightReduction_stock.java:11、_stage_I.java:11 |
| 氮气 | kind→写死表 `1→(nitroGain 0.55, tank 4.0)`、`2→(0.5,6.0)`、`3→(0.45,8.0)`、`4→(0.4,10.0)`、`5→(0.45,12.0)`，再 `nitroGain*=gain`、`nitroLeastRPMmul=minRPMmul`、`consumption_nitro=1.0` | INitrous.java:22-48 |
| 外观件 | 接口层只放元数据（`attach={ITEMSLOT_STYL_F_BUMPER/HOOD/SIDESKIRTS}`、`trackFlags=ITF_ALL`、`filterFlags=IFM_BODY`、`itemShowPriority` 基数 1.0/0.0/2.0 + kind*0.1）；物理/贴图在网格类：`maskTexture=ResourceRef("vehicles/Fantasy_Corus_2005.rpk",93)`、`configureMesh(rpk,71)`、`configureTexture(rpk,13)` | IF_Bumper.java:9-94、Hatch_S2_F_Bumper_style_I.java:3-49 |
| 油漆/贴纸/内饰 | `IPaintjob:onInstall → Vehicle.PaintjobID`；`ISticker` 常量 `STK_FRONT=0, STK_SIDE=1, STK_REAR=2, STK_ROOF=3, STK_LICPLATE=21` | IPaintjob.java:43-51、ISticker.java:2-6 |
| prestige 倍率 | `stylPrestigeMul=0.25`、`perfPrestigeMul=0.35`（每车一套）；车本身 `getPrestige()=40` | IVehicle_Hatch_S2.java:2-3,7 |

### 6.5 兼容性规则（逐字位运算）

```java
// IVehicle.java:759  —— 赛道能否跑这台车：只看悬挂类别 4 位，轮胎位不参与
return (0 != ((this.trackFlags & Item.ITF_KINDOF_SUSP) & (local1 & Item.ITF_KINDOF_SUSP)));
// MapTrack.java:78
return local1.isCompatible(this.trackFlags);
```
`VCF_*` **不参与** `isCompatible`，只用于分组/显示（`getCategoryFlags()=trackFlags&(VCF_KINDOF_TERRAIN|VCF_KINDOF_GROUP)`，IVehicle.java:302；`getCarClass()` 切 `VCF_GR_S/A/B/C/D`，304-345）。
零件自适配：`IRims.makeCompatible`/`ITyres.installTyres` 按 `flags & ITF_KINDOF_TYRE` 选 0/1/2/3（OFFROAD/STREET/WINTER/TRACK），`IRunningGear.makeCompatible` 按 `ITF_KINDOF_SUSP` → `setupTo(0/1/2)`；**能否装到车上由 `part.getAttachOptions()`（槽数组）决定，不是位掩码**。

### 6.6 零件从哪来（✓ 我核对过的三条）

| 途径 | 逐字证据 |
|---|---|
| **默认库存件** | 载车时 `getDefaultItems()` 返回成对数组，循环 `addItem((id\|idx), {idx+1, 0, 0, 100, 1})`；Corus 清单 16 组：`{4096,-1, 2,0, 7,0, 37,0, 9,0, 6,0, 1,0, 4,0, 5,0, 10,0, 72,0, 73,0, 3,0, 19,0, 23,0, 64,0, 39,0}`（Model_Hatch_S2.java:236-238；基类返回空数组 Vehicle.java:721） |
| **赌注赢来的** | `Challenge.apply()`：`BET_TYPE_PerformPart/StylingPart → player.items.addItem(betPart.getId())`、`BET_TYPE_IVehicle → addItem(betIVehicle.getId())`（Challenge.java:49-76）；输车时 `dropItem` + `attachPreviousStage`（91-137）。可押目标＝`getStage()==getMaxPossibleStage()(±1)` 的非默认件（Player.java:123-178） |
| **作弊码（PDA 输 4 个 Tab 序号）** | `(0,8,4,5)`=全车辆、`(0,8,7,8)`=当前车全零件、`(0,8,1,9)`=宽体化（PDAPopup.java:229-287）；主菜单 `cheatButton/cheatButton2` 直接调 `giveAllParts()/giveAllCars()`（mainMenu.java:469-486） |
| **零件池生成** | `addAllPotentialParts()`：遍历 `getIPart(0..65535)`，只收 `isDefault()==0 && getName()!="<undefined>"` 的件（IVehicle.java:1315-1339） |
| ✗ 商店/赠予/试炼奖励 | UI 有 `$10|GIFT`/`$11|BUY`/`XPLabel`/"Locked Stage"，但 `SmallBuyPressed(23)`/`itemDropped(16)` **只有 post 没有 handler**；`Gamelogic.trialCompleted` 不发零件 → **读不到，不确定** |

### 6.7 零件的阶（`kind`）—— **已从 TUFA 指令流取回真值**（✓ 本轮闭环）

> 旧 §6.8 #1 记的是「重建器把 `super(kind)` 的立即数丢了 ⇒ `stage_I ⇒ kind=1` 只是推断」。
> 推断没错，但不用猜了：**该常量在 TUFA 指令流里好端端躺着**，直接读回来即可。
> 工具 `tools/part_kinds.py`，产物 `out_part_kinds.json`（逐类带证据）。

**指令形态（逐字，全类别一致）**：

```
LOCAL_LOAD 0                  ; this
INT LITERAL k                 ; ← 就是 kind
<其余实参：STRING LITERAL / FIELD_REF_STATIC / …>
INVOKESPECIAL java.game.item.<Base>.<init>(I…)
```

**判据（三条，缺一不可）**：
1. 调用目标是 `java.game.item.*` 的 `<init>`，且描述符**以 `(I` 开头**（kind 是第一个实参）；
2. 该调用的实参里**真的**有一个 int 字面量（不是「方法体里第一个 int 字面量」——
   这个更弱的判据会张冠李戴：`IF_Doors`/`IInterior`/`IPaintjob` 体内的 int 是数组长度/标志位，
   照那个判据会得出 kind=1/2 的假值）；
3. 值域 0..5。

**原厂件（`_stock`）不传 int** ⇒ 需沿构造器链**递归**到基类：`Hatch_S2_IHood_stock.<init>()`
只调 `IHood.<init>(Ljava.lang.String;)`，而后者体内正是

```
LOCAL_LOAD 0 ; INT LITERAL 0 ; LOCAL_LOAD 1 ; INVOKESPECIAL IHood.<init>(ILjava.lang.String;)
```

⇒ 原厂 = 0 **由基类构造器自证**（不是假设）。`IRims_stock` 走 `IRims.<init>([Ljava.lang.String;)`、
`ITransmission_stock` 走 `ITransmission.<init>()`，同理。共 **76 个**隐含值，全部为 0。

**装饰/非分阶件：构造器链上根本没有 int** ⇒ 无阶（不是 0）：
`IF_Doors`→`ISet.<init>()`、`IPaintjob`→`IPart.<init>()`、`IInterior`→`IPart.<init>()`、
`ISteeringWheel`→`(FLjava.lang.String;)` —— 共 102 类。

**语义坐实**（`java.game.item.IEngine`，其余 ``I*`` 同构）：`getStage()` 直接 `return kind`；
`getName()` 按 1..5 出 `"Engine - Stage I/II/III/IV/**Unique**"`（**5 不是 Stage V，是 Unique**）；
`getPriority()` 1..5 → `IPL_UPGRADE_STAGE_I..V`；`loadItemTextures()` 1..4 →
`engine_stage_1..4.png`（5 无图标）；`itemShowPriority = 0.1 * kind`。

**结果与对账**：

| 项 | 数 | 说明 |
|---|---|---|
| 有真值 | **973** | 897 显式 + 76 沿基类链自证 |
| 与名字推断**一致** | 732 | 旧推断被独立证实（含 `_WB ⇒ 5`） |
| 类名里没有阶（**新增信息**） | 240 | `IRims_style_*`、`ISticker_*` 等：**只有字节码能给出阶** |
| **冲突** | **1** | `Coupe_SD_T5_ISideskirts_stock`：类名 stock，字节码**显式 kind=1**（同车其余件与其它 6 车同类件都经基类链得 0）⇒ 疑原版复制粘贴漏改；效果：该件在零件池/车库按 Stage I 出现 |
| 非零件类（内层网格/外观） | 809 | 构造器不调 `java.game.item.*`（`F_Bumper_style_*`、`L_sideskirt_style_*`…）⇒ 不是可装配 item |
| 无阶（装饰件） | 102 | 见上 |

类别分布干净得像设计表（`out_part_kinds.json` 可查）：`IEngine/IMuffler/ITyres/IRims/IRunningGear/
ITransmission/IWeightReduction/IF_Bumper/IR_Bumper` = **10 车 × {0,1,2,3,4,5}**；`ISticker` = 40×{1..5}；
`IHood 10 车有原厂 / 8 车有分阶`、`ITrunkLid`、`IChassRWing` 只有轿跑有 —— 这些差异是**数据事实**（车型差异），
不是解析漏抓。

**重制侧落地**：`remaster/data/parts.json` 每行新增 `kind` / `kind_confidence` / `kind_source`（逐类证据）
/ `kind_note`（未取到的原因），`stage_index` 降级为「仅交叉校验」；`validate.py` 新增 4 项
（kind 逐类一致 / 值域 / 冲突仅 1 处 / 原厂 0 必须由基类链自证）。

复现：`python tools/part_kinds.py --json out_part_kinds.json --report`

### 6.8 未决项

1. `Item.ILF_*`/`ITEM_*`/`getXPGain` 不存在 ⇒ **"零件 XP 增益"这一概念无证据**。
2. ~~`Vehicle.STATS_THEORIC_MAX=1` 与 8 个 STATS 矛盾~~ → **✅ 已闭环（`docs/55 §2.1`）**：双路证明（`out_init.json` 字节码抬升值 + `Vehicle.<clinit>` 原始字面量流与字段序一一对应）⇒ **值就是 1，不是重建假象**。后果自洽：`IPart.<i>()` 的 `statChanges` 数组长度也是 1，Java 层加/卸零件只改 `statStates[0]`（DURABILITY）。
3. ~~`statChanges[]` 无写入方~~ → **✅ 已闭环（`docs/55 §1`）**：**原版就没有 8 项 stat 的写入路径**——零件的性能影响走 `onInstall()` 把物理参数推给车辆，由原生 info block 反映（`docs/55 §3`）。`statChanges` 只承载耐久增量（长度 1，全库无其他写入点）。
4. `ItemRoot.<i>()` 的 `lists` 字面量顺序可疑（伪码字面 `{extras,drivers,gamemodes,pets,maps,6}`，推得应为 `{vehicles,extras,drivers,gamemodes,pets,maps}`）⇒ 须以 `addItem` 的 `lists[primary-1]` 为准。
5. ~~`ITEMSLOT_*(0-64)` ↔ 物理槽号映射只知片段~~ → **✅ 已闭环（`docs/55 §4`）**：`Vehicle.fillSLUT` **字节码**重建出完整 65 组 / 72 个 `SlotMap`（伪码版少 3 个），工具 `tools/stat_slots.py`，全表见 `docs/55 §4.2`；另抽出 24 个零件基类的 `attach`（零件族 → ITEMSLOT）✓。
6. `INitrous.gain/minRPMmul`、`IRunningGear` 的非 stock 数值、`int[] params` 的 `[1][2][3]` 语义、`IExtra` 消耗品逻辑 —— 均读不到。

---

## 7. 地图 / 赛道类的字段语义与引擎消费路径

> 证据：`out_pseudo/java/classes/game/MapTrack.java`、`Map.java`、`GroundRef.java`、`ComplexSpline.java`、`Trigger.java` + 各调用点。
> 原始带行号材料存档：`docs/annex/50B_maptrack_raw.md`。

### 7.1 先纠一个拆分错误（重制建模必须按这个来）

| 类 | 父类 | 管什么 |
|---|---|---|
| `java.game.Map`（地图） | `java.util.resource.GroundRef` | `todNames / previewFiles / customObjects / banners / blimpCamPos / timeLimit / totalSpeedTraps / winningSceneLocation / trackFlags(VCF) / sfx` + **spline 槽** |
| `java.game.MapTrack`（赛道） | `java.lang.Object` | `name / difficulty / direction / roadCondition / overallLength / officialBestLap / spline[] / complexspline / splineNames / startGrid / checkpoints / trackFlags(ITF) / visualisationBounds / iconsTyresAndSuspensions / uv*` |
| `maps.<图>.<图>`（图类） | `Map` | 一图一份：雾/水/天穹/cubemap/阴影/envmap + `soundSetup()` + 手摆的 Trigger |
| `maps.<图>.<图>_track_N`（赛道类） | `MapTrack` | 一赛道一份：检查点/发车位/spline 文件名/路线预览图/可视化边界 |

`todNames / banners / timeLimit` 这些**不在** `MapTrack` 里（`out_fields.json` 的 `MapTrack` 26 字段中无此名，`Map` 里才有）。

### 7.2 `MapTrack` 逐字段：值 + 谁读（Boulevard 实测）

| 字段 | 类里写的值 | 谁读 |
|---|---|---|
| `name` | `"$1|Ventura Bvd"`（Boulevard_track_0.java:32） | `GameMode.java:708`（救援日志）、`ReplayInfo.java:18` |
| `difficulty` | `2`（:33） | **无 Java 读取点**（`getDifficultyLevel` MapTrack.java:32 定义未用）→ 原生/UI 不确定 |
| `direction` | `1`（:34） | **无读取点** → 不确定 |
| `overallLength` | `5629.0`（:35） | **无读取点**；与真长度无关（见 §5） |
| `roadCondition` | `"100% asphalt"`（:36） | **无读取点** → 不确定 |
| `officialBestLap` | `0.0`（:37） | **无读取点**；单场最好圈走 `GmRace.bestLapTime` |
| `trackFlags` | `ITF_STREET_SUSP\|ITF_STREET_TYRE`（:38）= **34** | `MapTrack.isCompatible:78`；轮胎/悬挂类型文本 (`:84,102,120,138,154,170`)；`Map.getTrackFlags → Gamelogic.java:998 item.makeCompatible(...)` |
| `spline[]` | `{maps/Boulevard/Track_00_rescue.spl2, …_shortcut.spl2}`（:24-25） | `Map.prepareTrack` 逐槽装载（Map.java:182-183）；Bot 兜底 `GameMode.java:593`、`GmRace.java:223,297,998,1497` |
| `complexspline` | 4 条 AI 线 + 4 组参数（:26-31） | 仅 `GmRace.java:222,225,296,299`（SINGLE 挑战者 bot） |
| `splineNames[]` | **从未赋值** | 仅 `Replay.java:119-125` 对 `<图>_freeride_0` 读；本版无该类 → 恒 null |
| `startGrid` | `Pori[8]`，两列 4 排，`y` 全 `0.0`、朝向 `1.38058`（:41-42） | `GameMode.java:457,465`、`GmRace.java:58-59,1438`、`Track.java:384` |
| `checkpoints` | `CheckPoint[6]`，尺寸多为 `(25,7.5,0.25)`，第 6 个 `(36.5,7.5,0.25)`（:39-40） | `GmRace.java:75`（逐条建 Trigger）、`GmTrial.java:53-54` |
| `visualisationBounds` | 每图不同（Boulevard `(-756.5,-10,-467.7)→(492.5,-10,213.2)`，:14,18） | `Navigator.java:48-50`（小地图缩放） |
| `routePreviewTexture` | `Texture("maps\\boulevard\\routes\\00.tga")`、`545×297`（:2,5,8） | `Navigator.java:51-52,63,87,246-247,269-270` |
| `getStartPoint()` | `Pori((-186.223,7.5,36.5715), ypr(1.38711,0,0))`（:21） | `Navigator.java:29`（起点图标） |
| `mapper`(static int[32]) | `MapTrack.java:4` | **零调用点**（`getRoadComponentMapping` 无人用）→ 不确定 |

### 7.3 spline 槽号语义（重制必须照做）

- 槽表是原生 `GroundRef` 的定长数组，`GroundRef.MAX_SPLINES = 32`（GroundRef.java:8），**槽号就是 `loadSpline` 的入参/返回值**。
- 装载：`Map.prepareTrack(MapTrack m, int tod)` 先 `clearSpline()`，再 `for(i<m.spline.length) loadSpline(i, m.spline[i])`（Map.java:180-185）——**按顺序占 0,1,2…**。
- **槽 0 = 主行驶线**：`getSplineLength(0)` 当赛道总长（GmRace.java:74、GmTrial.java:51）、`getSplineVal(0,pos)` 当进度参数（GmRace.java:409）。
  槽 0 的文件名因图而异（Boulevard/Business/Coastline/Suburban = `*_rescue.spl2`，Harbor/Highway/Hills/Industrial/Observatory = `*_slow.spl2`），**与磁盘上实际存在的文件严格对应** ✓（我的 `out_map_tracks.json` 已逐文件核对存在性）。
- **槽 31 = 赛前镜头专用**：`GameMode.java:480 pr_spline = map.loadSpline(31, "frontend/gamemode/PreRaceCamera_2.spl2")`，用完 `clearSpline(31)`（:555,651）；与 `clearSpline()` 只清 `0..30`（GroundRef.java:12-16）吻合。
- 原生 API 真签名（`out_native_methods.json`）：`loadSpline(I,String)I`、`getSplineLength(I)F`、`getSplineVal(I,Vector3)F`、`getSplinePos(I,F,F)Vector3`、`getSplineDir(I,F)Vector3`、`getSplinePerp(I,Vector3)F`、`getSplineWidth(I,F,F)F`、`getNearestSpline(Vector3)I` / `(Vector3,II)I`、`transformSpline(I,Vector3,Ypr,F)V`。
- 语义要点：`getSplineVal` 返回的是**沿线的弧长（米）**，不是 0..1 归一值 —— `GameMode.java:716-720` 用 `getSplineLength` 做环绕；`GmTrial.java:42` 拿它 `+6.0` 米做前瞻点。失败信号：`getNearestSpline<0`、`getSplineLength<0`。
- `loadSpline(-1,file)` = 自动挑空槽（`PubWindow.java:272-281`，判失败用 `>=MAX_SPLINES-4`(28)）。

### 7.4 `ComplexSpline` 构造 5 参数（= AI 备用线定义）

| 位置 | 参数 | 语义 | Boulevard 值 |
|---|---|---|---|
| 1 | `String[] splineFile` | AI 备用线文件名 | `{_normal, _slow, _fast, _shortcut}` ✓（与我的 `out_map_tracks.json` 完全一致） |
| 2 | `float[] CUmin` | catch-up 区间下界 | `{-0.4, -1.0, 0.2, 1.0}` |
| 3 | `float[] CUmax` | catch-up 区间上界 | `{0.4, -0.2, 1.0, -1.0}`（第 4 条区间倒置） |
| 4 | `float[] botCUpars` | 4 个标量 → `AI_SetCatchUpSpline` | `{60.0, 110.0, 50.0, 100.0}` |
| 5 | `float[] botSCpars` | 6 个标量 → `AI_SetShortCut` | `{10.0, 40.0, 30.0, 99999.0, 0.35, 1.0}` |

消费（全库仅 4 处）：`GmRace.java:222-226` / `296-300` → `ComplexSpline.applyOnBot(bot)`（ComplexSpline.java:17-34）：`beStupid()`(=AI_suspend) → 逐条 `AI_RaceSplineMore <CUmin> <CUmax> <file>` → `activateRaceSpline(0)` → `AI_SetCatchUpSpline …` → `AI_SetShortCut …` → `AI_maxspeed -1.0`。

### 7.5 `Trigger`：构造参数与三种场景物怎么分

- `Trigger extends java.util.resource.GameRef`（可直接当通知源）。子类/实例命名由**构造的第 1 个 String** 决定；**回调方法名是另一个 String**（在 `addTrigger` 的第 6 参）。
- **盒子主构造（5 参，唯一有实现体的）**：`(GameRef 父, Vector3 位置, Ypr 朝向, Vector3 尺寸, String 名字)`（Trigger.java:18），原生描述串 = `"px,py,pz,oy,op,or,box,sx,sy,sz"`。
- **7 参盒子** `(父, 位置, 朝向, 尺寸x, 尺寸y, 尺寸z, 名字)`（Trigger.java:11-12）＝委托给 5 参版（伪码空体，属重建丢失；形参序由字节码确认）。
- **4 参球体** `(父, 位置, float 半径, 名字)`，串 = `"x,y,z,0,0,0,sphere,<半径>"`（Trigger.java:8）。
- `Config.showTriggers` 为真时建可视化 `ins`（`RenderType("frontend.rpk",260)`，Trigger.java:2-4,19-26）。
- **三种场景物的区分（关键）**：
  1. **banner（图里唯一由地图类创建的 Trigger）** = 救援/边界盒。`GameMode.java:355-364` 对 `map.banners` 每条注册 `addNotification(trigger, ON|OFF, SAME, null, "handleBannerTrigger")`，处理器只做一件事：**若驶入者就是本地玩家车 → `respawn()`**（GameMode.java:417-422）。Boulevard 实测 **49 个**，命名 `Box01..Box49`，尺寸多为 `(14.578,12.5,15.152)`，另有两个巨箱 `(565.779,12.5,15.14)` 夹住发车区 —— **我的提取数据与子代理独立结论完全一致** ✓。
  2. **checkpoint** = **地图文件里没有**，`GmRace.point()`/`GmTrial.point()` 在比赛期用 `MapTrack.checkpoints[k].size` 现场建 Trigger，名 `"checkpoint_trigger"`、回调 `"event_handlerTrigger"`（GmRace.java:405-411）。
  3. **救援点** = **不是 Trigger**，完全是 spline 逻辑：`GameMode.respawn()` 用 `getNearestSpline→getSplineVal/Perp/Width/Dir/Pos` 找可行点并按 `rescueCounter` 逐级换横向候选（GameMode.java:691-814）。

### 7.6 昼夜/季节（`todNames`）——**语义在、切换实现读不到**

- `todNames` 长度 **12**（字节码 `NEWARRAY 12` 确认），10 张正式图**共用同一份**：`$1|Spring Daytime`、`$2|Spring Morning`、`$3|Spring Sunset` … `$12|Winter Sunset`（Boulevard.java:21-22，`test` 图是 `{"Lucky Day"}`）。
- 索引传递链：房间参数 `ROOM_PARAM_timeofday(=35)`，−1 时改用 `ROOM_PARAM_randomTOD(=46)`（MetaServer.java:160,173）→ `Track.java:269-272` → `this.map.prepareTrack(mtr, tod)`（Track.java:274）；回放走 `replay.TOD`（Track.java:2413）。读 `todNames` 的 UI：`getTODName/getTODPreview/validateTodIndex` ← `ReplayInfo.java:16-20`、`Loading.java:149-150`。
- ✗ **反证**：`Map.prepareTrack(MapTrack,int)` 的 TOD int **一次都没被读**（Map.java:179-197 无 `slot1` 的 `LOCAL_LOAD`，字节码核对一致），所有图的光照/雾/天穹都是**每图写死一套**（Boulevard.java:189-209 `setFog(0,1350,10000,0,0,0.027,0)`、`setGlobalCubemap`、`skydome[5]`…）。另外 `previewFiles` 长度只有 **1**（`maps\boulevard\2.dds`）而 `todNames` 长度 12 → `validateTodIndex(i>0)` 会越界（守卫用的是 `todNames.length`，Map.java:158），目录里每图也确实只有一张预览 dds。
- ⇒ 重制建议：**保留 12 项 TOD 名称与索引语义，预览只实现 index 0**；真切换机制需原生层或实机验证。

### 7.7 `startGrid` 发车分配

`Gamelogic.startOrder = new int[8]`（Gamelogic.java:45）：
- 单机：`{0..7}` 洗牌后整表拷贝（Gamelogic.java:945-961，日志 `"startorder - SINGLE -> megkeverem"`）；`runMode==SINGLE` 时也可以直接 `startOrder[i]=i`（:613-617）。
- 联机：房主 `generateStartOrder()` 随机 1..8 不重复打包成十进制（:1256-1272）；收到 `ROOM_PARAM_STARTORDER` 按位拆 `startOrder[k] = (v%10)-1`（:606-610）；`NormalizeStartOrder()`（:1021-1047）。
- 取格：本地玩家 `startGrid[startOrder[localUserSlot]]`（GmRace.java:58-59，用于 Track.java:314）；**AI 用 `startOrder[getMetaLevel()-32]`**（Track.java:383-384）；单机挑战者 `startOrder[localUserSlot+1]`（GmRace.java:1438）。
- **方向判定基准**：`calcForwardSplineVal()` 用 `startGrid[0]` 与其后退 1 米两点的 `getSplineVal(0,·)` 比较得出 `forwardSplineVal=±1`（GameMode.java:455-477），用于救援/碰撞回退判前后。

### 7.8 生命周期（进图 → 退图 的真实顺序）

`Track.enter()`：`map.load()`（:255）→ `map.prepareTrack(mtr, tod)`（:274，内部 `clearSpline → loadSpline×N → customObjects/banners 重建 → GfxEngine 复位 → Sound.initReverb/initRooms(0)/initGeometries`）→ 图类自己的 `prepareTrack` 末尾调 `MapTrack.prepareTrack(map)`（建 `customObjects` 灯光拱门，如 Boulevard.java:262）→ `Navigator.init`（:276-284）→ `gameMode.initGameMode`（:293）→ `calcForwardSplineVal()`（:313）→ 玩家摆到 `startGrid[startOrder[localUserSlot]]`（:314）→ Bots 摆位（:384）→ `gameMode.startScene()`（:392，内部用 spline 槽 31 放赛前镜头）→ 加载条消失后 `startSoundAndMusic()`（:413，图类在此 `changeMusicSet(MUSIC_SET_MAIN)` + `addSfx(citynoise)`）→ `Track.run()` 主循环（每帧 `playRandomSound(elapsed)`，:656/:687）→ 退图 `Track.exit()` → `map.leaveTrack(mtr)`（:634，内部销毁 customObjects/banners/skydome/sun、停 sfx、`GfxEngine.leavetrack()`）。
车库/pub 侧另走一套：`PubWindow.java:290 pubi.map.prepareTrack(null,0)` 只装 spline 不放赛道对象；`PubWindow.java:219 map.leaveTrack()` 隐藏 3D 视图时清理。`soundOptions.java:250` 在改音频选项后重调 `map.soundSetup()`。

### 7.9 未决项

1. `getOverallLength/getRoadCondition/getDifficulty*/getDirection/getOfficialBestLap/getRoadComponentMapping/getTyreType*/getSuspensionType*/getVisualisation/blimpPos/getTimeLimit/getTotalSpeedTraps` **在 Java 伪码层零读取点** → 可能由原生/UI 按名调用，**一律标不确定，不要当废弃字段删掉**。
2. Trigger 8 参构造（第 4 个 Vector3 = 中心偏移 + 3 个 float = 尺寸）未逐字确认；`Trigger.java:11-15` 是空体。
3. `GameMode.handleBannerTrigger` 只做 `respawn()`，`bannerCnt` 置 0 后再无使用 → banner 是否还承载计数/一次性逻辑、是否与美术"横幅"有关，均无证据。
4. 32 人房发车位（`GameMode.Racers[32]` vs `startGrid[8]`）如何处理未知。
5. `Map.info / suntype / rt_particles / gatePsColor` 无初始化/读取点（疑似重建丢失）。
6. `Test` 图引用发货包里**不存在**的 `maps/Tokyo.rpk`（`test` 图类），属开发期残留。

---

## 8. 音频环境 / 音乐 / 文本与本地化

> 证据：`Sound.java`、`SfxRef.java`、`Config.java`、`Smiley.java`、各图 `soundSetup()`、`C:\Games\LASR\{formats.als,locale\,sound.rpk,spritecfg.smt,ds.cfg}`。
> 原始材料存档：`docs/annex/50C_audio_text_raw.md`。常量与文件统计已由我回读核对 ✓。

### 8.1 音乐集（全表只有 4 个 + 7 个通道）

```
Sound.java:2  MUSIC_SET_NONE   = -1      6  CHANNEL_EFFECTS     = 0
Sound.java:3  MUSIC_SET_MAIN   =  0      7  CHANNEL_MUSIC       = 1
Sound.java:4  MUSIC_SET_INGAME =  1      8  CHANNEL_ENGINE      = 2
Sound.java:5  MUSIC_SET_CREDITS=  2      9  GEARBOX=3 / 10 ENVIRONMENT=4 / 11 SPEECH=5 / 12 GUIEFFECTS=6
```

- **没有"每套音乐集一份曲目列表"**：全工程只有一次 `Sound.addMusicSet("music")`（Init.java:34），`music/` 下 13 个 `.ogg` 属**同一个池**（`01. Burn` … `12. Melrose Nights` + `14. StreetParty`，**13 号缺失**）。选曲靠文件名：`Sound.findTrack(String)` / `setTrack(int)` / `nextTrack()` / `prevTrack()`。
- 切换点：`GameIntro.java:139`(MAIN)、`mainMenu.java:145`(NONE)/`:660`(MAIN)、`Gamelogic.java:1080/1088`(MAIN)/`:1092`(PUB→NONE)、**`Track.java:2444`(INGAME，赛道加载完成时)**、`PubWindow.java:113`、`creditsWindow.java:27`(`findTrack("14")`)、`Init.java:113/116`(热键换曲)、**10 张图的 `startSoundAndMusic()` 全部 `changeMusicSet(MUSIC_SET_MAIN)`**（Boulevard.java:182 等）。
- ✗ `MUSIC_SET_CREDITS(2)` **Java 侧零引用**（与 docs/42 §2.5 一致）。

### 8.2 房间/混响盒（音频环境数据）

原生签名（exe 3052376-3053168 字符串表 + 反汇编双向确认）：`addRoomBox(IIFFF)I`、`roomSetPosition(IFFF)V`、`roomSetOrientation(IFFF)V`、`addReverbBox(FFFF)I`、`reverbSetPosition/reverbSetOrientation(IFFF)V`、`initRooms(I)I`、`initReverb()`、`addGeometry(String)`、`initGeometries()`。同族另有 8 个 Java 未用的原生方法（`addRoomSphere/Capsule/Cylinder`、`addReverbSphere/Capsule/Cylinder`、`roomRemove`、`reverbRemove`）。

每图 `soundSetup()` 一律同构（Boulevard.java:27-…)：

```java
Sound.initRooms(0);
if (Config.sound_latereverb)  { addRoomBox(...)   + roomSetPosition + roomSetOrientation }   // 晚反射
Sound.initReverb();
if (Config.sound_earlyreverb) { addReverbBox(...) + reverbSetPosition + reverbSetOrientation } // 早反射
```
⇒ **`sound_latereverb` 管 room box 族，`sound_earlyreverb` 管 reverb box 族**；`sound_occlusion` 只被 Highway 用（`Highway.java:252-255 addGeometry("maps/highway/fmod.geo")`）。三个开关默认全 `false`（Config.java:64-66），存于 `save\game\options`（魔数 −19088744、版本 37，Config.java:139-141）；选项 UI 四档映射 OFF/LOW/MEDIUM/HIGH（soundOptions.java:155-180，OFF=全关、LOW=只 latency、MEDIUM=+occlusion、HIGH=+early）。

**实测统计（全 15 图，我按子代理数据复核过数量级）**：共 **89 room box + 374 reverb box**。

| 图 | room | reverb | 图 | room | reverb |
|---|---|---|---|---|---|
| boulevard | 3 | 45 | industrial | **0** | **85** |
| business | 11 | 26 | observatory | 1 | 41 |
| coastline | **40** | **0** | suburban | 0 | 3 |
| harbor | 1 | 47 | urban | 7 | 35 |
| highway | 16 | 57 | 4 张 `_b` + test | 0 | 0 |
| hills | 10 | 35 | | | |

- 参数规律：`addRoomBox` 第 1 个 int ∈ {8,15}、第 2 个 int 恒 1、第 4 个 float **恒等于随后 `*SetPosition` 的 Y**；`addReverbBox` 第 4 个 float **恒 1.0**；返回的 int 是句柄。
- 坐标 = 与 Trigger 同一世界坐标，单位米；Y 恒等于该处地面高度（Boulevard 全图 5.93498；Highway 4.5 / 15.0 两档）；角度是**弧度**（取值 0.0873/0.6109/1.5708… = 5°/35°/90° 整倍）。
- room 盒少而大（15×…×212 房间级）、reverb 盒多而小（尺寸中位数 **1.081**，Highway 里 6 个 1.0809³ 小盒沿路排布）。
- 异常：`coastline` 40 room / 0 reverb，`industrial` 0 room / 85 reverb（半成品状态）。
- ⚠ 各 float 究竟是"全尺寸还是半尺寸"（AABB ±half 还是 [0,size]）**未定**，建模时先按全尺寸并在实机对比混响范围。

### 8.3 音效引用与 `.rpk` 寻址

```
SfxRef.java:2  SFX_3D = 0    SfxRef.java:3  SFX_2D = 1（1<<0）
SfxRef.java:4  SFX_LOOPED = 2（1<<1）        SfxRef.java:5  SFX_STREAMED = 4（1<<2）
SfxRef.java:6  SFX_ROOT = new ResourceRef("system.rpk", 9)
```
- `ResourceRef(archive, N)` 的 `N` = 该 `.rpk` **明文清单里的条目序号**；本轮确证 `res_mesh=7 / res_texture=8 / **res_sound=9** / res_force_fx=10`（`C:\Games\LASR\system.rpk`，1532 B，`RPAK` + `u32 index_size=0x200`），所以 `SFX_ROOT` 就是"挂在 system.rpk 第 9 号 res_sound 族下"。
- 子资源 = `createFromFile(SFX_ROOT, "frontend/sounds/suburb/cityloop.wav", flags)`（SfxRef.java:16-27）；语音目录扫描特例见 SfxRef.java:24-34。
- **素材是散装文件**，`.rpk` 只是清单：`sounds\`（17 个 `.fsb`/`.wav` + `sounds.fev`）、`frontend\sounds\`（21 个）、`music\*.ogg`。
- `sound.rpk`（13,499 B）= **音效事件清单**，131 条 `(名, 偏移, 大小, 类型)`；含 `collision`、`chassis`、`metalhits`、`tirehits`、`treehits`、`utkozes`×4、`window`、`damage`、`brake/cooler/engine/exhaust/shock/tire`、`map_sfx/animals/beesloop/crow01..03/deer`、`boathorn/citylife/beach01..04loop/folyo01..04loop/icewind01..03loop/mennydorges/quake01..02/wind*loop`、`speech/accident/back_on_track/checkpoint_missed/get_back_on_track/overtaken/wrong_way/netchatroot`、`surface/air/tire/water`、`vehicles/backfire/engine/ignition/horn/nitro/transmission/breaking/gear_up/gear_dn/turbo_BOV/turbo_WG/turbo_whistle`（多为匈牙利语命名）。

### 8.4 对手台词（Bottalk）：文案在**伪码常量表**里

- **`#Bottalk.text_b#` 不是台词，是样式令牌**，指向 `C:\Games\LASR\formats.als:158 Bottalk.text_b = #acenter# {char #larger# #black#}`（:157 text_w、:160 text），用在酒吧搭话气泡 Label 的 `Format` 属性上（`out_ui_layouts.json` 的 `PubWindow/saySomething`）✓。
- **真正台词 = `Gamelogic.botTalks`**：`Gamelogic.java:1605-1712` 共 **108 条**（我实数过 ✓），下标 `[BOTTALK_*][prestigeFactor][cheatFactor][aggressionFactor]`，四类 = `BOTTALK_REJECT(0)/GOSSIP(1)/TEASER(2)/BOAST(3)`（Bot.java:2-6，`OFFER(4)` 无台词走弹窗）。逐字样例：
  ```
  1605  "$1|Don't be scared little weakling, I don't wanna destroy your confidence. Now, get lost!"
  1606  "$2|I don't talk to toddlers. Go practice instead of pretending to be Mr. Cool Guy. Bye, buster!"
  1614  "$10|Hey Mr. Honest! If you leave those principles behind you learned in school maybe I will race you."
  ```
  取值：`Bot.whatDoYouSay(I)`（Bot.java:203-248）先算 `prestigeFactor`（按最近一场 `RaceChronicle` 输赢，0..2）→ 查表 → REJECT/GOSSIP/TEASER 做"最近两次不重复"去重（lastBotTalk1/2）；另有 2 条内联字符串（Bot.java:210,213）和兜底 `"$3|I don't feel like talking. Buzz off, joker!"`（:248）。调用链：`PubWindow.java:536 → botTalkPopup.botSays()`（:64-65,79）。
- `#tebarat` / `#obarat` 等也不是文本，而是 **`java.gui.Smiley` 的表情图元令牌**（`Smiley.tex = "gui\\textures\\smileys-trans.png"`，共 23 个令牌含 `#tebarat #obarat #barat #verseny #kiraly #zart #nyitott #meno #bohoc …`），用点：`PDAPopup.java:438-444`（难度星级）、`ProgrBarComponent.java:139-148,169`、`PubWindow.java:250-259`。
- ⚠ **内联默认文案 ≠ 发行版 locale 文案**（`locale\lasr.en` 的 `[java.game.Gamelogic]` 1-9 号与伪码不一致，10 号以后一致；`[java.game.Bot]` 3 号也不同）⇒ 两者来自不同代码版本，**运行时用哪份未定**。

### 8.5 文本与本地化资源清单（重制时的完整对照）

| 路径 | 规模 | 格式 / 用途 |
|---|---|---|
| `locale\lasr.en` | 32,467 B，**75 段 / 940 键** ✓ | 主字符串表。UTF-8 带 BOM、CRLF，段名 = `[类全限定名]`，条目 `N="文本"`（`N` 就是 `$N|` 的键）。**445 条 UI 文本的译文宿主** |
| `locale\LASR.de/fr/it/sp` | 35.5/36.5/33.9/36.4 KB，940 键 | 同格式 |
| `locale\.conf` | **2 B**，内容 `en` | 语言选择（Config.java:298-302） |
| `formats.als` | 6,451 B / **183 行** | ★ **UI 样式表**：`名 = 值`，值由 `#其它样式#`、`{char #字体# #颜色#}`、`font("arial",10)`、`bfont("bfont0",20)`、`ecol(FF000000)`、`aspc(center)` 拼成；`#样式名#` 的宿主（实例：`:1 black`、`:9 smallest`、`:18 WindowHeader`、`:128 HUD.text`、`:158 Bottalk.text_b`、`:183 Console`） |
| `spritecfg.smt` | 1,380 B | 精灵配置（文本，含字段注释 `name flags texture.rpk texture.id color distance offset upvector scaleH scaleV uv[2][2]` + `SPRMF_*` 位标志），9 行玩家名牌 `player1_tag..`，占位纹理 `nincsilyen.rpk`（="没有此文件"） |
| `ds.cfg` | 234 B | 专用服务器配置（`mgs=…:443`、`port=12346`、`servertype=1`、`map=1`、`laps=1`、`twaitforuser=15`…） |
| `frontend\` | `gamemode/garage/meshes/sounds/textures` | 本地化图 `textures/{en,de,fr,it,sp}/` + `faces/ items/ noise/ format/ paintjob_formatters/ specdecals/` |
| `frontend\sounds\` | 21 文件 | `frontend.fev` + 6 `.fsb` + UI `.wav`；子目录 = 环境音族（`harbor/ highway/ shops/ suburb/`） |
| `readme\`、`Manual.pdf` | 5×2 文件；707 KB / 14 页 | 安装文档 + 手册（**PDF 无文本层，需 OCR，未读**） |
| `$N|` 文本的完整清单 | 445 条 | 已在 `out_ui_texts.json`（docs/49 §4）；**54 个含 stringTable 的类中 21 个在 locale 里没有对应段**（多为在局 HUD 组件如 `HUD_Standard`、`LeftWheel`、`CarTabListComponent`）⇒ 这些文案只有伪码常量、无翻译出口 |

### 8.6 未决项

1. `initReverb/initGeometries` 返回类型冲突（反汇编 `()` vs 成员表 `()I`）。
2. room/reverb box 各 float 的"全尺寸 or 半尺寸"、`addRoomBox` 两个 int 与 `addReverbBox` 第 4 个 float 的确切语义未定。
3. 朝向三分量顺序（实测只用第 2 分量，其余 165/165 全 0）未证。
4. `MUSIC_SET_*` → 具体曲目的分组规则在原生侧，未定位。
5. 内联 `$N|` 与 `locale` 文件谁优先未定。
6. `setTOD` 类原生接口未找到（见 §7.6）。

---

## 9. 数据层未决项汇总（重制前必须落地或决策）

| # | 未决项 | 影响面 | 建议路径 |
|---|---|---|---|
| 1 | **`overallLength/difficulty/timeLimit/roadCondition/VisualisationBounds(地图类) 等字段全图同值** | 数值/UI | 已判定模板残留 ✓；长度改从 `.spl2` 算（§5） |
| 2 | **TOD 真正切换机制缺失**（`prepareTrack` 的 int 未使用，光照按图写死） | 昼夜/季节玩法 | 保留 12 项名称索引；切换需原生层或实机验证 |
| 3 | ~~`Vehicle.STATS_THEORIC_MAX=1` 与 8 个 STATS 矛盾~~ → **✅ 已闭环（`docs/55 §2.1`）**：字节码真值就是 1（双路证明），后果 = 零件在 Java 层只改耐久；性能改动的真路径 = `onInstall()` 推物理参数 → 原生 info block | 零件性能增益 / UI | 已落地（重制侧 `stats.json` 带 8 项映射）|
| 4 | ~~`statChanges[]` 无写入方~~ → **✅ 已闭环（`docs/55 §1`）**：原版**没有** 8 项 stat 写入路径（数组长度 1 = THEORIC_MAX），无需追 native | 同上 | 已落地 |
| 5 | **商店/赠予/试炼奖励无落地点**（事件 16/23 无 handler、`trialCompleted` 不发件） | 生涯经济 | 与「钱不存在」结论一致：重制需自定经济 |
| 6 | **32 人房发车位**（`startOrder[8]` vs `Racers[32]`） | 联机 | 实机或原生层 |
| 7d | ~~材质表 id↔名 配对错位~~ → **✅ 已解（`docs/57 §8`）**：三重证据（逐字节 / OBJ 包围盒 / 偏移扫描 k=+0 最优）证明**变体 1–4 配对正确**；**变体 5/6（WB）整体平移一件**（链条实证），按「族 + `_5`/`_6` + id 最近」重绑 73 件全有解；stock 件引用车体网格属原版设计 | 装配/渲染数据 | 已落地（`data/mesh_id_map.json`，6 项校验）|
| 7c | ~~零件外观（网格/贴图）从哪来~~ → **✅ 已闭环（`docs/57`）**：`configureMesh(ResourceRef(车包,id))` + `configureVisual` + 3 张贴图 + `PartDecal`；45 种 `configureType` 键成词表；**按 id 取网格**（材质表 id↔名有系统性错位 ✗） | 装配系统可视化 | 已落地（`data/mesh_assembly.json`，6 项校验）|
| 7b | ~~物理槽「几何位置从哪来」~~ → **✅ 已闭环（`docs/56`）**：位姿来自 `configureType("slot\t\t<pos>\t\t<rot>\t\t<id>")` 字面量；车 Model 声明骨架槽 + 默认件，**造型件由零件类自带位姿**；纯参数件 `configureType` 调用数为 0 ⇒ 12 逻辑槽；游戏未出货 19 死槽 | 装配系统可视化 | 已落地（`data/slot_geometry.json`，7 项校验）|
| 7 | ~~`ITEMSLOT_*(0-64)` ↔ 物理槽号映射只知片段~~ → **✅ 已闭环（`docs/55 §4`）**：`Vehicle.fillSLUT` 字节码重建 65 组 / 72 个 `SlotMap` + 24 个基类 `attach`；工具 `tools/stat_slots.py` | 装配系统 | 已落地（重制侧 `stats.json` → `slots`，12 项校验）|
| 8 | ~~具体零件 `kind`（阶）常量被重建吞掉~~ → **✅ 已闭环（§6.7）**：真值从 TUFA 构造器链读回（973 类，工具 `tools/part_kinds.py`，逐类证据在 `out_part_kinds.json`）；与名字推断 732 一致 / 240 新增 / 仅 1 处原版数据不一致 | 零件数据全表 | 已落地（重制侧 `parts.json` 带 `kind` + 4 项校验） |
| 9 | **在局 HUD 类 21 个无 locale 段** | 本地化 | 重制时补建字符串表 |
| 10 | **`Manual.pdf` 未读**（无文本层） | 玩法细节 | 需要 OCR 时再处理 |
| 11 | **`Test` 图引用不存在的 `maps/Tokyo.rpk`** | 无（开发残留） | 忽略 |

---

### 附：数据层产出清单

| 文件 | 内容 |
|---|---|
| `docs/50_DATA_LAYER.md` | 本文（§0-§5 地图数据、§6 零件、§7 赛道语义、§8 音频/文本、§9 未决） |
| `out_map_data.json` (510 KB) | 15 图 / 28 类的**全字段 + 全调用**原始提取 |
| `out_map_tracks.json` | 干净版：15 图 / 82 检查点 / 606 banner / 463 声学盒（全带坐标）+ spline 文件与实测长度 + 可视化边界 |
| `tools/map_data.py` | 提取器（`python tools/map_data.py --export`） |
| `tools/part_kinds.py` + `out_part_kinds.json` | **零件阶（kind）真值提取器**（TUFA 构造器链）+ 逐类证据（973 类 / 911 未命中带原因）（§6.7） |
| `tools/stat_slots.py` + `out_stats_spec.json` | **性能 stat 链 + 槽位系统提取器**（字节码常量 / `fillSLUT` 重建 65 组槽位表 / 滑块量程 / 24 个基类 `attach`）→ 详见 `docs/55_STATS_AND_SLOTS.md` |
| `tools/mesh_id_map.py` + `out_mesh_id_map.json` | **车包资源 id 映射表**（目录记录流 → id/类型/名字/偏移 + 导出 OBJ 包围盒几何标签 + 零件引用归因 + **WB 区错位重绑**，三重证据定案）→ 详见 `docs/57_MESH_ASSEMBLY.md §8` |
| `tools/mesh_assembly.py` + `out_mesh_assembly.json` | **车身网格装配链提取器**（`configureMesh`/`configureVisual`/`configureTexture`/贴花 + 45 种 `configureType` 键词表）→ 详见 `docs/57_MESH_ASSEMBLY.md` |
| `tools/slot_geometry.py` + `out_slot_geometry.json` | **零件槽几何来源普查器**（691 个类的 `configureType("slot … <id>")` 逐行解析 / 骨架槽 vs 零件自带位姿 / 无几何槽三分类）→ 详见 `docs/56_SLOT_GEOMETRY.md` |
| `docs/annex/50A_items_raw.md` | 零件系统原始证据（带行号，38,957 B） |
| `docs/annex/50B_maptrack_raw.md` | 赛道字段语义原始证据（36,058 B） |
| `docs/annex/50C_audio_text_raw.md` | 音频/音乐/文本原始证据（38,092 B） |
