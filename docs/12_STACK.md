# 12 · 栈深度分析（抽象解释 / 栈效应求解）

> 状态：✅ **效应表求解完成** —— 全库 **98.83%** 方法同时满足四条不变量，**96.96%** 指令拿到确定栈高
> 工具：`tools/stack_depth.py`（`--solve` / `--verify` / `--export` / `--class <file>`）
> 产物：`out_stack_sem.json`（解出的效应表）、`out_stack_heights.json`（6.0 MB，逐指令栈高）
> 相关：`docs/08_VM_OPCODES.md`（指令编码/宽度）、`docs/09_CFG.md`（块与边）、`docs/11_CLASS_META.md`（`MTHD`）

---

## 1. 目标与判据

栈深度分析要把每条指令**执行前**的栈高算出来。这是抬升伪码（P2.7）和表达式重建的前提：
没有栈高就不知道 `DUP` 复制的是谁、`ARRAY_INIT n` 消费了几个值、`POP` 丢掉的
是哪个调用的返回值。

不用「猜一个效应表再试试」的做法，而是把栈效应当**约束满足问题**：

**四条硬不变量**（任一条破了就说明效应表或宽度表有错）

| # | 不变量 | 含义 |
|---|---|---|
| 1 | 不下溢 | 执行任何指令前高度 ≥ 它要弹的数量 |
| 2 | 返回元数 | `RETURN` 处高度 == 描述符的返回值个数（`V`/空 → 0，否则 1） |
| 3 | 全可达 | 每个基本块都能从偏移 0 到达（配合 `docs/09` 的 CFG） |
| 4 | 汇合一致 | 经不同路径到达同一指令时高度必须相同 |

其中 **2 和 4 是「独立第二判据」**：它们和「算出高度」不是同一件事，
而是对**调用描述符解析**（`docs/10`/`docs/11`）和**控制流建模**（`docs/09`）的交叉验证。

---

## 2. 效应表

### 2.1 固定项（语义明确，直接写死）

| op | 名称 | 弹,压 | 全库次数 | | op | 名称 | 弹,压 | 全库次数 |
|---|---|---|---|---|---|---|---|---|
| `01` | CAST | 1,1 | 558 | | `2a` | DUP | 1,2 | 12,323 |
| `02` | INSTANCEOF | 1,1 | 103 | | `2b` | DUP_X1 | 2,3 | 4 |
| `03`–`08` | 字面量 | 0,1 | 91,686 | | `2c` | DUP_X2 | 3,4 | 25 |
| `0b` | LOCAL_LOAD | 0,1 | 36,944 | | `2d` | DUP2 | 2,4 | 41 |
| `0d` | LOCAL_STORE | 1,0 | 6,851 | | `2e`–`3d` | 算术/转换 | — | 19,743 |
| `13` | FIELD_REF_INSTANCE | 1,1 | 4,250 | | `40`/`41` | ANDAND / OROR | 2,1 | 950 |
| `14` | FIELD_REF_STATIC | 0,1 | 18,215 | | `42`–`46` | 位运算/取反 | — | 1,150 |
| `15` | FIELD_REF_QUICK | 0,1 | 14,345 | | `47`–`49` | 移位 | 2,1 | 356 |
| `1f` | PUTFIELD_INSTANCE | 2,0 | 2,784 | | `4a`–`4f` | 整型比较 | 2,1 | 3,816 |
| `20` | PUTFIELD_STATIC | 1,0 | 5,911 | | `50`–`55` | 浮点比较 | 2,1 | 712 |
| `21` | PUTFIELD_QUICK | 1,0 | 6,815 | | `37`/`38`/`39`/`3b` | INEG/FNEG/IINC/IDEC | 1,1 | 4,508 |
| `22` | NEWARRAY | 1,1 | 2,260 | | `10`–`12` | INVOKE* | 描述符驱动 | 61,124 |
| `23` | ARRAY_STORE | 3,0 | 3,891 | | `16` | RETURN | 描述符驱动 | 16,836 |
| `26` | ARRAY_ACCESS | 2,1 | 2,934 | | `17` | JMP | 0,0 | 3,295 |
| `27` | NEW | 0,1 | 12,084 | | `29` | POP | 1,0 | 34,380 |

`*_QUICK` 系列 = **隐式 `this`**：读是 `(0,1)`（不动接收者），写是 `(1,0)`（只弹值）。
`FIELD_REF_INSTANCE` / `PUTFIELD_INSTANCE` 是显式形式，接收者占栈位。
`09 RID`、`28 DELETE`、`3a FINC`、`3c FDEC`、`49 LSR`、`0a` 全库 **0 次**——与 `docs/08`
「从未发射：`09 0a 28 3a 3c 49`」完全吻合（独立复核 ✓）。

