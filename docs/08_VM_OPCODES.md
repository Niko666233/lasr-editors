# P2.2 —— VM 操作码：**排列与名字已彻底钉死**

> **修正后的映射不是单一反转，而是分段的**（见 §5）：
> ```
> opcode 0x01..0x09  →  names[84 - opcode]     ; CAST … RID LITERAL
> opcode 0x0a        →  （保留：无 handler、全库 0 次）
> opcode 0x0b..0x55  →  names[85 - opcode]     ; LOCAL_LOAD … FLE
> opcode 0x00 / >0x55 → 非法
> ```
> 指令编码 = `<u8 opcode>` + 可选 **4 字节**操作数。
> **14,796 条 method record 里 14,796 条（100.00%）精确解析。**
> **完整代码（含尾 RETURN）= 382,399 条指令 / 1,475,195 字节，均 3.86 B/条**
> （`367,603` 是剥离尾字节口径，见 `docs/09_CFG.md` §0 的修正）。
> **宽度表与 exe 自己的 handler 收尾判据零分歧（§5.5）。**

## 0. 本轮修掉的三个我自己的错误

**(a) 地址空间混用**：`VA = ImageBase(0x400000) + RVA`，且本 exe `.text`/`.rdata` 的
**RVA == 文件偏移**。`VA 0x723ca4 → 文件 0x323ca4`。

**(b) 名字表漏项**：名字表**不是** NUL 分隔串，而是**按 4 字节边界对齐**的槽：

```
+0x323cf0 'XOR'   +0x323cf4 'OR'    +0x323cf7 <pad>
+0x323cf8 'AND'   +0x323cfc 'OROR'  +0x323d01..03 <pad>
+0x323d04 'ANDAND'
```

旧抽取器**把 `OR` 漏了** → `XOR` 之后下标全少 1。补齐后共 **85 项**（`OR` 在下标 18）。

**(c) 🚨 两个把我自己带偏的 bug（本轮才发现）**

1. **上一轮假设「分派表的槽号 = 操作码」** —— 读 `0x653900` 分派点后证伪：
   实际是 **`handler[opcode - 1]`**（§5.1），整个映射差 1。
2. **`lasr_vm.walk()` 返回 `(pos, op, w, pay)`，我的分析脚本按 `(op, pos, w, pay)` 解包**
   —— 于是「每个操作码的载荷画像」其实是**按记录内偏移**的直方图，**整批作废**。
   正确字段序重算后数据完全变了（例如 `0x0b` 从"4,451 次"变成 **36,120 次**）。

> 教训：`walk` 的 docstring 明写了字段序，我却按记忆解包。**凡是多元组，先读 docstring。**
> 另外，"按某个键分组统计"的表若键的取值分布异常（如 100% 的"操作码 0"、
> 或某操作码"0 次出现"），那就是解包错了的典型指纹 —— 本轮正是靠这个指纹抓到的。

## 1. 先修正一个坐标错误

之前记录的「VM/编译错误串表 VA `0x723a98`，38/47 串定位，0 指针槽」有两个问题：

* `0x723a98` 超过 `SizeOfImage`(0x51D000) —— 它其实是**虚拟地址**而节表里存的是 RVA，
  之前把两者混用了。`VA = ImageBase(0x400000) + RVA`，且本 exe 的
  `.text`/`.rdata` 的 **RVA == 文件偏移**，所以 `VA 0x723a98 → 文件 0x323a98`。
* 那 47 个名字只是散落在错误串之间，**不是一张表**。

## 2. 🎯 操作码名字表（完整 85 项，按地址升序）

`.rdata` 里一段**连续、按地址升序的 85 个 NUL 结尾字符串**：

