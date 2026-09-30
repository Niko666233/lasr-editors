# P2 — LASR 的自研 Java VM / 编译器：实测结论

> 本文只记录**有二进制实证**的结论。推测部分单独标注。[HYP] = 假设，未证实。

## 1. 结论：TUFA 不是一个静态类格式，而是一个"运行时编译产物"

`.rdata` 里的字符串是决定性证据：

| 字符串（VA） | 含义 |
|---|---|
| `Cannot parse class "%s" at line %d in file "%s"` @ `0x72401c` | 解析类时保留**源码行号与文件** |
| `JavaMachine::loadClass: failed to load ` @ `0x724470` | 加载器 |
| `JVM::addClass: unknown chunk` @ `0x7241d8` | 按 chunk 名分派（CONS/FILD/MTHD/CLSS/TREE） |
| `JVM::compileHook: invalid arguments` @ `0x7245fc` | 存在**编译钩子** |
| `internal compiler error 1512 / 3041 / 3240 / 3300` @ `0x7240cc`... | 手写编译器里的 assert |
| `JVM::numericPromotion` / `JVM::stringConversion` | 正规的 Java 语义实现 |
| `ambiguous class name, multiple choices possible:` / `bad import decl.` | **import 解析** |
| `finalize() misses to call super.finalize()!` | 运行时检查 |
| `JVM::getTypeName: tulirsz egy tombon! :)` @ `0x7244fc` | 匈牙利开发者玩笑（"你在墓碑上挖过头了"） |

**判定：Invictus 自研了一整套 Java 编译器 + JVM，嵌在 `LASR.exe` 里。**
类格式里保存行号 → 说明它把源码编译成 `TREE` 节点树，并保留调试信息。

## 2. 运行时节点（node）结构体 — 已由反汇编确定

`getType` 是一个 3 字节函数：

```asm
; RVA 0x2595f0  Node::getType()
movzx eax, word ptr [ecx + 0x14]     ; 类型是 u16 @ +0x14
ret
```

同域内的其它 tiny 访问器确定了字段布局：

| 偏移 | 类型 | 含义（实证） |
|---|---|---|
| `+0x0C` | ptr | 父/兄弟链（`isProductive` 用它向上走并打印 "unknown **parent** node type"） |
| `+0x14` | u16 | **节点类型** |
| `+0x16` | u16 | 第二个类型/子类型字段（`0x259600` = setter，`0x259610` = getter） |
| `+0x18` | f32 | 浮点操作数（`fld dword ptr [ecx+0x18]`） |

## 3. `JavaMachine::isProductive` — 节点类型合法性表（实测）

`isProductive(node)` @ RVA **`0x244A30`**，被 RVA `0x2504D1` 调用。

顶层节点类型必须属于：

```
0x2E .. 0x3D       (16 个)
0x42 .. 0x55       (20 个)
0x108E
```

子节点查表分派：

```asm
mov  ecx, [esi + 0x0C]        ; 子/父节点
call Node::getType
cmp  eax, 0xAC   ; je  -> productive
sub  eax, 0x0C
cmp  eax, 0x9A   ; ja  -> error
movzx eax, byte ptr [eax + 0x644BA0]   ; ← 字节索引表，155 项
jmp  dword ptr [eax*4 + 0x644B90]      ; ← 4 项跳转表
```

**跳转表**（VA `0x644B90`，即 RVA `0x244B90`）：

| 索引 | 目标 | 语义 |
|---|---|---|
| 0 | `0x244B83` `mov eax,1` | LEAF → productive |
| 1 | `0x244AD8` | RECURSE → 继续看子节点 |
| 2 | `0x244B7A` `xor eax,eax` | 非 productive |
| 3 | `0x244B0D` | 报错 |

**字节索引表**（VA `0x644BA0`，155 项，索引 = `type - 0x0C`）：