### 2.2 未知项（爬山求解）

这些操作码的守卫副作用从字节码看不出来，列为未知量后用不变量当分数爬山：

```
UNKNOWN = { JMP_NE:[1,2], JMP_EQ:[(1,0),(2,0),(0,0)], JMP_EQ2:[...], SHORTCUT:[...],
            EMPTYDIMS:[...], DUP2:[...], LOCAL_CREATE:[...], LOCAL_CLEAR:[...],
            LOCAL_CLEARN:[...] }
```

爬山的**分数函数 = 满足全部四条不变量的方法数**，所以合法的取值域是硬约束，
不存在「解出一堆但都没用」的假解。最终 `out_stack_sem.json`：

| 名称 | 解 | 依据 |
|---|---|---|
| `JMP_NE` | 1 | 后面接 `IEQ` 的结果布尔，必须弹掉；跳转条件 = **顶值为假**（`== 0`） |
| `JMP_EQ` | (1,0) | 同族比较跳转，仅 16 处 |
| `JMP_EQ2` | **(1,0)** | ★ switch 链，见 §3.3 |
| `SHORTCUT` | **(0,0)** | ★ 偷看栈顶，见 §3.2 |
| `EMPTYDIMS` | (0,0) | 全库仅 1 次 |
| `DUP2` | (2,4) | 41 次，符合「复制两份双宽/双槽」 |
| `LOCAL_CREATE` | (0,0) | 纯槽位管理，不动栈 |
| `LOCAL_CLEAR` | (0,0) | 同上 |
| `LOCAL_CLEARN` | (0,0) | 同上 |
| `ARRAY_INIT n` | **(n+1, 1)** | ★ 数组字面量，见 §3.4 |

`ARRAY_INIT` 是唯一「净效果 -n 但弹压两种写法同分」的项：`(n+1,1)` 与 `(n,0)` 净效果都是 -n，
全库同分 **98.83%**。选 `(n+1,1)` 的理由是**它保住了数组引用** —— 后面紧跟的
`PUTFIELD_STATIC`/`PUTFIELD_QUICK` 还要把它存进字段（见 `Driver.<clinit>`：
8 个字符串字面量 + 长度 + `NEWARRAY` + `ARRAY_INIT 8` + `PUTFIELD_STATIC` 恰好需要留下 1 个值）。
`(n,0)` 是同一个净效果的错误物理解释，虽然分数相同但会让后续 `PUTFIELD` 无从取值。

---

## 3. 四条关键发现

### 3.1 `V` 返回的调用**仍然压 1 个单位值**；构造函数压 0

首跑 `stack_depth.py` 只有 82/400 —— 满屏 `POP` **下溢**。根因不是 `POP`，
而是「无返回值调用压 0」的假设错了。

统计全库「返回 `V` 的调用后面跟什么」：

| 调用种类 | 次数 | 后面跟 `POP` | 结论 |
|---|---|---|---|
| 构造函数（描述符 `()`，**连返回类型都省略**） | 14,572 | **0** | 压 0 |
| `()V` 方法 | 33,449 | **33,449 = 100.00%** | 压 1 个单位值 |
| 有返回值 | 13,103 | 701（= 表达式语句丢弃结果） | 压 1 |

**33,449/33,449 = 100.00%** 是铁证：`V` 调用压一个可被 `POP` 丢弃的单位值，
编译器对「语句式调用」总是补一条 `POP`。而构造函数用**完全省略返回类型**的
`()` 写法区分——既不能当「返回 1 个」也不能当 `V` 处理，必须按空尾特判。

> 这条同时修好了两类错误：269 处下溢 + 46 处返回元数不符。

### 3.2 `SHORTCUT_AND` / `SHORTCUT_OR` = **偷看栈顶** `(0,0)`

`Bet.getName()`（三元 `||` 链）把规则彻底暴露：

```
 18 FIELD_REF_QUICK betType         ; b
 23 FIELD_REF_STATIC BET_TYPE_PerformPart
 28 IEQ                            -> [b == PerformPart]
 29 SHORTCUT_OR     ← 偷看，不弹；为真则跳 47
 30 JMP -> 47
 35 FIELD_REF_QUICK betType
 40 FIELD_REF_STATIC BET_TYPE_StylingPart
 45 IEQ
 46 OROR            ← 弹 2 压 1，把两段折成一个
 47 SHORTCUT_AND
 48 JMP -> 61
 ...
```