| | | | | |
|---|---|---|---|---|
| `0x723ca4` FLE | `0x723ca8` FLT | `0x723cac` FGE | `0x723cb0` FGT | `0x723cb4` FNE |
| `0x723cb8` FEQ | `0x723cbc` ILE | `0x723cc0` ILT | `0x723cc4` IGE | `0x723cc8` IGT |
| `0x723ccc` INE | `0x723cd0` IEQ | `0x723cd4` LSR | `0x723cd8` ASL | `0x723cdc` ASR |
| `0x723ce0` EXCLAMATION | `0x723cec` NOT | `0x723cf0` XOR | **`0x723cf4` OR** ← 之前漏掉 | `0x723cf8` AND |
| `0x723d04` ANDAND | `0x723d0c` SHORTCUT_OR | `0x723d18` SHORTCUT_AND | `0x723d28` MOD | `0x723d2c` FDEC |
| `0x723d34` IDEC | `0x723d3c` FINC | `0x723d44` IINC | `0x723d4c` FNEG | `0x723d54` INEG |
| `0x723d5c` FMUL | `0x723d64` IMUL | `0x723d6c` FDIV | `0x723d74` IDIV | `0x723d7c` FSUB |
| `0x723d84` ISUB | `0x723d8c` FADD | `0x723d94` IADD | `0x723d9c` SADD | `0x723da4` DUP2 |
| `0x723dac` DUP_X2 | `0x723db4` DUP_X1 | `0x723dbc` DUP | `0x723dc0` POP | `0x723dc4` DELETE |
| `0x723dcc` NEW | `0x723dd0` ARRAY_ACCESS | `0x723de0` EMPTYDIMS | `0x723dec` ARRAY_INIT | `0x723df8` ARRAY_STORE |
| `0x723e04` NEWARRAY | `0x723e10` PUTFIELD_QUICK | `0x723e20` PUTFIELD_STATIC | `0x723e30` PUTFIELD_INSTANCE | `0x723e44` F2S |
| `0x723e48` I2S | `0x723e4c` I2F | `0x723e50` F2I | `0x723e54` JMP_EQ2 | `0x723e5c` JMP_EQ |
| `0x723e64` JMP_NE | `0x723e6c` JMP | `0x723e70` RETURN | `0x723e78` FIELD_REF_QUICK | `0x723e88` FIELD_REF_STATIC |
| `0x723e9c` FIELD_REF_INSTANCE | `0x723eb0` INVOKESTATIC | `0x723ec0` INVOKESPECIAL | `0x723ed0` INVOKE | `0x723ed8` LOCAL_CLEARN |
| `0x723ee8` LOCAL_CLEAR | `0x723ef4` LOCAL_STORE | `0x723f00` LOCAL_CREATE | `0x723f10` LOCAL_LOAD | `0x723f1c` RID LITERAL |
| `0x723f28` STRING LITERAL | `0x723f38` CHAR LITERAL | `0x723f48` FLOAT LITERAL | `0x723f58` INT LITERAL | `0x723f64` BOOL LITERAL |
| `0x723f74` NULL LITERAL | `0x723f84` INSTANCEOF | `0x723f90` CAST | `0x723f98` N/A | |

* 表内**没有指针数组**（全文件搜各名字只出现 1 次）→ 它是**一整块字符串**
* 分组完全是语义化的：比较 → 位运算 → 算术 → 栈 → 字段 → 跳转 → 局部变量 →
  字面量 → 收尾，**是手写枚举的顺序**
* 数组下标 84 的 `N/A` **不是操作码**，是「非法/无」哨兵
  —— 与 §5.1 分派点的「`opcode 0` 非法」判定吻合

## 3. 🎯 指令编码（已解）

```
06 33 33 13 40                -> <op 06><f32 2.3>        FLOAT LITERAL
06 9a 99 d9 3f                -> <op 06><f32 1.7>        FLOAT LITERAL
08 6c 00 00 00                -> <op 08><串池下标 108>   STRING LITERAL
0b 00 00 00 00 10 3f 00 00 00 29   -> [0b|0][10|63][29]   5+5+1
```

**格式：`<u8 opcode>` + 可选 **4 字节载荷**（整数索引 / f32 字面量 / 有符号跳转偏移）。**

### 宽度怎么解出来的

per-record 穷举会爆（长度 L 的体有 ~Fib(L) 种切法），所以用**全局爬山**：

* **目标函数**：所有 record 中「载荷合理」的数量。合理 = 整数 `< 2^24`（索引）
  或有限且 `|v| < 1e6` 的浮点（字面量）。错位解析会把相邻指令字节当载荷，
  而随机 4 字节窗口几乎不可能同时满足这两条 → **判别力极强**
* **硬约束**：操作码字节 `<= MAX_OP`
* **种子**：直接从 record 体读出的无载荷操作码

