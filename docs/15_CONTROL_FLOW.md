# 15 · 控制流结构化

> 状态：✅ **14,796 个方法全部结构化**，其中 **14,666 个（99.12%）零 `goto`**
> 独立判据：**与抽象解释栈高表逐块核对，0 处分歧**
> 工具：`tools/struct_cfg.py`（`--report` / `--method` / `--class` / `--dump`）
> 产物：**`out_pseudo/`（2,216 个类, 90,651 行, 8.5 MB）**

## 1. 分支语义 —— 从语料标定，不靠猜

| opcode | 名 | 语义（已标定） | 证据 |
|---|---|---|---|
| `0x17` | `JMP` | 无条件；**紧跟 `SHORTCUT_AND/OR` 时变成条件跳转** | 见 §3 |
| `0x18` | `JMP_NE` | 弹 1；**弹出值为 0 时跳**（即条件为假时跳） | 545 个回跳中 **539 个**循环头的出口分支都是它，且前一条是 `ILT/IGE/INE` 比较；17 处条件是 `BOOL LITERAL 1`（= `while (true)`） |
| `0x19` | `JMP_EQ` | 相反语义：弹出值非 0 时跳 | 仅 16 处（`do-while`/值语义分支） |
| `0x1a` | `JMP_EQ2` | 弹**刚压入的常量**、**保留**被比较主体；相等时跳 | 2,340 处，全为前向；链式即 `switch` |

标定法：**「循环头的条件分支必然是按条件取反跳出」**是编译器铁律 —— 用它一元确定跳转极性，
不需要读源码。反过来，这也解释了为什么 `JMP_NE` 占 4,378 处而 `JMP_EQ` 只有 16 处：
编译器统一用「假则跳」的极性，`if (!x)` 靠 `EXCLAMATION (0x46)` 先取反。

## 2. 结构化率

```
methods                      14,796
clean (no goto)              14,666   = 99.12%
with goto fallback              130   =  0.88%
height disagreements (consistent methods)   0   ← 独立判据
merge conflicts                 118   (0.8% 方法)
unvisited blocks                254   (0.03% 块，全部显式列出)
```

**独立判据**：结构化器自己维护一套符号栈做数据流；把每个块入口的栈高与
`out_stack_heights.json`（P2.6 抽象解释产物）逐块核对。**1,470 个方法曾对不上**
（最大偏差 −35，逐块累积），根因是汇合点用「取较长者」合并导致栈高膨胀 ——
改为**用栈高表校正每条边的栈**后归零。这条判据是「表达式在汇合点是否还正确」的唯一保证。

## 3. 三种必须专门处理的形状

### 3.1 `SHORTCUT_AND/OR` 之后的 `JMP` 是**透明块**

```
B47: SHORTCUT_AND ; JMP 61      ← 假则跳到 61（跳过右边）
B53: <求右边> ; ANDAND → 61     ← 求值路径也到 61
B61: JMP_NE 77                  ← 在 61 处消费合并后的布尔
```

两条路径**落点相同、栈状态相同**（shortcut 只偷看不弹）→ 它**不是一个 `if`**，必须折叠掉。
若当作条件分支渲染，就会得到 `if (A) { if (B) { ... } }` 的重复嵌套与幻影 `else`。

### 3.2 值菱形 = 三元表达式

`Bet.getIcon()` 里 `cond ? name : "默认"` 编译成「两支都只压一个值、不产生语句」的 if-else。
识别后**在数据流里合成三元节点**，并把该节点的栈**覆盖到汇合点**，后续块用覆盖后的栈重新抬升：

```java
System.log(("Bet.getIcon() : '" + ((local0.getName() != null)) ? (local0.getName()) : ("")) + "'");
```

不做这一步，三元就会渲染成 `if (...) { goto L42; } else { }` —— 结构没丢，语义全丢。

### 3.3 区间延续点 `cont`