- 跳过去的路径：栈顶**已经就是**那个布尔结果 ✓
- 落空的路径：继续把后半段算完，由 `OROR`/`ANDAND` 折进来 ✓

**两条路径在同一汇合点高度恰好相等**（都是 1）——这正是不变量 4 能证明它是对的。
同时它解决了 `docs/09` 的 CFG bug：`SHORTCUT_*` 后面那条 `JMP` 是**条件跳转**
（条件不成立就顺落），不是无条件跳转。修后不可达方法 355 → 68。

### 3.3 `JMP_EQ2` = **链式 switch 比较**（弹刚压入的常量，保留被比较的主体）

`Challenge.apply(I)V` 里一条完整的 switch：

```
 86 LOCAL_LOAD 3
 91 FIELD_REF_QUICK opponentBets
 96 ARRAY_ACCESS                    ; 取出 switch 主体
 97 INVOKE Bet.getBetType()I        ; 主体在栈上，全程不动
102 FIELD_REF_STATIC BET_TYPE_Prestige     ; 压常量
107 JMP_EQ2 -> 148                  ; 弹常量，与栈下主体比，相等则跳
112 FIELD_REF_STATIC BET_TYPE_PerformPart  ; 下一段
117 JMP_EQ2 -> 153
122 ... StylingPart
127 JMP_EQ2 -> 352
132 ... IVehicle
137 JMP_EQ2 -> 551
142 POP                             ; 最后一次丢掉主体
143 JMP -> 620                      ; default
148 JMP -> 620                      ; case 1：空体
153 LOCAL_CREATE …                  ; case 2 体
```

`(2,0)` **在结构上就不可能**：那样链条第二步自己就下溢（112 只压了 1 个）。
`(1,0)` 让整条链读得通顺，代价是下面 §4 的残留。

### 3.4 `MTHD` 版式修正（顺带挖出，是返回元数错误的根因）

做 §3.1 的时候发现 `ChallengeOffer` 的方法名解析出 `()` 这种鬼东西——
`MTHD` 头部在 Bet 上是 `(0, 7)`，在它上面是 `(13, 9)`，而 `TREE` 有 17 条记录。

真相：**`MTHD` 和 `FILD` 是同一个版式** ——「两组、计数夹中间」：

```
MTHD blob = <u32 n₁> + n₁ × <flags, name_idx, desc_idx, tree_index, n_locals>
            <u32 n₂> + n₂ × <同上 20 B 记录>
```

- **第 1 组 = 静态方法**（`flags & 8`），**第 2 组 = 实例方法**
- `tree_index` 是 1-based，`TREE` 记录 0 是编译器生成的 `<clinit>`（无 `MTHD` 条目）
- 判据：`len(tree_records) == n₁ + n₂ + 1`

`Bet` 是 `n₁=0`（全实例方法，所以固定 8 字节头刚好读对），`ChallengeOffer` 是
`n₁=13`（13 个静态工厂）+ `n₂=3`（构造函数，tree 1,2,3）。

**之前用「固定 8 字节头 + n 条记录」读，让所有 `n₁>0` 的类（约一半）方法名/描述符全错**，
`arity` 随之错，栈分析首先就在这里炸。修正后 `MTHD` 自身多了一条独立判据：
**组的静态性必须与调用指令一致**（第 1 组只能被 `INVOKESTATIC` 调、第 2 组只能被
`INVOKE`/`INVOKESPECIAL` 调）。

---

## 4. 结果

```
方法总数                  : 14,796
  四条不变量全满足        : 14,623 = 98.83%
  指令拿到确定栈高        : 370,773 / 382,399 = 96.96%
  汇合点高度分歧          : 507 处（编译器在 case 体路径上留了死值）
残留失败                  : return-arity 115、unreachable 58、下溢 0
```

**下溢 = 0** 很关键：说明效应表本身没有系统性错误（每条指令弹的数量都不超过实际可用的）。
剩下的每一类都能指到具体原因，而不是「还有 1.17% 不知道」：

### 4.1 `return-arity` 115 个：数组字面量/字段初始化器的 +1 泄漏

`ItemRoot.<i>()`（实例字段初始化器）整体净效果是 **+1**：