| 指标 | 值 |
|---|---|
| TREE method record | **14,796** |
| 精确解析（切到末尾、不多不少） | **14,796 / 14,796 = 100.00%** |
| 指令总数 | **367,603**（1,460,399 字节，均 3.97 字节/条） |
| 无载荷操作码 | **55** 个（见 §5.4/§5.5） |

### 记录终止符

每条 record 以**单独的 `0x16` 字节**结束（14,796/14,805 = 99.9%）。
`0x16` = **RETURN**（§5.2），无载荷，体内另出现 **2,006 次**
→ **方法以 RETURN 结尾**，语义完全自洽（旧文档猜的 JMP 是错的，但宽度与计数正确）。

## 4. 每个操作码的载荷画像（**已按 walk 真实字段序重算**）

| opcode | 名字 | 出现次数 | 首条 | 末条 | 最常见载荷 |
|---|---|---|---|---|---|
| `0x0b` | **LOCAL_LOAD** | **36,120** ← 全库第一 | 16.9% | 2.3% | `0`×16,032、`1`×9,089、`2`×3,469 |
| `0x29` | **POP** | 34,198 | — | 15.0% | 无载荷 |
| `0x06` | **FLOAT LITERAL** | 31,237 | 1.8% | 0.6% | `0.0f`×10,367、**`1.0f`×2,021**、`0.5f`×55 |
| `0x05` | **INT LITERAL** | 27,603 | 0.8% | 3.1% | `0`×6,157、`1`×3,798、`2`×1,728 |
| `0x08` | **STRING LITERAL** | 25,713 | 2.7% | 2.2% | 小整数（串池下标） |
| `0x12` | INVOKESTATIC | 24,206 | 5.2% | 5.0% | `32`×6,578 |
| `0x10` | INVOKE | 19,286 | — | 0.5% | `66`×899 |
| `0x14` | FIELD_REF_STATIC | 16,977 | 11.7% | 0.9% | `68`×1,417 |
| `0x11` | INVOKESPECIAL | 16,356 | — | 12.5% | `37`×1,692 |
| `0x15` | FIELD_REF_QUICK | 13,449 | 9.6% | 1.7% | `44`×621 |
| `0x2a` | **DUP** | 12,287 | — | — | 无载荷 |
| `0x27` | NEW | 12,066 | 4.6% | — | `34`×1,434 |
| `0x00` | **（非法）** | **9,950** ⚠ | — | — | 无载荷 → **宽度表在此处仍有局部错** |
| `0x21` | PUTFIELD_QUICK | 6,245 | — | 15.9% | `44`×371 |
| `0x0d` | LOCAL_STORE | 6,075 | — | — | `1`×1,972、`2`×991 |
| `0x20` | PUTFIELD_STATIC | 5,871 | — | 18.5% | `80`×424 |
| `0x1c` | I2F ⚠ | 5,601 | — | — | 见 §5.5 |
| `0x0c` | **LOCAL_CREATE** | 4,914 | **40.0%** ← 序言 | — | **无载荷** |
| `0x13` | FIELD_REF_INSTANCE | 4,145 | — | 0.2% | `53`×640 |
| `0x18` | JMP_NE | 3,917 | — | 0.1% | `11`×383（跳转偏移） |
| `0x38` | FNEG | 3,354 | — | — | 无载荷 |
| `0x36` | FMUL | 3,152 | — | — | 无载荷 |
| `0x2e` | SADD | 2,898 | — | 19.7% | 无载荷 |
| `0x26` | ARRAY_ACCESS ⚠ | 2,838 | — | 0.7% | 无载荷 |
| `0x03` | **NULL LITERAL** | 2,681 | 2.6% | 4.0% | **无载荷** |
| `0x17` | **JMP** | 2,462 | — | 2.2% | `10`×130（跳转偏移） |
| `0x1a` | **JMP_EQ2** | 2,334 | — | — | `51`×70（跳转偏移） |
| `0x23` | ARRAY_STORE | 2,292 | — | 2.1% | 无载荷 |
| `0x22` | NEWARRAY | 2,258 | — | 0.1% | `4`×745、`7`×653 |
| `0x16` | **RETURN** | 2,006（+14,796 终止） | — | — | 无载荷 |