| 索引 | 节点类型 | 值 | 语义 |
|---|---|---|---|
| `0x00` | `0x0C` | 0 | **LEAF**（唯一无子节点的类型） |
| `0x22`–`0x29` | `0x2E`–`0x35` | 1 | RECURSE |
| `0x2A`–`0x31` | `0x36`–`0x3D` | 1 | RECURSE |
| `0x36`–`0x49` | `0x42`–`0x55` | 1 | RECURSE |
| `0x9A` | `0xA6` | 2 | 非 productive |
| 其余 | | 3 | 未知 → 报错 |

`0xAC` 短路返回 productive；`0xAE`/`0xAF`/`0xB1`/`0x108E` 同样返回 productive；`0xB5` 返回非 productive。
（来源：`0x244AE0`–`0x244B0C` 的分支链。）

**含义**：有 **1 个叶类型 + 36 个容器类型 + 若干特殊类型**。这说明 LASR 的代码表示是
**语法树**（容器节点 = 语句/表达式，叶节点 = 终结符），不是栈式字节码 —— 与
`.rdata` 里那批 opcode 名字吻合。

## 4. 操作码 / 节点名表（.rdata，VA `0x723F1C`–`0x7240CC`）

这是从编译器内部挖出来的**完整名字表**（原文照抄，含原版拼写错误）：

```
EXCLAMATION  ANDAND  SHORTCUT_OR  SHORTCUT_AND
DUP_X2  DUP_X1  DELETE  ARRAY_ACCESS  EMPTYDIMS  ARRAY_INIT
ARRAY_STORE  NEWARRAY
PUTFIELD_QUICK  PUTFIELD_STATIC  PUTFIELD_INSTANCE
JMP_EQ2  JMP_EQ  JMP_NE  RETURN
FIELD_REF_QUICK  FIELD_REF_STATIC  FIELD_REF_INSTANCE
INVOKESTATIC  INVOKESPECIAL  INVOKE
LOCAL_CLEARN  LOCAL_CLEAR  LOCAL_STORE  LOCAL_CREATE  LOCAL_LOAD
RID LITERAL   <-- 原版笔误，应为 INT LITERAL
STRING LITERAL  CHAR LITERAL  FLOAT LITERAL  INT LITERAL
BOOL LITERAL  NULL LITERAL
INSTANCEOF  CAST  N/A
```

字段访问的 VM 内建（同一区域）：

```
vm_get_int_field  vm_get_float_field  vm_get_instance_field  vm_fieldcheck
vm_set_int_field  vm_set_float_field  vm_set_instance_field
vm_set_instance_array_field  vm_get_it_field
```

错误串：`vm_get_int_field: unknown field: ` / `null::` 、
` is not compatible with '` 、`vm_set_instance_array_field: `。

> ✗ **未证实**：这些名字到数字编号的映射。`INSTANCEOF`/`CAST`/`N/A` 后面紧跟一张
> **恰好 12 项的代码指针跳转表**（VA `0x723F9C`，紧邻 `.java` 字符串之前），
> 但**没有**找到指向这些名字字符串的指针数组或 `.text` 立即数引用（在 `.text` 里
> `0x72xxxx` 的 VA 出现 0 次，作为 RVA 也 0 次）。因此名字是按 `switch` 的每个
> `case` 各自 `push` 自己的名字，编号顺序需另行确定。

## 5. `TREE` chunk = 每方法一段代码（实证）

`TREE` 载荷结构已在 **2224 / 2224 个类**上精确闭合：

```
u32 count
count × ( u32 size ; size bytes )
```

- 共 **14 879** 条记录 / **2224** 个类
- 记录条数与类的方法数吻合（例：`java/game/Bet.class` 有 3 个 `<init>` + 5 个方法 = 8 条记录）

### 记录 = 帧序列

帧 = `<u8 opcode> [operand]`，**`0x16` 是终止符：14 869 / 14 879 条记录以 0x16 结尾（99.93%）**。

由 `java/game/Bet.class` 记录 0（61 字节）**逐字节精确闭合**得到：

