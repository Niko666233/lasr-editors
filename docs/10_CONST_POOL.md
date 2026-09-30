# 10 · `CONS` 常量池与名字恢复

> 状态：✅ **彻底定案**（字节级 2224/2224 精确 + 语义级 128,449 次操作数零不符）
> 工具：`tools/pool_shape.py`（求解）、`tools/resolve_pool.py`（解析）、
> `tools/verify_pool.py`（验证）、`tools/lasr_named.py`（带名字反汇编）
> 产物：`out_names.json`、`out_named_bet.txt`、`out_named_hills.txt`、`out_pool_validate.txt`

---

## 1. 结论速览

### 1.1 `CONS` 版式

```
CONS blob = <u32 count>                 # 条目数（含字符串）
            count × entry
entry     = <u8 tag> <payload>
    tag 0 : NUL 结尾 UTF8 字符串
    tag 4 : 4 字节——1 个索引（Class → 名字 UTF8；或数组描述符）
    tag 5 : 8 字节——2 个索引（类引用 + 名称类型引用）        ← 字段/方法**引用**
    tag 7 : 8 字节——2 个索引（名字 + 描述符，**都直接指 UTF8**） ← NameAndType
```

索引 **0-based**，条目 `[0]` 恒为该类自身名字，`[1]` 恒为 `tag4 → 0`（自身类引用），
`[3]` 为 `tag4 → 2`（父类）。

### 1.2 ★ 全游戏只有 4 种 tag

用 `Bet.class` 求解出的尺寸表（`{4: 4, 5: 8, 7: 8}`）**不加修改**跑全量 2224 个类：
**2224/2224 字节级精确铺满、0 失败**。也就是说整个游戏**从未使用** tag 1/2/3/6/8…

**数值字面量根本不在池里** —— 它们是 `INT LITERAL` / `FLOAT LITERAL` 指令的**内联载荷**
（见 `docs/08_VM_OPCODES.md`）。池里只有字符串 + 类 + 成员引用。

### 1.3 验证数字（三道独立判据）

| 判据 | 结果 |
|---|---|
| 字节级：`pos == len(blob)` 且 `条目数 == count` | **2224/2224 = 100.00%**，0 失败 |
| 语义级：`INVOKE*` 操作数必须是**方法**描述符 | **61,124 / 61,124 = 100.00%** |
| 语义级：`FIELD_*` 操作数必须是**字段**描述符 | **52,320 / 52,320 = 100.00%** |
| 语义级：`NEW/CAST/INSTANCEOF/NEWARRAY` 必须是类名/数组描述符 | **15,005 / 15,005 = 100.00%** |
| **合计** | **128,449 次解析，0 不符** |

恢复出的名字规模：

```
2224 个类（池全精确）   2300 个不同类名
23,111 个成员引用 = 11,976 个方法 + 11,135 个字段
1,703  个不同方法名
```

顶层包分布：`vehicles` 14,598 / `java` 8,039 / `maps` 432 / `drivers` 8 —— 与游戏目录结构完全吻合。

---

## 2. `MTHD` 方法表（顺带解出）

```
MTHD blob = <u32 reserved=0> <u32 n_methods>
            n × 5 × <u32 flags, u32 name_idx, u32 desc_idx, u32 tree_slot, u32 ?>
```

* `name_idx` / `desc_idx` 都是 `CONS` 索引，直接指 UTF8。
* **`tree_slot` = `TREE` 记录索引，1-based。**
* ★ 类的 `TREE` 记录数 = 方法数 **+1**：**record 0 是编译器生成的静态初始化块 `<clinit>`，没有 `MTHD` 条目**。
  （早期按 `slot-1` 映射 → 全部方法名错位一格，`Bet.5` 会被标成 `<init>(II)`。）

`Bet.class` 七条记录全对：

```
(1, 20, 19, 1, 2) → <init>       "(I)"
(1, 20, 21, 2, 3) → <init>       "(II)"
(1, 20, 22, 3, 2) → <init>       "(Ljava.game.item.IPart;)"
(1, 20, 23, 4, 2) → <init>       "(Ljava.game.item.IVehicle;)"
(1, 25, 24, 5, 1) → getBetType   "()I"
(1, 27, 26, 6, 1) → getIcon      "()Ljava.gui.Texture;"
(1, 29, 28, 7, 1) → getName      "()Ljava.lang.String;"
```

`FILD`（字段表，168 B @ Bet）尚未定案，结构与 `MTHD` 相似但记录长度不是 4 的整数倍
（`(168-4)/6 = 27.33` B/记录）→ 见 §6。

---

## 3. 破解方法（可复用的套路）

眼睛读前缀只能定 tag 0 / tag 4，走到二进制段就失步。真正的破法是**把两个已知约束当零和一校验**：

