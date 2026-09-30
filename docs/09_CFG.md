# P2.3 —— CFG：控制流图已建成

> **状态：✅ 完成。** 跳转基址 = `指令偏移 + 有符号 payload`（10,029/10,029 = **100.0%** 目标
> 落在指令起点）；14,796 个方法全部以 `RETURN` 结尾；31,246 个基本块 / 21,144 条边 /
> 545 条回边。反汇编已可读（见 `out_disasm_sample.txt`）。

## 0. 先修一个我自己引入的 bug：方法末尾的 RETURN 被剥掉了

`tools/lasr_vm.py::load_records()`：

```python
for i, r in enumerate(tree_records(ck["TREE"][0])):
    if r and r[-1] == 0x16:          # 要求 record 以 0x16 结尾 …
        recs.append((f.stem, i, r[:-1]))   # … 然后又把它切掉 ✗
```

那个 `r[:-1]` 是早期把 `0x16` 误判成「容器分隔符」时写下的。三条理由说明它是**方法的
尾 RETURN**，不是分隔符：

1. `0x16` 是一个**真操作码**（RETURN，见 `docs/08_VM_OPCODES.md` §5.2），1 字节、无载荷；
2. 容器（TREE chunk）**每条 record 已经用 `u32 size` 长度前缀**，不需要字节分隔符；
3. **全部 14,796 条 record 恰好都以 `0x16` 结尾** —— 这正是「编译器给每个方法都补一条
   RETURN」的形状。

所以正确的模型是：**`code = record blob`（含尾 `0x16`）**，`tools/lasr_cfg.py::load_methods()`
把它加回来。影响：

| | 剥离尾字节（旧口径） | **完整 code（正确）** |
|---|---|---|
| 指令总数 | 367,603 | **382,399** |
| 字节总数 | 1,460,399 | **1,475,195**（均 3.86 B/条） |
| `0x16` 出现 | 2,040（仅提前 return） | **16,836** = 14,796 尾 RETURN + 2,040 提前 RETURN |
| 方法以 RETURN 结尾 | 2 / 14,796 ✗ | **14,796 / 14,796 = 100%** ✅ |

宽度表本身不受影响（两种口径都 100% 精确解析）。

## 1. 🎯 跳转基址：`target = 指令偏移 + 有符号 payload`

分派点读过 `0x17 JMP` 的 handler 做相对计算（`mov edx,[edi+1]; add edx,edi`），但
**基址到底是「操作数偏移」还是「指令偏移」必须由语料判定**。判据：正确的基址能让
**近乎 100%** 的跳转载荷落在**另一条指令的起点**（或方法末尾）—— 错基址几乎必然落在
指令中间。

`tools/lasr_cfg.py --jumpbases`：

| opcode | n | `off+1+pay` | **`off+pay`** | `pay` 绝对 | `off+5+pay` |
|---|---|---|---|---|---|
| `0x17` JMP | 3,295 | 25.9% | **100.0%** | 30.3% | 74.1% |
| `0x18` JMP_NE | 4,378 | 33.7% | **100.0%** | 27.4% | 66.3% |
| `0x19` JMP_EQ | 16 | 0.0% | **100.0%** | 0.0% | 100.0% |
| `0x1a` JMP_EQ2 | 2,340 | 2.1% | **100.0%** | 28.6% | 97.9% |
| **合计** | **10,029** | 23.7% | **100.0%** | 28.6% | 76.3% |

**全 10,029 个跳转、四个操作码统一 100.0%，越界 0 个**（前向 9,484 / 后向 545）——
没有比这更干净的判定了。

> 注意 `off+5+pay` 拿到 76.3%：因为指令只有 1 或 5 字节，随便 +5 也有约 76% 概率落到
> 某个指令起点。**只有 100% 才能定案。**

## 2. CFG 结构

`tools/lasr_cfg.py --stats`：