```
05 01000000 | 20 24000000
05 02000000 | 20 37000000
05 03000000 | 20 39000000
05 04000000 | 20 40000000
05 05000000 | 20 5b000000
05 06000000 | 20 5d000000
16
```
= 6 × (`0x05` + u32) + (`0x20` + u32)，共 6 组 → 与该类 **6 个字段**的默认值初始化一致
（`FILD` 的 count 也是 6；操作数 `0x24,0x37,0x39,0x40,0x5b,0x5d` 是常量池索引）。

记录 1（43 字节）同样精确闭合：

```
0b 00000000 | 11 20000000 | 14 24000000 | 21 22000000 |
0b 01000000 | 21 26000000 | 03 |
21 28000000 | 03 | 21 2c000000 | 16
```

由此确定的操作数宽度（**在样本上精确闭合，非猜测**）：

| opcode | 操作数字节 | 证据 |
|---|---|---|
| `0x03` | 0 | 记录 1 精确闭合 |
| `0x16` | 0 | 14869/14879 记录末尾 |
| `0x05` | 4 | 记录 0 |
| `0x0b` | 4 | 记录 1 |
| `0x11` | 4 | 记录 1 |
| `0x14` | 4 | 记录 1 |
| `0x20` | 4 | 记录 0 |
| `0x21` | 4 | 记录 1 |

> ✗ **未完成**：全量 14879 条记录的操作数宽度表。
> 尝试过**纯约束传播**（把"某 opcode 在任何合法解析中只出现一种宽度"钉死为全局宽度，
> 迭代到不动点）：**失败**——因为允许宽度 0 时，几乎任何位置都能自成一帧，
> 可及性图过密，无 opcode 能被钉住。这个方向已被证伪，需要**真实解析器**。
> `isProductive` 的字节索引表惯用法（`movzx`+`jmp`）在 `.text` 里只出现 12 处，
> 且都不在 VM 区域；节点类型载入（`movzx r32, word ptr [reg+0x14]`）只有 6 处，
> 附近**没有**跳转表 → 分派器编译成了 **cmp 链**，需要逐函数追踪。

## 6. TUFA 容器权威布局

```
offset 0   "TUFA"
offset 4   u32 version = 4
offset 8   u32 0
offset 12  重复: <4 字节 chunk 标签> <u32 payload 大小> <payload>
```

chunk 标签：`CONS`（常量池）、`FILD`（字段）、`MTHD`（方法）、`CLSS`（类）、`TREE`（代码）。

各 chunk 载荷记录格式（实测）：

| chunk | 格式 | 验证情况 |
|---|---|---|
| `TREE` | `u32 count` + `count × (u32 size, bytes)` | ✅ 2224/2224 精确闭合 |
| `CLSS` | 24 字节定长 | ✅ 尺寸恒定 |
| `FILD` | 见下 | ⚠ 部分 |
| `MTHD` | 见下 | ⚠ 部分 |
| `CONS` | 常量池 | ⚠ 未解 |

`FILD` 样本（`Model_Coupe_TornadoR.class`，88 字节）：
`05 000000 | 08 000000 71 000000 04 000000 00 000000 | 08 000000 72 000000 ...`
→ 首 u32 = 记录数（5），随后 `(u32 size, size bytes)`；每个 8 字节记录 =
`<u32 常量池索引><u32 类型/标志>`。这与字段名从 `CONS` 取值一致。

`MTHD` 样本（`Bet.class`，148 字节）是一串小整数（`07,01,14,13,01,02,01,14,15,02,03,10,13,...`），
不满足 `(size, blob)` 格式，**尚未解出**。

## 7. 仍然未知（写进路线图 P2.3）

1. `TREE` 帧 opcode → 语义 的完整编号（需要逐函数反汇编 VM 主循环）
2. `CONS` / `MTHD` / `FILD` 的权威布局
3. 本地方法绑定表（`.rdata` 里有 300+ 条 `java.*` 签名，可作为交叉验证）
4. `.rdata` 两张节点类型表：RVA `0x31E7A8`（81 项，类型 0x2E–0x3D，重数
   `5,4,5,4,5,5,5,5,5,5,5,6,5,6,5,6`）与 RVA `0x325724`（32 项，类型 0x43–0x4C）
   —— 没有找到任何代码引用，**用途未定**