1. **`count` 必须精确等于条目数** —— 唯一的、免费的 oracle。
2. **解析必须精确铺满 blob**（`pos == len`）。
3. tag 0 一定是 NUL 结尾字符串（前缀肉眼可读的部分已证）。

于是把「每个 tag 的载荷尺寸」当成**未知量做 DFS 求解**（`tools/pool_shape.py`）：

```
state = (pos, entry_index, 尺寸表)
在 pos 处: tag = blob[pos]
  tag == 0  → 跳到下一个 NUL
  tag != 0  → 尝试候选尺寸 s ∈ {4, 8}（尺寸表里有的则只试那一个）
剪枝：条目数 > count 立即回溯
成功：pos == len 且 条目数 == count
```

`Bet.class` → **唯一解** `{4:4, 5:8, 7:8}` ✓
然后把这张表**不加修改**跑全量 → 2224/2224 通过 → 证明解是全局的，不是过拟合单文件。

**再用一个与字节无关的判据二次确认**：操作数的「种类」必须匹配操作码要求的「种类」
（`INVOKE` 后必须跟方法描述符）。任何一处池解析错误都会让某个操作数指到错误种类的条目
→ `tools/verify_pool.py` 报 0 不符。

> 教训：**「精确铺满」是很强的约束，但单靠它可以被巧合满足**（早期错误的 5 字节模型
> 也恰好铺满了 `Bet.class`，只是条目数 187 ≠ 97）。**必须同时要 `count` 对上**，
> 两个约束联立才是零和一判据。

---

## 4. 操作数 → 池的绑定规则（按操作码分类）

| 操作码 | 操作数含义 | 例子 |
|---|---|---|
| `NEW` `CAST` `INSTANCEOF` | UTF8 索引**或** tag4 索引（两种编码并存） | `NEW 415` → tag4 → `java.util.resource.GameType` |
| `NEWARRAY` | 数组描述符 UTF8 | `NEWARRAY 11` → `[I` |
| `INVOKE` `INVOKESPECIAL` `INVOKESTATIC` | tag5 **引用**，描述符以 `(` 开头 | `INVOKE 305` → `java.game.RaceChronicle.analyseThis(Ljava.game.RaceChronicle;)V` |
| `FIELD_REF_*` `PUTFIELD_*` | tag5 **引用**，描述符是字段类型 | `PUTFIELD_QUICK 34` → `java.game.Bet.betType I` |
| `STRING LITERAL` | UTF8 索引 | `STRING LITERAL 437` → `"$1\|Self respect is important…"` |
| `INT LITERAL` `FLOAT LITERAL` `BOOL/CHAR/NULL LITERAL` | **内联数值，不是池索引** | `FLOAT LITERAL` 载荷按 `f32` 解 |
| `LOCAL_LOAD` `LOCAL_STORE` `LOCAL_CLEAR*` | **局部变量槽号** | `LOCAL_LOAD 1` → 第 1 个参数 |
| `JMP*` | **相对偏移**（`target = off + signed payload`） | 见 `docs/09_CFG.md` |
| `RID LITERAL` | 资源 id（未绑定到资源表） | |

★ **字段引用和方法引用共用 tag 5**：池里**没有**单独的 field-ref tag，
两者的区分完全由**操作码**承担。这是该引擎与标准 JVM 的一个设计差异。

---

## 5. 样例：`Bet.class` 完全还原

`out_named_bet.txt` 是用 `tools/lasr_named.py` 生成的**源码级**反汇编，例如：