```
 60 [0] FIELD_REF_QUICK vehicles      ; 6 个连续字段读取，压 6 个
 65 [1] FIELD_REF_QUICK extras
 ...
 85 [5] FIELD_REF_QUICK maps
 90 [6] INT LITERAL 6                 ; 长度
 95 [7] INT LITERAL -1                ; 又一个长度/sentinel
100 [8] NEWARRAY 10
105 [8] ARRAY_INIT 6                  ; 弹数组 + 6 个值，压回数组 -> [2]
110 [2] PUTFIELD_QUICK lists          ; 弹 1 -> [1]
115 [1] RETURN                        ; 但方法返回类型是空 -> 应等于 0 ✗
```

`ARRAY_INIT` 的净效果无论怎么取（-n）都在这里差 1：编译器**多压了一个值没人消费**。
`Vehicle.<i>()` 是同一形状（整条方法基线高度就是 1，一路漏到 `RETURN`）。
这类代码在**不做校验的自研 JavaMachine** 上能跑（多余槽位是死值，没人读），
但任何全局一致的高度赋值都会被它顶住。

### 4.2 `unreachable` 58 个：switch case 体的孤立块

`Challenge.apply(I)V` 的 `148 JMP -> 620`（case 1 空体）与 default 路径
（`142 POP; 143 JMP -> 620`）在 620 汇合时高度差 **1**：case 体路径带着
switch 主体（`JMP_EQ2` 按 §3.3 保留了它），default 路径已经 `POP` 掉了。

**这是编译器自己产出的栈不平衡**，不是模型错：`(2,0)` 会让链条读不通、
`(0,0)` 汇合处差 4、`(1,0)` 恰好差 1——候选值穷举完了，没有能让两条路径同时一致的取值。
处理办法：`analyze()` 把「汇合分歧」当**软错误**（记录 + 首值优先，继续分析），
所以这些方法的大部分指令**仍然拿到高度**，只是标记 `conflicts > 0`。

> 结论：这 1.17% 不是「还没解出来」，而是**游戏自带编译器的栈不平衡痕迹**，
> 已被量化（507 处分歧、115 个方法溢到 RETURN）并给出具体例证。
> 对抬升伪码的影响：至多一个死槽位，按「每条路径各自的高度」取值即可。

---

## 5. 工具用法

```bash
PY=tools/../.venv/Scripts/python.exe    # 见 README 的环境说明

python tools/stack_depth.py --solve     # 爬山求解，写 out_stack_sem.json
python tools/stack_depth.py --verify    # 全库复验（四条不变量 + 指令覆盖率）
python tools/stack_depth.py --export    # 逐指令栈高 -> out_stack_heights.json (6.0 MB)
python tools/stack_depth.py --class extracted/java/classes/game/Bet.class
```

`--class` 输出示例（`Bet` 的静态初始化器）：

```
--- #0 <clinit>()V   ok=True    maxstack=1
      0 [ 0] 05 INT LITERAL           1
      5 [ 1] 20 PUTFIELD_STATIC       java.game.Bet.BET_TYPE_Prestige I
     10 [ 0] 05 INT LITERAL           2
     15 [ 1] 20 PUTFIELD_STATIC       java.game.Bet.BET_TYPE_PerformPart I
     ...
     60 [ 0] 16 RETURN
```

`[n]` = 该指令执行前的栈高。左边是偏移，右边是带名字的操作数。

`out_stack_heights.json` 结构（下一阶段抬升伪码直接消费）：

```json
{"java/classes/game/Bet.class#5":
  {"arity": 1, "locals": 2, "max": 1, "ok": true, "n_ins": 12, "conflicts": 0,
   "h": {"0": 0, "5": 1, "10": 0, ...}}}
```

没有 `ok:true` 的方法会带 `"fail": "return-arity"` 之类的标记，但 `h` 里仍是
**所有可达指令**的高度（最多差一个死槽位）。

---

## 6. 下一步（P2.7 抬升伪码）

栈高已就位，抬升需要的三样东西齐了：

| 需要 | 来源 | 状态 |
|---|---|---|
| 指令边界 + 操作数语义 | `docs/08` 宽度表 + `docs/10` 常量池 | ✅ |
| 控制流（块/边/环） | `docs/09` CFG | ✅ |
| 每指令栈高 + 局部槽数 | 本文 | ✅ |

抬升的切入点建议：**表达式树重建** —— 以 `RETURN`/`PUTFIELD`/`POP` 为「消费者」，
沿栈高差反向把生产者连成树（`DUP` 处理共享子表达式，`JMP_EQ2` 链还原成 `switch`）。
`NEW+DUP` 有 12,075 处，是最典型的共享子表达式模式。