**关键读法**：`0x0b` 载荷是 `0/1/2`（`this` 与头两个局部变量）且 16.9% 出现在方法第一条
—— 与 handler 的越界检查语义完全咬合（§5.2）。`0x0c` 无载荷且 40% 在方法第一条
—— 正是「开场创建局部变量」。

## 5. 🎯 排列：分段映射（本轮彻底定案）

### 5.1 🎯 分派点反汇编（最硬的一环，`tools/dis_va.py`）

```
0x6538f0  8b7e28            mov   edi, dword ptr [esi + 0x28]   ; edi = 指令流指针
0x6538f3  0fbe07            movsx eax, byte ptr [edi]          ; eax = 有符号操作码
0x6538f6  48                dec   eax                          ; ★ eax = opcode - 1
0x6538f7  83f854            cmp   eax, 0x54
0x6538fa  0f879b040000      ja    0x653d9b                     ; 越界 → 共用兜底路径
0x653900  ff2485704b6500    jmp   dword ptr [eax*4 + 0x654b70] ; handler[opcode - 1]
```

**三条硬事实：**
1. **表索引 = 操作码 − 1**，所以 **操作码枚举是 1-based**（`0x01..0x55` = 1..85 共 85 个）
2. **`0x00` 与 `> 0x55` 是非法操作码**（0 → `eax = 0xFFFFFFFF` → `ja` 触发）
3. **`[esi+0x28]` 就是指令流指针**（handler 一律以 `[edi+1]` 读载荷，`edi` 即操作码位置）

### 5.2 🎯 handler 语义独立确认（20+ 个分组全部落在预测位置）

| slot | =opcode | 名字（修正后） | handler 行为（capstone 反汇编） |
|---|---|---|---|
| 3,4,5,6 | 0x04–0x07 | NULL/BOOL/INT/FLOAT LITERAL | **四槽共用**：`mov eax,[edi+1]; push eax`（压 4 字节立即数） |
| 7 | 0x08 | **CHAR LITERAL** | `mov di, word ptr [edi+1]` —— **只读 2 字节** ✅ CHAR 就是 2 字节 |
| 8 | 0x09 | STRING LITERAL | `mov edi,[edi+1]` 后查 `[[esi+0x24]+0xa0]` 池 → 串池查找 ✅ |
| **9** | **0x0a** | **（保留）** | **表项 = `0x653d9b` = 越界跳转的那个地址 → 无专属 handler** 🎯 |
| 10 | 0x0b | **LOCAL_LOAD** | `mov edi,[edi+1]` → `cmp dword ptr [eax], edi` / `test edi,edi; jl` → `mov ecx,[eax+4]; mov edi,[ecx+edi*4]` = **越界检查 + 槽位数组取值** 🎯🎯 |
| 11 | 0x0c | LOCAL_CREATE | `mov ecx,[esi+0x24]; push 0; call` —— **不读 `[edi+1]`** → 无载荷 ✅（40% 在方法第一条） |
| 12 | 0x0d | LOCAL_STORE | `call 0x652f10`（弹栈）后存槽 |
| 13 | 0x0e | LOCAL_CLEAR | `mov ecx,[esi+0x24]; call 0x652f60` |
| 14 | 0x0f | **LOCAL_CLEARN** | 读载荷后 **`mov ecx,[eax+8]` 循环清空全部槽位** 🎯 语义自证 |
| 15 | 0x10 | INVOKE | 查 `[eax+0x14]` 符号表 → `call 0x6537a0` |
| 21 / 22 / 23 / 24 / 25 | 0x16–0x1a | **RETURN / JMP / JMP_NE / JMP_EQ / JMP_EQ2** | slot 22 **全表唯一**做相对跳转：`mov edx,[edi+1]; add edx,edi` ✅ |
| 26–29 | 0x1b–0x1e | F2I / I2F / I2S / F2S | 4 槽同形（类型转换组）✅ |
| 30–32 | 0x1f–0x21 | PUTFIELD_INSTANCE / STATIC / QUICK | 3 槽同形 ✅ |
| 33–39 | 0x22–0x28 | NEWARRAY…DELETE | 7 槽连续 ✅ |
| 40–44 | 0x29–0x2d | POP / DUP / DUP_X1 / DUP_X2 / DUP2 | 5 槽连续 ✅ |
| 45–53 | 0x2e–0x36 | SADD…FMUL | **9 槽全是 `call 0x652f10`（弹操作数）** ✅ |
| 61,62 | 0x3e,0x3f | SHORTCUT_AND / SHORTCUT_OR | `call; test eax,eax` + 条件分支 ✅ |
| 70–72 | 0x47–0x49 | ASR / ASL / LSR | 3 槽连续 ✅ |
| 73–78 | 0x4a–0x4f | IEQ…ILE | 6 槽同形（整数比较）✅ |
| 79–84 | 0x50–0x55 | FEQ…FLE | 6 槽同形（浮点比较）✅ |