```
--- method #0: ?   (61 bytes)          ← 静态初始化块（无 MTHD 条目）
        0  05 INT LITERAL           1
        5  20 PUTFIELD_STATIC       java.game.Bet.BET_TYPE_Prestige I
       10  05 INT LITERAL           2
       15  20 PUTFIELD_STATIC       java.game.Bet.BET_TYPE_PerformPart I
       ...
       60  16 RETURN

--- method #1: <init>(I)   (43 bytes)
        0  0b LOCAL_LOAD            slot 0
        5  11 INVOKESPECIAL         java.lang.Object.<init> ()
       10  14 FIELD_REF_STATIC      java.game.Bet.BET_TYPE_Prestige I
       15  21 PUTFIELD_QUICK        java.game.Bet.betType I
       20  0b LOCAL_LOAD            slot 1
       25  21 PUTFIELD_QUICK        java.game.Bet.prestigeValue I
       30  03 NULL LITERAL
       31  21 PUTFIELD_QUICK        java.game.Bet.betPart Ljava.game.item.IPart;
       36  03 NULL LITERAL
       37  21 PUTFIELD_QUICK        java.game.Bet.betIVehicle Ljava.game.item.IVehicle;
       42  16 RETURN

--- method #3: <init>(Ljava.game.item.IPart;)   (77 bytes)
        0  0b LOCAL_LOAD            slot 0
        5  11 INVOKESPECIAL         java.lang.Object.<init> ()
       10  0b LOCAL_LOAD            slot 1
       15  10 INVOKE                java.game.item.IPart.isPerformancePart ()I
       20  18 JMP_NE               -> 35  (+15)
       25  14 FIELD_REF_STATIC      java.game.Bet.BET_TYPE_PerformPart I
       30  17 JMP                  -> 40  (+10)
       35  14 FIELD_REF_STATIC      java.game.Bet.BET_TYPE_StylingPart I
       40  21 PUTFIELD_QUICK        java.game.Bet.betType I
       45  0b LOCAL_LOAD            slot 1
       50  10 INVOKE                java.game.item.IPart.getPrestige ()I
       55  21 PUTFIELD_QUICK        java.game.Bet.prestigeValue I
       60  0b LOCAL_LOAD            slot 1
       65  21 PUTFIELD_QUICK        java.game.Bet.betPart Ljava.game.item.IPart;
       70  03 NULL LITERAL
       71  21 PUTFIELD_QUICK        java.game.Bet.betIVehicle Ljava.game.item.IVehicle;
       76  16 RETURN
```

即：

```java
class Bet {
    static final int BET_TYPE_Prestige = 1, BET_TYPE_PerformPart = 2, …;   // <clinit>
    int betType; int prestigeValue; IPart betPart; IVehicle betIVehicle;

    Bet(int type)   { this.betType = BET_TYPE_Prestige; this.prestigeValue = type;
                      this.betPart = null; this.betIVehicle = null; }
    Bet(int t, int p){ this.betType = t; this.prestigeValue = p; … }
    Bet(IPart p)    { this.betType = p.isPerformancePart() ? BET_TYPE_PerformPart
                                                          : BET_TYPE_StylingPart;
                      this.prestigeValue = p.getPrestige(); this.betPart = p; … }
    …
}
```

`Bot.class`（454 条目）顺带把整棵 AI/对话系统的字符串都还原了：
`botTalks`（`[[[[Ljava.lang.String;` 四维字符串数组）、`BOTTALK_REJECT/GOSSIP/TEASER/BOAST/OFFER`、
`AI_level `、`AI_params2 `、`AI_follow 0,0,`、`AI_RaceSpline `、`AI_ActivateSpline `、
`$1|Self respect is important…` 等台词模板 —— 这些都是走 `command("AI_race …")` 的控制台指令，
见 `out_names.json`。

---

## 6. 未解 / 待办

* **`FILD` 字段表版式**未定案（`Bet` 168 B、`Hills` 120 B，记录长度非 4 整数倍）。
  已知字段：`name_idx` / `type_idx`（都是 `CONS` 索引）+ 若干标志位。
  解开后可给出**字段名 + 局部变量名**，伪码可读性再上一台阶。
* **局部变量名**：`FILD` 未解 → `LOCAL_LOAD slot 3` 目前只能显示槽号。
* **`RID LITERAL`** 尚未绑定到 `RPAK` 的资源 id。
* **`MTHD` 的 `flags` / 第 5 字段**语义未定（`extra` 值 1/2/3 疑似参数计数或可见性）。
* `docs/08_VM_OPCODES.md` 的每个操作码「操作数语义」一列需要按本文 §4 回填。

---

## 7. 陷阱清单（踩过的坑）

1. **tag 4 的载荷必须取 `[0]`**：解析器把它存成 1 元组 `(7,)`，
   `utf8(val)` 会拿元组当字典键 → **静默返回 `None`**。嵌套引用里写的是 `vals(a)[0]` 所以
   `INVOKE`/`FIELD` 一直是对的，只有顶层 `tag4` 一直解析失败（表现为池转储里满是
   `tag4->(0,)?`）。★ 一个静默的 `None` 能掩盖整类解析失败。
2. **`NEW` 的操作数不是「类索引」**：它可以直接指 **UTF8**，也可以指 **tag4**，两种并存。
3. **`NEWARRAY` 的操作数是数组描述符 `[I`/`[F`**，不是点分类名 —— 验证判据要放行。
4. **不要用「条目数不匹配」之外的单一判据**：错误的 5 字节模型也能精确铺满 `Bet.class`。
5. **`MTHD` 的 `tree_slot` 是 1-based**，`TREE` record 0 是 `<clinit>`，没有对应的 `MTHD` 条目。
6. `INT/FLOAT/LOCAL/JMP` 的操作数**不是池索引**；早期版本把它们的操作数也当索引去查，
   输出了一堆看似有理的假名字（`INT LITERAL 1` → `tag4 -> (0,)`）。