| 指标 | 值 |
|---|---|
| 方法数 | **14,796** |
| 以 RETURN 结尾 | **14,796（100%）** |
| 基本块 | **31,246**（均 2.1/方法，中位 **1**，最大 222） |
| CFG 边 | **21,144**（均 1.43/方法） |
| 回边（循环 latch） | **545** |
| 含不可达代码的方法 | **355**（1,181 个块，2.4%） |

**中位 1 个块**说明多数方法是**直线代码**（绝大多数是 getter/setter/小工具函数），
只有少数是大状态机。循环分布：

| 循环数 | 方法数 |
|---|---|
| 0 | 14,486 |
| 1 | 206 |
| 2 | 57 |
| 3 | 19 |
| 4 | 12 |
| >4 | 16 |

方法规模分布：

| 指令数 | 方法数 |
|---|---|
| ≤2 | 1,221 |
| 3–4 | 2,286 |
| 5–10 | 5,429 |
| >10 | 5,860 |

最大的方法：`Hills.6` 3,254 条、`Coastline.5` 2,593 条、`Track.37` 2,326 条（217 块）。
最复杂的：`Model_Hatch_Trend.13` 223 块 / 662 条 / 112 跳转。
最简的：`Bet.5` = `FIELD_REF_QUICK 34; RETURN`（纯 getter）。

`355 个方法含不可达代码` —— 可能是编译器为 `while(true)`/常量条件留下的死代码，也可能是
`SHORTCUT_*` 短路造成的「编译器已排除的分支」。**待查**，但不影响 CFG 正确性
（跳转目标 100% 命中已证明）。

## 3. 🎯 控制流模式（`--idioms`，14,796 个方法全扫）

| 模式 | 计数 |
|---|---|
| 对象分配 `NEW; DUP` | 12,075 |
| `if (cond)` → `JMP_NE` | 4,252 |
| 连续取参 `LOCAL_LOAD x2` | 3,893 |
| `if (cond)` → `JMP_EQ2` | 2,340 |
| **提前 RETURN**（非末条） | 2,040 |
| 空值比较 `NULL LITERAL; IEQ/INE` | 1,581 |
| **短路 &&** `SHORTCUT_AND; JMP` | 680 |
| **短路 \|\|** `SHORTCUT_OR; JMP` | 270 |
| 混合实参 `INT LITERAL; FLOAT LITERAL` | 231 |
| `if (!cond)` → `EXCLAMATION; JMP_NE` | 126 |
| `if (cond)` → `JMP_EQ` | 16 |

### ★ 短路模式独立确认了 `0x3e/0x3f` 宽度 1

```
    FIELD_REF_STATIC 1019
    SHORTCUT_AND                      ; 宽度 1，不携带跳转目标！
    JMP -> L4                         ; 真正的跳过在这里
L3: FIELD_REF_QUICK 480
    NULL LITERAL
    INE
    ANDAND                            ; 真正的布尔与
L4: ...
```

`SHORTCUT_AND` 后面总跟着一条**无条件 `JMP`** 来做实际跳过 —— 所以它
**不可能携带 4 字节目标**，宽度 1 **从语义上被独立确认** ✓✓✓
这与上一轮「数据说 1、exe 收尾说双出口、强改 5 会让解析率掉到 98.21%」完全一致。

## 4. 反汇编样例（人类可读性验真）

完整样例见 **`out_disasm_sample.txt`**。取证式摘录：

**`Bet.5`（纯 getter）**
```
L0:  0  15 FIELD_REF_QUICK   (34)      ; 读实例字段 34
     5  16 RETURN
```