**每个语义分组都精确落在预测的操作码上** —— 排列由第二套完全独立的机制确认。

### 5.3 🎯 为什么是**分段**映射：枚举里有一个空洞

| 证据 | 内容 |
|---|---|
| **分派表** | slot 9 的表项 = `0x653d9b`，与越界跳转目标**同一地址** → `0x0a` 无 handler |
| **出现次数** | **`0x0a` 全库出现 0 次**（361,971 条指令里一次都没有） |
| **计数闭合** | 真操作码 = `0x01..0x09`(9) + `0x0b..0x55`(75) = **84**；真名字 = 下标 `0..83`（CAST…FLE）= **84**，下标 84 的 `N/A` 正好是哨兵 → **84 = 84，数目闭合** |
| **字面量区载荷** | `0x03` 无载荷 / `0x04` 只有 0-1 / `0x05` 是 0,1,2 / `0x06` 是 `0.0f`,`1.0f`,`0.5f` / `0x07` 是 `'.'` / `0x08` 是 25,713 个串下标 / `0x09` 只 4 次 —— **七个锚点全部对上 `names[84-opcode]`** |

所以映射必须分段：

```
opcode 0x01..0x09  →  names[84 - opcode]    ; CAST INSTANCEOF NULL BOOL INT FLOAT CHAR STRING RID
opcode 0x0a        →  （保留：枚举有值，但无名、无 handler、编译器从不发射）
opcode 0x0b..0x55  →  names[85 - opcode]    ; LOCAL_LOAD … FLE
```

**等价的统一说法**：名字数组是「**去掉保留值 `0x0a` 之后**的操作码枚举的反序」。

### 5.4 完整 opcode → 名字（85 项，修正后）

