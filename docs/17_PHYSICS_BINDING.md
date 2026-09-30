# 17 · 原生实体属性系统 ↔ Java 配置（物理参数绑定）

> P5 第一块。**结论：游戏的车辆/物件参数不是二进制黑箱，而是一套「名字 → setter」属性表 +
> 文本键值对」，两端我都拿到了。**
> 工具：`tools/pe_scan.py`（PE/字符串/xref/反汇编）、`tools/native_props.py`（属性表）、
> `tools/native_fields.py`（handler → 格式串 + 字段偏移）、`tools/config_dump.py`（配置抽取）

---

## 1. 属性表（LASR.exe `.data`，8 字节记录）

```
struct PropRec { const char* name; void (*handler)(void* this, const char* value); };
```

5 张表 / **198 条 / 149 个不同名字**（`out_native_props.json`）：

| 表 | 条数 | 是什么 | 代表键 |
|---|---:|---|---|
| 0 | 9 | **原生实体类注册表** | `ground camera object car part trigger player cursor bot` |
| 1 | 109 | **车** | `mass enginepower ratios torque rearendratio brakepower clutch wheel_friction spring maxsteer rpm_idle drag wing center rollbar steerhelp steerspeed velfactor turn roll pitch cheat_control` + OSD/sfx/slot/座舱 |
| 2 | 14 | **轮 / 网格材质** | `materials material params friction rollres collcoeff pacdata type skid_PS skid_SM skid_SMcolor skid_SFX FF_effect tire_bump` |
| 3 | 31 | **物件 / 部件** | `bounds body render light shadow bone trigger part nocollision buoy concave joint damage material powerup init damping foliage…` |
| 4 | 35 | **部件（slot）** | `click body bone inertia flags slotturn deform damage intdamage skinned linked stockpart…` |

**这是重制最需要的一张词表**：它说明每个物件/车有哪些可调项，且表里的 `handler` 指针
就是写这个字段的代码。

## 2. 配置管线（全链已解）

```
Java: Model_*.class  →  configureType("maxsteer\t0.750 2.406 10.0")
   ↓  (native method, 名字字符串在 .rdata: 0x6ede0c 'configureType')
0x4afc70  按行切分，逐行调 0x4afb30
0x4afb30  strncpy(256) → 在 ';'(0x3b) '#'(0x23) '/'(0x2f) 处截断（注释）
          → 用 [0x743210] = " \r\n\t" 分词
          → 线性扫描属性表（strcmp 每个 name）
          → call handler(this, 值串)
handler   sscanf(值串, "<fmt>", &字段, …)   ← 包装函数 0x5666c0
```

- **`configureType` / `configureVisual` 是 native 方法名**（.rdata 里各只有 2 处引用 ✓）
- 分隔符是 `" \r\n\t"`（`[0x743210]` 里存的是指针 → 0x6f0158）✓
- 支持 `;` `#` `/` 三种注释截断 ✓

### 车辆标量属性：格式串（= 值的个数与类型）

`tools/native_fields.py` 从 198 个 handler 里机取出 **170 个 sscanf 格式串**，字段数由
格式串里的转换符个数确定（**自验证**：push 个数必须等于 `%` 个数，不等就标出来）：

| 属性 | 格式串 | 属性 | 格式串 |
|---|---|---|---|
| `mass` | `%f` | `maxsteer` | `%f %f %f` |
| `enginepower` | `%f %f %f %f %f %f` | `spring` | `%f %f %f` |
| `ratios` | `%d %f %f %f %f %f %f %f` | `steerhelp` | `%f %f %f %f %f %f` |
| `torque` | `%#%f:%f` | `steerspeed` | `%f %f %f` |
| `drag` | `%f %f %f %f` | `velfactor` | `%f %f` |
| `brakepower` | `%f %f` | `turn` | `%f %f %f` |
| `clutch` / `rearendratio` | `%f` | `roll` | `%f %f %f %f` |
| `wheel_friction` | `%f %f` | `pitch` | `%f %f %f` |
| `pacdata` | `%d %d %f` | `center` | `%f %f %f` |
| `collcoeff` / `rollres` | `%f` | `tire_bump` | `%d %f %f %f` |
| `FF_effect` | `%d %f %f %f` | `wheelpars` | `%f ×9` |