**`Hills.6`（构造函数，3,254 条）**
```
     0  0b LOCAL_LOAD   (0)      ; this
     5  0b LOCAL_LOAD   (2)
    10  0b LOCAL_LOAD   (1)
    15  11 INVOKESPECIAL (154)
    20  29 POP
    21  27 NEW          (159)
    26  2a DUP
    27  05 INT LITERAL  (32)
    32  11 INVOKESPECIAL (162)
    37  21 PUTFIELD_QUICK (157)          ; this.x = new Foo(32)
    42  0c LOCAL_CREATE
    43  27 NEW (164); 2a DUP; 08 STRING LITERAL (291); 05 INT LITERAL (10)
    59  11 INVOKESPECIAL (165); 0d LOCAL_STORE (3)
    69  0b LOCAL_LOAD (3); 05 INT LITERAL (11441513); 06 FLOAT LITERAL (0.5)
    84  05 INT LITERAL (5399151); 05 INT LITERAL (0); 10 INVOKE (169); 29 POP
   100  0b LOCAL_LOAD (0); 05 INT LITERAL (0)
   110  06 FLOAT LITERAL (1350.0)         ← 车辆/摄像机参数直接可读
   115  06 FLOAT LITERAL (10000.0)
   120  06 FLOAT LITERAL (0.0); (0.0)
   130  06 FLOAT LITERAL (0.026999998837709427)
   135  06 FLOAT LITERAL (0.0); 10 INVOKE (173); 29 POP
```

**`Track.37`（217 块状态机）**
```
L0:  0  15 FIELD_REF_QUICK (1186); 46 EXCLAMATION; 18 JMP_NE -> L2   ; if (!this.x)
L1: 11  16 RETURN
L2: 12  04 BOOL LITERAL (0); 21 PUTFIELD_QUICK (1276)                ; this.y = false
    22  14 FIELD_REF_STATIC (1019); 3e SHORTCUT_AND; 17 JMP -> L4
L3: 33  15 FIELD_REF_QUICK (480); 03 NULL LITERAL; 4b INE; 40 ANDAND ; x != null && …
L5: 46  15 FIELD_REF_QUICK (480); 08 STRING LITERAL (2288); 10 INVOKE (1283); 29 POP
L10:121 0b LOCAL_LOAD (0); 14 FIELD_REF_STATIC (1382); 10 INVOKE (778); 29 POP
        137 17 JMP -> L12
L11:142 0b LOCAL_LOAD (0); 15 FIELD_REF_QUICK (1360); 05 INT LITERAL (1); 31 ISUB
        158 10 INVOKE (778); 29 POP
L12:164 16 RETURN
```

**读起来完全自洽** —— `!x`、`x = false`、`x != null && …`、`this.x.foo("…")`、
`this.n - 1`、提前 return、if/else 链。**字节码语义已被证实，不是"看起来像"。**

## 5. 工具

| 工具 | 作用 |
|---|---|
| `tools/lasr_cfg.py --jumpbases` | 判定跳转基址（四个候选基址的分命中率对比） |
| `tools/lasr_cfg.py --stats` | 基本块 / 边 / 回边 / 可达性 / 循环分布 |
| `tools/lasr_cfg.py --idioms` | 控制流模式普查（短路、if、提前 return、对象分配…） |
| `tools/lasr_cfg.py --list` | 按块数 / 指令数排行的方法清单 |
| `tools/lasr_cfg.py --disasm <idx>` | **带块标号 + 已解析跳转目标 + 浮点字面量**的反汇编 |

```bash
python tools/lasr_cfg.py --jumpbases
python tools/lasr_cfg.py --stats
python tools/lasr_cfg.py --idioms
python tools/lasr_cfg.py --disasm 2455      # Track.37
```

## 6. 下一步

CFG 通了以后，剩下的都是**数值/语义绑定**（优先级：数值与规则 > 网格 > 贴图）：

1. **操作数 → 常量池 / 局部变量槽绑定**：`LOCAL_LOAD (1)` 的 1 是槽号已确认，
   但 `INVOKE (154)` / `FIELD_REF_QUICK (34)` / `STRING LITERAL (291)` 的索引
   指向 `CONS` 块的哪一项还没接上 → **接上就能读出方法名、字段名、字符串**。
2. **栈深度分析**：CFG 已可用，可算每条指令的栈高 → 反过来验证宽度表与操作数语义。
3. **不可达代码那 355 个方法**：查明来源（可能是 `while(true)` 或常量折叠）。
4. 然后才是把方法抬升成类 C 伪码 / 直接对重制引擎导出数值表。
