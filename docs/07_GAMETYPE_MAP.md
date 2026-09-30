# P3.7 —— `gametype` → 物件名 映射表

> 状态：**已解并全量导出**。32 个 gametype 拿到高置信度名字，19 个判定为「通用容器」。

## 1. 怎么拿到名字的

关键线索：在每个 `RSD` 块**之前**，有一段二进制物体记录，标记是 `58 00 00 00`：

```
f32 1.0f | u32 ? | 58 00 00 00 | u8 nameLen | name\0 | f32 ×6 (位置+旋转)
```

实例（`maps/coastline.rpk` @`0xb59b`）：

```
00 00 80 3f | 85 b6 00 00 | 58 00 00 00 | 0a | "side_lamp\0" | 3b 36 0d 44 …
= 1.0f      = 46725       marker        len=10  名字           564.847, 82.068, -226.258, …
```

**踩到的坑：`nameLen` 把结尾的 `\0` 也算进去了。**
`side_lamp` 是 9 个字符，但 `nameLen = 10`。按「长度不含 NUL」去解析，
会要求 `name[10]` 是 `\0`，实际那里已经是第一个浮点字节 → **4,199 条记录全被判非法，只剩 1 条。**

### 配对方法

记录的 6 个浮点 = 物体的位置 + 旋转，和 `RSD` 块的 `params` 是同一个变换。
所以用**「变换距离最近的 RSD 块」**做连接（候选限制在 ±4 KB 窗口内以保证速度）。

* **4,199 / 15,194 条 RSD 块**成功配对（其余 RSD 没有配套记录）
* 其中 4,174 条变换距离平方 < 1000 → **99.4% 是干净连接**

## 2. 判定原则

| 情形 | 含义 |
|---|---|
| 某个 gametype 下**名字高度集中** | 该 gametype **就是**这个名字的物件类型 |
| 某个 gametype 下有几百个不同名字 | 它是**通用容器槽**（"杂项"），不是具体物件类型 |

用 **purity**（最常见名字占比）区分。

## 3. 高置信度映射（purity ≥ 60%，32 项）

| gametype | 物件名 | 记录数 | purity |
|---|---|---|---|
| `0x00030081` | **side_lamp**（路灯） | 734 | 97% |
| `0x00030082` | **double_lamp**（双臂路灯） | 121 | 99% |
| `0x0003000E` | **double_lamp** | 16 | 100% |
| `0x0003002C` | **road_block_barrier**（路障） | 457 | 88% |
| `0x00030010` | **road_block_barrier** | 9 | 89% |
| `0x00000430` | **road_block_barrier** | 1 | 100% |
| `0x0003001B` | **apex**（弯心标志） | 130 | 93% |
| `0x00030080` | **side_traffic**（路侧交通牌） | 76 | 93% |
| `0x0003000C` | **side_traffic** | 4 | 100% |
| `0x0003005C` | **trash**（垃圾桶） | 49 | 88% |
| `0x0003005B` | **trash2** | 26 | 92% |
| `0x00030060` | **hydrant**（消防栓） | 22 | 91% |
| `0x0003005A` | **parkingclock**（停车计时器） | 18 | 100% |
| `0x000301BC` | **trailer**（拖车） | 17 | 100% |
| `0x000301BF` | **truck**（卡车） | 17 | 100% |
| `0x000000FB` | **villanyoszlop**（匈：电线杆） | 16 | 100% |
| `0x00000105` | **villanyoszlop** | 1 | 100% |
| `0x00030018` | **poster**（海报） | 11 | 100% |
| `0x0003003A` | **poster** | 1 | 100% |
| `0x0003005D` | **mailbox**（邮筒） | 15 | 93% |
| `0x00030020` | **buoy**（浮标） | 30 | 80% |
| `0x00030011` | **bouy**（同上，拼写变体） | 2 | 100% |
| `0x00030019` | **fear** | 99 | 83% |
| `0x00000431` | **flare_side**（侧向信号灯） | 24 | 96% |
| `0x00000494` | **flare_blue**（蓝灯） | 43 | 67% |
| `0x00000495` | **flare_orange**（橙灯） | 5 | 100% |
| `0x00030013` | **parking_car**（停放车辆） | 7 | 100% |
| `0x00030014` | **parking_car** | 4 | 100% |
| `0x00030015` | **parking_car** | 8 | 100% |
| `0x00030083` | **park_lamp**（公园灯） | 4 | 75% |
| `0x00030027` | **parking_car_e** | 26 | 62% |

## 4. 通用容器槽（purity < 60%，19 项）

这些是**"杂项道具"通用槽位**，一个 gametype 下混着几百种名字 —— 说明
**gametype 只决定"类别/行为"，具体模型由记录里的名字决定**：