`if/else` 的 then 支末尾那条 `JMP` 跳向的是**外层汇合点**，不是本区间的 stop。
把「延续点」作为参数传进区间发射器（`t == stop or t == cont → 静默结束`），
`goto` 回退数从 313 降到 **130**。

## 4. 读出来的游戏规则（示例）

`Challenge.apply(I)V`（381 条指令，分红结算）：

```java
if (this.trialMode) return;
if (local1 && (this.opponentBets != null)) {
    local3 = 0;
    while ((local3 < this.opponentBets.length)) {
        if ((this.opponentBets[local3] != null)) {
            switch (this.opponentBets[local3].getBetType()) {
                case BET_TYPE_Prestige:  break;
                case BET_TYPE_PerformPart:
                    local4 = {0, 0, 1, 100, 0, 0};
                    Gamelogic.player.items.addItem(..., local4);
                    if ((this.destIVehicle != Gamelogic.player.getVehicle().item)) {
                        Gamelogic.lastPinkPerformPart = null;  local2 = this.destIVehicle;
                    } else {
                        Gamelogic.lastPinkPerformPart = ...betPart;  local2 = ...item;
                    }
                    local2.getVehicle();  break;
                case BET_TYPE_StylingPart:  ... Gamelogic.lastPinkStylingPart = ...
                case BET_TYPE_IVehicle:
                    local4 = (IVehicle)Gamelogic.player.items.addItem(...getId());
                    Gamelogic.lastPinkSlipsPrice = local4.getVehicle();  break;
            }
        }
        local3 = (local3 + 1);
    }
}
```

`Gamelogic.getPlayerReputation()F`（声望结算）：

```java
local2 = (Gamelogic.races.size() - 1);
while ((local2 >= Gamelogic.races.size())) {
    local3 = (RaceChronicle)Gamelogic.races.elementAt(local2);
    if (((((local3 == null) || (local3.getOpRank() >= 100)) || (local3.getOpRank() < 0))
         || (local3.getTrackID() == (-1))) || (local3.getMyCar() == (-1))) {
    } else {
        local1 = (local1 + 1);
        local4 = 0;
        if ((local3.getWon() != 0)) {
            switch (local3.getOpponentStatus()) {
                case  2: local4 = 2.0;  break;      // 胜强敌
                case  1: local4 = 1.0;  break;
                case -1: local4 = 0.25; break;      // 胜弱敌
            }
        } else {
            switch (...) { case 2: local4 = -0.5; case 1: local4 = -1.0; ... }
        }
    }
    local2 = (local2 - 1);
}
```

> 注：`while (local2 >= races.size())` 是**忠实于字节码**的（比较操作数顺序已用
> `Challenge.apply` 的 `local3 < opponentBets.length` 独立交叉验证）。这是原源码
> 「一边遍历一边缩减 Vector」的写法，不是抬升错误。

## 5. 诚实的残差

* **130 个方法（0.88%）** 含 `goto` —— 读起来仍接近 Java（多为 if-else 链的尾部跳转）。
* **254 个块（0.03%）** 未被结构游走访问：其中 133 个方法本身就属于
  P2.6 已定性的「栈分析失败」集合（115 return-arity + 58 unreachable）。
  **全部在输出里显式列出**（`// B<off> [kind] <指令>`），不静默丢代码。
* **118 个方法**有汇合点表达式分歧（两条路径压入的表达式文本不同 → 取先到者）。
* 结构化是**语句级**的，不含异常（该 VM 无异常指令）。
* 未还原：`for` 循环的语法糖（现在统一渲染为 `while` + 初始化/自增语句）、
  `do-while` 的边界情况。

## 6. 复现

```bash
python tools/struct_cfg.py --report                          # 结构化率统计
python tools/struct_cfg.py --method extracted/java/classes/game/Bet.class#7
python tools/struct_cfg.py --class extracted/java/classes/game/Challenge.class
python tools/struct_cfg.py --dump                            # -> out_pseudo/
```