→ 例如 `maxsteer` 恰好 3 个数 ✓（`docs/14` 从 Java 侧拿到的 `Chassis.max_steer = 0.7` 是它的第 1 个 ✓）。

### 数组属性：每轮一个 0xD8 字节的元素

`wheel` / `arm` / `hub` / `wheelbones` 这类 handler 结构完全一致：

```asm
mov  eax, [this + 0x3cb0]        ; 元素个数（轮数 / 臂数）
test eax, eax / jle  skip
imul eax, eax, 0xD8              ; ★ 元素步长 = 0xD8 = 216 字节
lea  esi, [eax + this + 0x3bdc]  ; ★ 数组基址 = this + 0x3bdc（取第 count-1 个元素）
...
sscanf(值, "<fmt>", &栈临时…)     ; 先解析到栈
movss [esi + 0x54], xmm0 …       ; 再逐个写进元素
```

**这是本轮最重要的结构发现**：原生侧「一台车 = 车身对象 + `count` 个 216 字节轮/臂记录」，
车身对象在 `entity+0x4878`，轮数组在 `car+0x3bdc`，个数在 `car+0x3cb0` ✓

已定位到的字段组（`out_native_fields.json` 的 `post_stores`）：

| 组 | 偏移 | 含义 |
|---|---|---|
| 引擎功率曲线 6 槽 | `+0xe8 +0xec +0xf8 +0xfc +0x100 +0x108 +0x118` | `enginepower` 写其中 6 个（与 docs/14 的 RPM×倍率曲线对应） |
| 扭矩 2 槽 | `+0xf0 +0xf4` | `torque` / `rearendratio` / `brakepower` / `clutch` 共用 |
| 轮 · 摩擦/滚阻 | `+0x330 +0x334` | `rollres` / `pacdata` |
| 轮 · 碰撞系数 | `+0x300` | `collcoeff` |
| 轮 · 冲击曲线 4 槽 | `+0x30c +0x310 +0x314 +0x318` | `tire_bump` |
| 力反馈 4 槽 | `+0x2f0 +0x2f4 +0x2f8 +0x2fc` | `FF_effect` |
| 元素内位置 | 元素基址 `+0x1c +0x20 +0x2c +0x30 +0x54 +0x58 +0x5c +0x6c +0x78 +0x7c +0x8c` | `wheel` / `arm` / `hub` / `bonepos` / `skid` |

## 3. 配置文本全量抽取

`tools/config_dump.py`：把每个 TUFA 类里的可打印串按 `key<TAB>values` 解析，
**key 必须命中第 1 节的 149 个原生属性名**（白名单来自 exe，不是猜的）——
所以抽出来的每一行都按构造被验证过。

**9,849 行配置，覆盖 691 个类**（`out_config_dump.csv` 1.9 MB / `.json` 1.7 MB）：

| 键 | 行数 | 键 | 行数 |
|---|---:|---|---:|
| `body` | 1954 | `flags` | 567 |
| `slot` | 1906 | `nocollision` | 536 |
| `damage` | 660 | `dirt_texture` | 457 |
| `wing` | 646 | `flexible` | 306 |
| `lod` / `lods` | 644 / 630 | `slottype` | 220 |
| `use_mesh` | 619 | 车辆属性（20 台车） | 各 20 或 80 |

样例（`Model_Hatch_S2`，Fantasy_Corus 2005）：

```
maxsteer    0.750 2.406 10.0
spring      0.490 0.100 0.050
steerhelp   1.000 30.000 0.500 1.200 1.571 1.0
steerspeed  0.625 50.0 0.280
wheel       -0.731 0.000 -1.203   0.000 0.000 0.000   1.000 0.000 1.000 0.000
type        10.000 sphere  0.650
steering    -0.366 0.496 -0.258  0.0 -0.383 0.0  0.010  sphere 0.100
```

