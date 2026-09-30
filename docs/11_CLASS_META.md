# 11 · TUFA 类元数据：`FILD` / `MTHD` / `CLSS`

> 状态：✅ **三个块全部彻底定案**（每块都有字节级 100% + 一条独立的语义判据）
> 工具：`tools/fild_shape.py`（`--class` / `--verify` / `--export`）
> 产物：`out_fields.json`（8,487 字段）、`out_fild_validate.txt`、`out_fild_report.txt`
> 相关：`docs/10_CONST_POOL.md`（`CONS` 常量池）、`docs/08_VM_OPCODES.md`（指令编码）

---

## 1. `FILD` 字段表 ✅

### 1.1 版式

```
FILD blob = <u32 n_static>                      第 1 组（静态）字段数
            n_static × <u32 flags><u32 name_idx><u32 type_idx><u32 extra>   (16 B/条)
            <u32 n_instance>                    第 2 组（实例）字段数
            n_instance × <u32 flags><u32 name_idx><u32 type_idx><u32 extra> (16 B/条)
```

`name_idx` / `type_idx` 都是 `CONS` 索引，直指 UTF8 条目。

★ **两组之间夹着第二个计数字段**，不是「一个头部 + 一个数组」——
`4 + 16·n₁ + 4 + 16·n₂ == len(blob)` 才是完整判据。

### 1.2 `flags` 就是标准 JVM 字段访问位

```
1 = public   2 = private   4 = protected   8 = static   16 = final
32 = synchronized   64 = volatile   128 = transient
```

`Bet` 的 6 个 `BET_TYPE_*` 全是 `0x19 = public|static|final` ✓ 与 `static final int` 完全一致。
全量标志位直方图：

| 值 | 数量 | 解读 |
|---|---|---|
| `0x00` | 2,261 | 包私有实例字段 |
| `0x08` | 1,871 | `static` |
| `0x19` | 1,488 | `public static final` |
| `0x1a` | 811 | `private static final` |
| `0x18` | 703 | `static final`（包私有） |
| `0x09` | 522 | `public static` |
| `0x01` | 509 | `public` |
| `0x02` | 185 | `private` |

### 1.3 `extra` 是编译器缓冲区残留（**不要解释它**）

`extra` 各字段之间毫无一致性：`0x0EA4`、`0x00050000`、`0x0EA1`、`0`、`0x54C0040C`、`0x88080EA1`…
其中 `0x000E000F` 的字节是 `0f 00 0e 00` = 两个 u16 `15`/`14`（**相邻字段的名字索引**），
`a1 0e 08 88` = `0x0EA1`（**别的字段的 flags**）——
说明这是**复用未清零的缓冲区**留下的垃圾，不是格式的一部分。工具只报告不解读。

### 1.4 验证（三项全 100%）

| 判据 | 结果 |
|---|---|
| 字节级：`4+16n₁+4+16n₂ == len(blob)` | **2224/2224 = 100.00%** |
| 索引级：每个 `name_idx`/`type_idx` 都解析成 UTF8 | **2224/2224 = 100.00%** |
| **语义级**：第 1 组字段只被 `*_STATIC` 操作码引用、第 2 组只被 `*_QUICK` 引用 | **8,174 / 8,174 = 100.00%**，0 不符 |

第三条与字节无关：它只用「操作码种类 ↔ 字段种类」的对应关系，
所以它独立地把「哪一组是静态」钉死了。

⚠️ 该判据的键必须是 **`(属主类, 字段名)`**。第一次只按字段名归并 →
35 处假不符（`gameOptions` 的 `player_transmission` 等与别的类同名字段混在一起）。
**跨类同名字段很常见，按名归并必然出假阳性。**

### 1.5 产出规模

```
8,487 个字段 = 5,426 静态 + 3,061 实例      3,931 个不同字段名
字段最多的类：java.net.MetaServer 296 / java.io.Input 203 / java.util.Config 163
              java.game.frontend.controlOptions 152 / java.game.Gamelogic 152
类型直方图：I 2842 / F 1529 / ResourceRef 952 / PartDecal 602 / Label 382 / [F 223 …
```

---

## 2. `MTHD` 方法表 ✅

```
MTHD blob = <u32 reserved=0> <u32 n_methods>
            n × 5 × <u32 flags><u32 name_idx><u32 desc_idx><u32 tree_slot><u32 n_locals>
```

* `name_idx` / `desc_idx` → `CONS` 索引，直指 UTF8。
* **`tree_slot` = `TREE` 记录索引（1-based）**。
* `n_locals` 疑似**局部变量槽数（含 `this`）**：`<init>(I)`→2、`<init>(II)`→3、
  `getBetType()`→1 ✓ 与描述符参数个数 +1 完全吻合；且 `Hills` 里出现 4，`Vehicle` 出现 71。
* ★ **类的 `TREE` 记录数 = 方法数 + 1**：**record 0 是编译器生成的 `<clinit>`，没有 `MTHD` 条目**。
  早期按 `slot-1` 映射 → 全类方法名错位一格。

`Bet` 七条记录逐一验证（名字 + 描述符全对）：

```
(1, 20, 19, 1, 2) → <init>       "(I)"                        (this+I = 2 槽 ✓)
(1, 20, 21, 2, 3) → <init>       "(II)"                       (this+II = 3 槽 ✓)
(1, 20, 22, 3, 2) → <init>       "(Ljava.game.item.IPart;)"
(1, 20, 23, 4, 2) → <init>       "(Ljava.game.item.IVehicle;)"
(1, 25, 24, 5, 1) → getBetType   "()I"
(1, 27, 26, 6, 1) → getIcon      "()Ljava.gui.Texture;"
(1, 29, 28, 7, 1) → getName      "()Ljava.lang.String;"
```