| gametype | 记录数 | 不同名字数 | 里面装了什么 |
|---|---|---|---|
| `0x00030038` | 754 | **637** | side_lamp, electric_pole_cyan, side_traffic, apex, Box… |
| `0x0003004E` | 326 | **273** | park_lamp, l_flare269, l_flare258 … |
| `0x00030050` | 325 | **295** | l_flare193, l_flare170 … |
| `0x00030041` | 173 | **173** | l_flare_d_84, l_flare_d_83 … |
| `0x00030042` | 151 | 100 | park_lamp, l_flares153 … |
| `0x0003004D` | 77 | 77 | l_flare318, l_flare312 … |
| `0x00030023` | 71 | 66 | side_lamp, roadside_block366 … |
| `0x000300A7` | 65 | 7 | parking_car_a(26), parking_car(25) … |
| `0x000300A1` | 54 | 4 | parking_car_b(25), parking_car(17) … |
| `0x0003009F` | 37 | 4 | parking_car_c(20), parking_car(9) … |
| `0x00000185` | 36 | 22 | electric_pole_cyan(15), crash_barrier464 … |
| `0x00000005` | 29 | 29 | flare52, flare55, flare57 …（编号灯） |
| `0x00030028` | 25 | 4 | parking_car_d(12) … |
| `0x00030064` | 18 | 4 | side_traffic(7), side_traffic_double(6) … |
| `0x00000089` | 16 | 16 | Cylinder101, Cylinder100 …（编号圆柱） |
| `0x00000088` | 4 | 4 | Cylinder75, Cylinder77 … |
| `0x00030069` | 4 | 4 | park_lamp30, park_lamp32 … |
| `0x00000191` | 6 | 6 | light_dummy342, l_flares140 … |
| `0x0003004C` | 9 | 9 | l_flare486, l_flare478 … |

**重要推论**：`0x000300A7/A1/9F/27/28` 这 5 个都映射到 `parking_car_a..e`，
说明它们是**同一个"停放车辆"物件的 5 个变体槽**（车色/车型不同），
但记录里的名字没有严格区分 —— 需要看游戏内确认。

## 5. 名字词汇表（可直接用于重制）

| 类别 | 名字 |
|---|---|
| 照明 | `side_lamp`、`double_lamp`、`park_lamp`、`l_flare*`、`l_flare_d_*`、`light_dummy*`、`flare*` |
| 交通设施 | `side_traffic`、`side_traffic_double`、`apex`、`road_block_barrier`、`crash_barrier*`、`parkingclock` |
| 道具 | `trash`、`trash2`、`hydrant`、`mailbox`、`poster`、`buoy`/`bouy` |
| 载具 | `parking_car`/`_a..e`、`truck`、`trailer` |
| 建筑构件 | `Box*`、`Cylinder*`、`roadside_block*`、`electric_pole_cyan`、`villanyoszlop` |
| 信号 | `flare_blue`、`flare_orange`、`flare_side` |
| 其它 | `fear`（含义未明）、`Object*` |

`villanyoszlop` 是匈牙利语（"电灯杆"），`korfuggo`、`felho`、`iranyitok` 等同理
—— **Invictus Games 是匈牙利工作室**，命名遗留是吻合的。

## 6. 工具

| 工具 | 作用 |
|---|---|
| `tools/gametype_map.py` | 扫 `58 00 00 00` 记录 + 与 `RSD` 变换配对 + 算 purity，输出 `--csv` |
| `docs/gametype_map.json` | **机器可读**：`{confident:{}, catchall:{}}`，直接拿去写生成器 |
| `docs/gametype_map.csv` | 同上的表格版 |
| `docs/gametype_names.csv` | 4,199 条**逐物体**明细（map, gametype, name, 变换, 匹配距离） |

## 7. 对重制的意义

* **关卡装配现在完全可做**：`docs/map_objects.csv` 给每个物体的坐标+朝向，
  `docs/gametype_map.json` 给它是什么东西
* 32 个高置信度类型 + 名字词汇表 → 在 Unity/Godot 里实现一个
  `switch(gametype)` 生成器，配合 `name` 选择具体模型，即可装配全部 15,194 个物体
* 19 个通用槽的语义 = **"这一类物件走名字选模型"**，逻辑上比枚举 gametype 更简单

## 8. 仍缺

* 12,000 余条 `RSD` 块没配上记录（缺 `58 00 00 00` 记录）→ 名字未知，但 gametype 已知
* `0x00030019` = `fear`、`0x00030069` = `park_lamp30` 语义存疑
* 记录头里的 `u32 ?`（如 `0x0000B685`）语义未定 —— 疑似离线文件偏移
* `maps/*.rpk` 里 `Box*`/`Cylinder*` 编号与 INVO 网格的对应关系未建