| op | 名字 | 宽 | op | 名字 | 宽 | op | 名字 | 宽 |
|---|---|---|---|---|---|---|---|---|
| 00 | **（非法）** | — | 1d | I2S | 1 | 3a | FINC | 1 |
| 01 | CAST | 5 | 1e | F2S | 1 | 3b | IDEC | 1 |
| 02 | INSTANCEOF | 5 | 1f | PUTFIELD_INSTANCE | 5 | 3c | FDEC | 1 |
| 03 | NULL LITERAL | 1 | 20 | PUTFIELD_STATIC | 5 | 3d | MOD | 1 |
| 04 | BOOL LITERAL | 5 | 21 | PUTFIELD_QUICK | 5 | 3e | SHORTCUT_AND | 1 |
| 05 | INT LITERAL | 5 | 22 | NEWARRAY | 5 | 3f | SHORTCUT_OR | 1 |
| 06 | **FLOAT LITERAL** | 5 | 23 | ARRAY_STORE | 1 | 40 | ANDAND | 1 |
| 07 | CHAR LITERAL | 5 | 24 | ARRAY_INIT | 5 | 41 | OROR | 1 |
| 08 | STRING LITERAL | 5 | 25 | EMPTYDIMS | 5 | 42 | AND | 1 |
| 09 | RID LITERAL | 5 | 26 | ARRAY_ACCESS | 1 | 43 | OR | 1 |
| 0a | **（保留）** | — | 27 | NEW | 5 | 44 | XOR | 1 |
| 0b | **LOCAL_LOAD** | 5 | 28 | DELETE | 5 | 45 | NOT | 1 |
| 0c | LOCAL_CREATE | 1 | 29 | **POP** | 1 | 46 | EXCLAMATION | 1 |
| 0d | LOCAL_STORE | 5 | 2a | **DUP** | 1 | 47 | ASR | 1 |
| 0e | LOCAL_CLEAR | 1 | 2b | DUP_X1 | 1 | 48 | ASL | 1 |
| 0f | LOCAL_CLEARN | 5 | 2c | DUP_X2 | 1 | 49 | LSR | 1 |
| 10 | INVOKE | 5 | 2d | DUP2 | 1 | 4a | IEQ | 1 |
| 11 | INVOKESPECIAL | 5 | 2e | SADD | 1 | 4b | INE | 1 |
| 12 | INVOKESTATIC | 5 | 2f | IADD | 1 | 4c | IGT | 1 |
| 13 | FIELD_REF_INSTANCE | 5 | 30 | FADD | 1 | 4d | IGE | 1 |
| 14 | FIELD_REF_STATIC | 5 | 31 | ISUB | 1 | 4e | ILT | 1 |
| 15 | FIELD_REF_QUICK | 5 | 32 | FSUB | 1 | 4f | ILE | 1 |
| 16 | **RETURN**（终止符） | 1 | 33 | IDIV | 1 | 50 | FEQ | 1 |
| 17 | **JMP** | 5 | 34 | FDIV | 1 | 51 | FNE | 1 |
| 18 | JMP_NE | 5 | 35 | IMUL | 1 | 52 | FGT | 1 |
| 19 | JMP_EQ | 5 | 36 | FMUL | 1 | 53 | FGE | 1 |
| 1a | JMP_EQ2 | 5 | 37 | INEG | 1 | 54 | FLT | 1 |
| 1b | F2I | 1 | 38 | FNEG | 1 | 55 | FLE | 1 |
| 1c | I2F | 1 | 39 | IINC | 1 | | | |
| 1d | I2S | 1 | 3a | FINC | 1 | | | |
| 1e | F2S | 1 | 3b | IDEC | 1 | | | |
| 1f | PUTFIELD_INSTANCE | 5 | 3c | FDEC | 1 | | | |
| 20 | PUTFIELD_STATIC | 5 | 3d | MOD | 1 | | | |
| 21 | PUTFIELD_QUICK | 5 | 3e | SHORTCUT_AND | 1 | | | |
| 22 | NEWARRAY | 5 | 3f | SHORTCUT_OR | 1 | | | |
| 23 | ARRAY_STORE | 1 | 40 | ANDAND | 1 | | | |
| 24 | ARRAY_INIT | 5 | 41 | OROR | 1 | | | |
| 25 | EMPTYDIMS | 5 | 42 | AND | 1 | | | |
| 26 | ARRAY_ACCESS | 1 | 43 | OR | 1 | | | |
| 27 | NEW | 5 | 44 | XOR | 1 | | | |
| 28 | DELETE | 5 | 45 | NOT | 1 | | | |

**宽度 1（55 个 —— 无载荷）**：
`03 0c 0e 16 1b 1c 1d 1e 23 26 29 2a 2b 2c 2d 2e 2f 30 31 32 33 34 35 36 37 38 39 3a 3b 3c 3d 3e 3f 40 41 42 43 44 45 46 47 48 49 4a 4b 4c 4d 4e 4f 50 51 52 53 54 55`

**宽度 5（30 个 —— 带 4 字节操作数）**：
`01 02 04 05 06 07 08 09 0a 0b 0d 0f 10 11 12 13 14 15 17 18 19 1a 1f 20 21 22 24 25 27 28`

### 5.5 ✅ 已解决：宽度表 100% 精确解析，且与二进制零分歧

**上一版留的 15 处分歧、9,950 条非法 `0x00`，本轮全部清掉。**

#### (1) 两条新判据

**(a) 合法域当硬约束。** 分派点 `@0x6538f0` 的 `dec eax / cmp eax,0x54 / ja` 已证明
**`1 ≤ opcode ≤ 0x55`**。之前只在事后过滤（85.27%），本轮把它写进分数函数**重新求解**
（`tools/opcode_align2.py`）→ 旧表的伪 `0x00` 无处藏身。

**(b) 🎯 handler 的收尾自己就暴露宽度。** 每个 handler 都以跳到两个共享尾声之一结束：