**注意**：`enginepower` / `ratios` / `wheel_friction` / `pacdata` 这些**不在 Java 语料里**
（全库 0 命中，`extracted/`、`extracted_rpak/` 都搜过）→ 它们的值来自**二进制**路径，
不是文本缓冲。这是本项剩下的主要缺口。

## 4. 验证与产出

| 判据 | 结果 |
|---|---|
| 属性表记录合法性（name 指针落在 `.rdata` 可打印串、handler 落在 `.text`） | 198/198 ✓ |
| 格式串字段数 vs 紧邻 push 个数 | 170 个 handler 全部自洽（个数不等会被标 `short`）✓ |
| 分隔符字符串 | `[0x743210]` → `" \r\n\t"`；表被 `.text` 两处引用（0x45599a / 0x461052）✓ |
| 配置抽取 | key 全命中原生白名单，9,849 行 / 691 类 ✓ |
| `maxsteer` 3 值 ↔ Java 侧 `Chassis.max_steer` | 一致（3 值中的第 1 个）✓ |

产出：`out_native_props.json`、`out_native_fields.json/.csv`、`out_config_dump.csv/.json`、
`tools/{pe_scan,native_props,native_fields,config_dump}.py`

## 5. 仍未解 / 已定位（诚实列出）

**已定位（本轮末尾）**：`enginepower` / `ratios` / `pacdata` 这类键**不在任何数据文件里**
（`extracted/`、`extracted_rpak/`、整个 `C:\Games\LASR` 排除大文件后全库 0 命中）——
它们的值走 **Java → 原生 setter 的数组参数**，而不是文本行：

```java
// out_pseudo/java/classes/game/Vehicle.java（我已抬升的伪码，直接可读）
local1.setTorqueFactors(this.SPtrqs_F.x, this.SPtrqs_F.y, this.SPtrqs_F.z);   // 前轮扭矩分配
local1.setTorqueFactors(this.SPtrqs_R.x, this.SPtrqs_R.y, this.SPtrqs_R.z);   // 后轮
local0.setTurboParams(this.turboTable, this.turboFlags);
local0.setExhaustParams(this.consumption_air_per_rotation, this.exhaust_reaction);
// out_pseudo/java/classes/game/parts/{Rim,Tyre}.java
local2.setPacejka(local3, PacejkaGlobals.common_pacVarIdxs, PacejkaGlobals.common_pacVars);
local2.setPacejka(local3, PacejkaGlobals.pacVarIdxs, Rim.pacVars[local3]);
// 引擎曲线：new java.util.PointPairSeries(eRPMs(), eMuls())
```

→ **重制要的物理参数 = 这些 Java 类（已抬升）+ 本轮的字段偏移表**，
两端都拿得到，不需要再猜数值。

仍缺：

- **标量属性的精确字段偏移**：部分 handler 先把值解析到**栈临时**再搬进结构，
  需要一个小型寄存器模拟器才能跟到最终偏移（数据结构已就位，工具留了 `post_stores` 字段）；
- **数组元素内部的字段顺序**（`wheel` = 12 值 + 1 整数 对应元素的哪些偏移）；
- `setTorqueFactors` / `setPacejka` / `setTurboParams` / `setExhaustParams`
  这几个 native 方法**自身的字段偏移**（用同一套方法反它们即可）；
- handler 里从 `.rdata` 浮点常量取的**默认值**（例：`0x6e7668`）—— 是"未配置时的缺省"，
  对重制有用，逐个提取未做。

## 附：一条工具教训（值得记住）

`LASR.exe` 的属性 setter **只被属性表引用**，一直找不到调用点 —— 因为
**绝对 VA 扫描（`push imm32`）看不到相对调用（`E8 disp32`）**。
补上 `pe_scan.py callers`（线性扫 `E8`/`E9` + 校验目标）后立刻找到了
配置加载器 `0x4afce0` 的 3 个调用点与 sscanf 包装函数的 **533 个**调用点。
**只看数据引用的 xref 分析会得出"这段代码没人用"的错误结论。**