---

## 3. `CLSS` 类描述块 ✅

固定 24 字节 = 6 个 u32：

```
[0] 0xFFFFFFFF       哨兵 / flags
[1] CONS 索引 → 自身类名（UTF8）
[2] CONS 索引 → 自身类引用（tag4）
[3] CONS 索引 → 父类引用（tag4）★ 父类在这里
[4] CONS 索引 → 自身类名（重复）
[5] 0 或 0xFFFFFFFF  （疑似源文件名 / 外部类，无则 0xFFFFFFFF）
```

实测：

| 类 | `[3]` 解析出的父类 |
|---|---|
| `java.game.Bet` | `java.lang.Object` |
| `maps.hills.classes.Hills` | `java.game.Map` ✓ |
| `java.game.Vehicle` | `java.game.parts.Chassis` ✓ |

内容与 `CONS` 头部冗余，但它是**唯一显式给出父类**的地方，比从池里猜可靠。

---

## 4. 局部变量名：**文件里不存在**

`FILD` 存的是**字段**名。全库没有任何局部变量名表（5 个块只有 `CONS`/`FILD`/`MTHD`/`CLSS`/`TREE`）。

验证：`CONS` 共 229,091 个 UTF8 条目，其中形如 camelCase 标识符的 37,183 个，
扣掉所有类名/方法名/字段名后**只剩 3,308 个**（不同 820 个），
而它们的实际身份是**资源与脚本键**，不是局部变量名：

```
bone  noclick  nocollision  exitTrack  sideskirt  wheelbones  skydome1  mirrordome
belso_perem  kulso_perem  fektarcsa …      ← 匈牙利语「内圈/外圈/靠垫」，开发组是匈牙利人
```

所以反汇编里局部变量**只能显示槽号**（`LOCAL_LOAD slot 3`）。
不过 `MTHD.n_locals` 给出了槽数，配合描述符就能知道每个槽是第几个参数。

---

## 5. 现在反汇编器能输出什么

`tools/lasr_named.py --class <file>` 现在输出**完整类重建**：

```
=== Bet.class  pool=97 exact=True methods=8 (MTHD names: 7) ===
class java.game.Bet extends java.lang.Object
   static public|static|final     I                          BET_TYPE_Prestige
   static public|static|final     I                          BET_TYPE_PerformPart
   …
   field  private                 I                          betType
   field  public                  I                          prestigeValue
   field  public                  Ljava.game.item.IPart;      betPart
   field  public                  Ljava.game.item.IVehicle;   betIVehicle

--- method #1: <init>(I)   (43 bytes)   locals=2
        0  0b LOCAL_LOAD            slot 0
        5  11 INVOKESPECIAL         java.lang.Object.<init> ()
       10  14 FIELD_REF_STATIC      java.game.Bet.BET_TYPE_Prestige I
       15  21 PUTFIELD_QUICK        java.game.Bet.betType I
       …
```

### 顺带挖出的重制关键数据

`java.game.Gamelogic`（152 个字段）= **全局游戏状态机的完整模式**：

```
状态:  GST_INIT GST_SHUTDOWN GST_START GST_USERLOGIN GST_USERINIT GST_SERVERLOGIN
       GST_MENU GST_LOBBY GST_ROOM GST_INGAME GST_PUB GST_SETTINGS
模式:  SINGLE TEST DEMO MULTI GUITEST REPLAY TESTERBOT SETTINGS
存档:  SAVEFILEID_MAIN SAVEFILEVERSION_MAIN saveFileName curSaveSlot lastSaveTime
试炼:  weHaveATrial trialProgress trialsCompleted TRIALS_PER_SERIE trials
经济:  prestige lastPrestigeValues BEST_PRESTIGE_VALUES PRESTIGE_VECTOR_SIZE
天气:  WEATHER_DRY WEATHER_DAMP WEATHER_WET WEATHER_WINDY WEATHER_SNOWY WEATHER_COUNT
AI:    aiLevelMul aiLevelMul2 aiLevelMul3 BOT_ARRAY_MAX opponents botTalks
网络:  serverID connectionCount serverName serverLocation lobbyID MGSaddress
司机:  manDriver1..4 girlDriver1..4        （对应 drivers.crcman / crcgirl 4 个变体 ✓）
彩蛋:  sala_splinet_keszit   （匈牙利语，疑似开发者私货）
```

---

## 6. 陷阱清单

1. **`FILD` 不是「一个头部 + 一个数组」**：两组计数**夹在中间**，
   用 `4 + 16·(n₁+n₂)` 去校验会算错 4 字节。
2. **`extra` 是缓冲区垃圾**，跨字段毫无一致性 —— 别当默认值/标志位解读。
3. **跨类同名字段很常见**，任何「按字段名」做的交叉检验都必须带上属主类，否则出假阳性。
4. **`MTHD.tree_slot` 是 1-based**，且 `TREE` 多出一条 `<clinit>`，没有 `MTHD` 条目。
5. **局部变量名不存在**，别去池子里硬凑（那些 camelCase 字符串是资源键）。
6. `flags` 用标准 JVM 位（`1/2/4/8/16/…`），不要另起一套解释。