```
0x653d9f   add dword ptr [esi+0x28], 4     ; 吃了操作数
0x653da3   inc dword ptr [esi+0x28]        ; 只为 opcode 字节本身 +1
           （0x653d9f 自然落到 0x653da3，所以进入它 = 前进 5）
```

`esi+0x28` 就是分派点加载的那个**指令流指针**（`mov edi,[esi+0x28]`）。
所以：**从每个 handler 入口做递归下降、收集它到达哪个尾声 → 直接读出宽度**，
不用统计、不用猜语义（`tools/handler_advance.py`，含内联 `add [esi+0x28],4` 的累加）。

#### (2) 两条独立来源的一致性

| 来源 | 可判定操作码 | 与最终表分歧 |
|---|---|---|
| **exe**（handler 收尾） | **75**（75 单出口；9 双出口、1 寄存器间接跳转读不到） | **0** ✅ |
| **数据**（爬山：精确落点 + 载荷合理） | 85 | 见下 |

**9 个"双出口"**（`10 11 12 16 18 19 1a` = `[0,5]`，`3e 3f` = `[1,5]`）与 **1 个读不到**
（`17 JMP`，handler 用寄存器间接跳转离开）由数据补：
数据对它们给 5（`10 11 12 17 18 19 1a`，都是吃操作数的调用/跳转）与 1（`16 RETURN`、`3e/3f`）。
**反向验证**：强行把 `0x16`/`0x3e`/`0x3f` 改成 5 会让解析率掉到 97.47%/98.21%/99.19% → 1 正确 ✅

#### (3) 上一版那 7 处"名字 vs 数据"分歧，逐个由 handler 判死

| opcode | 名字 | 我猜 | **exe 收尾** | 判决 |
|---|---|---|---|---|
| `0x03` | NULL LITERAL | 5 | **1** | `push 0; call; jmp ep+1` → **无载荷**，隐式压 0 |
| `0x0c` | LOCAL_CREATE | 5 | **1** | `push 0; call 0x652f80; jmp ep+1` → **槽位由栈顶隐式给出** |
| `0x0e` | LOCAL_CLEAR | 5 | **1** | `call 0x652f60; jmp ep+1` → 无载荷 |
| `0x25` | EMPTYDIMS | 1 | **5** | handler 读 `[edi+1]`、`je ep+4` → **有载荷**（数据原本就对） |
| `0x26` | ARRAY_ACCESS | 5 | **1** | 两次 `call 0x652f10` 从**栈**弹数组与下标，不读 `[edi+1]` |
| `0x39` | IINC | 5 | **1** | `inc dword ptr [eax+edx*4-4]` —— 原地改**栈顶**，无载荷 |
| `0x3b` | IDEC | 5 | **1** | `dec dword ptr [eax]`，同上 |
| `0x3a`/`0x3c` | FINC/FDEC | 5 | **1** | 与 IINC/IDEC 同族；数据对它俩给 1 或 5 同分（各仅 20/13 次），**唯二进制可判** → 1 |

→ **凡是我"按名字语义"猜错的，都是把「操作数在栈上 / 隐式」误当成「操作数在指令流里」。**
名字只约束语义，**宽度必须由 handler 或数据给**。

#### (4) 最终表验证（`tools/verify_widths.py`，独立 walker）

| 指标 | 值 |
|---|---|
| TREE method record | **14,796** |
| **精确解析** | **14,796 / 14,796 = 100.00%** |
| 畸形（非法操作码 / 切不齐） | **0** |
| 指令总数（完整代码口径） | **382,399**（1,475,195 字节，均 **3.86** 字节/条） |
| 宽度 1 / 宽度 5 | **55 / 30** |
| 实际出现的操作码 | **79 / 85** |
| 从未发射 | `09 RID LITERAL`、`0a`（保留）、`28 DELETE`、`3a FINC`、`3c FDEC`、`49 LSR` |
| `0x0a` 保留空洞 | **确认全库从未发射** ✅ |
| 与 exe 收尾判据分歧 | **0** ✅ |

**旧表同口径只有 85.27%**（`sane` 分数 172,899 vs 新表 **272,544**）——
所以旧表不只是"略差"，而是**在合法域约束下有一大批系统性错位**。

高频操作码也完全自洽：`0x0b LOCAL_LOAD`(36,944) > `0x29 POP`(34,380) >
`0x06 FLOAT LITERAL`(31,618) > `0x05 INT LITERAL`(29,956) > `0x08 STRING LITERAL`(26,064)
> `0x12 INVOKESTATIC`(24,428)；方法**首条**最常是 `LOCAL_LOAD`(41%)，
**末条**最常是 `POP`(5,161) / `INVOKESPECIAL`(2,047) —— 都像人手写的字节码。

**结论：指令编码彻底定案 —— `<u8 opcode ∈ 0x01..0x55>` + 可选 4 字节操作数，
55 个无载荷、30 个有载荷，全库 14,796 个方法 100% 精确解析。可以建 CFG 了。**

## 6. 工具

| 工具 | 作用 |
|---|---|
| `tools/opcode_blob.py` | 按地址 dump `.rdata` 字符串；修正 VA/RVA 混淆 |
| `tools/opcode_table.py` | 装载 85 项名字表（4 字节对齐抽取），TUFA/TREE 解析 |
| `tools/opcode_width.py` | 早期约束传播（收敛慢，保留作对照） |
| `tools/opcode_align.py` | 载荷合理性爬山求宽度表（初版，**无合法域约束**，已被 `opcode_align2.py` 取代） |
| `tools/opcode_align2.py` | ★ **合法域硬约束 + 名字语义种子 + 爬山** → `out_w.json`（100% 精确解析） |
| `tools/handler_advance.py` | ★ **读每个 handler 的指令流前进量**（`0x653d9f`=5 / `0x653da3`=1）→ 75 个宽度，独立于数据 |
| `tools/reconcile_widths.py` | ★ 两条来源对账 + 同口径打分 → `out_w_final.json` |
| `tools/verify_widths.py` | ★ 独立 walker 终验：100% 精确解析、0x0a 从未发射、与 exe 零分歧 |
| `tools/dispatch_table.py` | 容错线性扫描 + 找 `jmp [reg*4+disp]` 跳转表（**发现 85 项分派表**） |
| `tools/dis_va.py` | **按 VA 反汇编任意区间**（`--raw` 带字节）—— 本轮读分派点用的就是它 |
| `tools/opcode_handlers.py` | dump 85 个 handler 并分类 |
| `tools/handler_widths.py` | 从 handler 反推宽度（**探测器不可信，须手工判读**） |
| `tools/emit_sites.py` | 找编译器 `mov byte ptr [reg], imm8` 发射点（**该编译器用寄存器寄存，此法失效**） |
| `tools/lasr_vm.py` | 端到端：求宽度 → 分类 → `--survey` / 反汇编任意方法。**`walk()` 返回 `(pos, op, w, pay)`** |

反汇编示例：

```
$ python tools/lasr_vm.py --class java.game.Bet --method 1
$ python tools/dis_va.py 0x6538f0 0x653907 --raw
```

## 7. 对重制的意义

* **361,971 条指令的边界 + 操作码名字全部已知** → 可做控件流分析、导出常量、翻译逻辑
* 85 项里 **77 个语义明确**（标准字节码操作），只有 **8 个引擎特有**：
  `SADD` / `SHORTCUT_OR` / `SHORTCUT_AND` / `RID LITERAL` / `DELETE` /
  `EMPTYDIMS` / `LOCAL_CLEARN` / 保留的 `0x0a`
* **`0x06` = FLOAT LITERAL**（`0.0f`×10,367、`1.0f`×2,021、`0.5f`×55 已实测）
  —— 车辆物理参数、游戏规则常数**现在可以直接挖了**
* 控件流所需的 5 个跳转/返回操作码（`0x16..0x1a`）已定位，且 `0x17` 是唯一
  做相对跳转的 handler —— **可以开始建 CFG 了**

## 8. 仍缺

* §5.5 的 15 处宽度分歧（主要是 `0x1c I2F`）+ 9,950 条 `0x00` 伪指令
  → 用 `1 ≤ opcode ≤ 0x55` 硬约束**重新求解**宽度表
* 34 条无法解析的 record（0.23%），为超长方法
* 操作数索引 → 常量池/字段表/方法表的绑定（`CONS` 已见雏形：
  `u32 count` + 4 字节对齐定长槽，槽内含 NUL 串 + 类型字节；尚未完整解出）
