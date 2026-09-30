# 43 · 生涯系统：prestige / 名次 / pub / 挑战生成 / 存档

> 全部来自 `out_pseudo/java/`（静态）。凡是「实测」都指**能指到代码或字节码地址**的结论；
> 「推断」单独标注。可执行验证见 `tools/career_sim.py` 与 `out_career_prestige.csv`。
>
> 本轮同时**关闭了 docs/42 的一个待办**：`rankingScores` 的单位（见 §1.2）。
>
> **本轮产物**：`out_career_prestige.csv`（61 行名次阶梯）、`out_vehicle_prestige.csv`（23 个车辆类的 prestige 门槛）、
> `out_opponents.csv`（列名已修正）、`tools/career_sim.py`（算法复现 + 自洽校验）。

---

## 1. 先分清三个都叫「rank / 名次」的东西 ★

原版里有三套互不相干的「名次」，混起来会得出错误结论：

| # | 名字 | 取值 | 谁在用 | 单位 |
|---|---|---|---|---|
| **A** | 生涯名次 `getPlayerRank()` | **1..61**（1 最好，61 最差） | `getOpponentStatus` / pub 推荐 / 挑战抽取 / 夺冠判定 | **prestige** |
| **B** | 称号等级 `getRankString(I)` | **-1..39** → 8 档 × 5 级 | HUD / 升级提示 | **XP**（网络用户参数） |
| **C** | pub 内 15 人窗口 | 60 人名册的滑动窗口 | `ChallengeOffer.getOpponentIndex` | 名册下标 |

### 1.1 A：生涯名次 = prestige 在 60 人名册里的位置

```java
// Gamelogic.getPlayerRank(I)I
i = BOT_ARRAY_MAX - 1;                    // 59
while (i >= 0) {
    if (opponents[i].getPrestige() >= prestige) return i + 2;
    i--;
}
return 1;
```

* 名册 `opponents[]` 的 prestige **严格递减**（`opponents[0]=10000` … `opponents[59]=250`，实测 60 值无重复）
  ⇒ 返回值 = `max{ i : prestige_i >= px } + 2`。
* 于是：`px <= 250` → 名次 **61**（开局）；`px > 10000` → 名次 **1**（登顶）。
* 名册顺序即强度顺序，`Bot.rank`（构造参数第 8 个）与下标一致（`rank == i+1`，实测）。

### 1.2 B：称号等级 —— 这回答了 docs/42 的遗留问题 ★

```java
// Gamelogic.getRankString(I)        入参 = XP
level = 找 rankingScores 里第一个 <= XP 的下标（从高往低），XP < rankingScores[0]=28 时 level = -1
name  = rankingNames[level / 5]        // Java 整数除法，-1/5 == 0
suffix = switch (level % 5) { -1:"-F"  0:"-E"  1:"-D"  2:"-C"  3:"-B"  4:"-A" }
return name + suffix;
```

* ⇒ `rankingNames` 8 档 × 每档 5 级 = **40 级**：`Rookie-F`(level -1) → `Rookie-E`(0) → … →
  **`National Pro-A`(level 39)**；超过表尾由 `getNextRankName` 返回 `"Intergalactic Pro"`。
* **实测**：`rankingScores` 的比较对象是 `Player.xpBeforeRace`（`GameMode.java:257`）与
  `xpAfterRace`（`GameMode.java:256`）。**不是 prestige**。
* **实测**：XP 存在**元服务器用户参数**里 —— `MetaServer.USER_PARAM_XP = 12`
  （`net/MetaServer.java:228`），读写在 `GameMode.java:495 / 654`。
  ⇒ **XP 的累加规则不在 Java 层**（✗ 未找到，见 §10）。
* `getNextRankXP` / `getCurrentRankXP`（`Gamelogic.java:1205–1226`）返回的都是
  `rankingScores[i] + 1` 这种「阈值+1」，是 UI 进度条用的边界值，不是奖励量。
* ⚠ 方向注意：`getRankString` 的用户名是「分数→称号」，而 `Challenge.rankingScores`
  与生涯**名次**无关。docs/42 §1 说的「达到第 N 名所需的分数」应改述为
  「达到第 N 级**称号**所需的 XP」。

---

## 2. prestige 的结算：`Challenge.updateRanking()` 是唯一入口 ★★

`updateRanking()` 只在 `GmRace.refreshResults()`（`GmRace.java:879`）里被调用，条件是
单机、非快速比赛、且本场不是「混蛋赛已结束」：

```java
if (!Gamelogic.bastardRaceFinished && !Gamelogic.isQuickRace) Challenge.updateRanking();
```

### 2.1 逐步照抄（`Challenge.java:155–194`）

```java
updateRanking() {
    streak = 0;
    // ① 从最新往旧数「连续输给更强对手」的场数（赢一场即停）
    for (i = races.size()-1; i >= 0; i--) {
        c = races[i];
        if (c != null && c.getOpRank() < 100) {        // ★ opRank >= 100 = 教学关，排除
            st = c.getOpponentStatus();
            if (c.won != 1) { if (st == 2 || st == 1) streak++; }
            else break;
        }
    }
    // ② 偶数连败（≥2）→ 掉 1 名
    if (streak % 2 == 0 && streak != 0)
        prestige = getOpponentPrestigeByStatus(-1) + 1;

    // ③ 只看最近一场
    last = races.lastElement();
    if (last != null && last.getOpRank() < 100) {
        st = last.getOpponentStatus();
        if (last.won == 1) { if (st > 0) prestige = getOpponentPrestigeByStatus(st) + 1; }
        else               { if (st < 0) prestige = getOpponentPrestigeByStatus(-1) + 1; }
    }
}
```

★ 求值顺序实测确认：②③ 里的 `getOpponentPrestigeByStatus` 用的是**赋值前**的 prestige
（Java 先算 `local2` 再赋值），但 ③ 读的 `Gamelogic.prestige` 已经是 ② 更新后的值。

### 2.2 对手状态的方向（容易读反，已核到字节码）

```java
getOpponentStatus(Bot b) {
    if (b.rank <= getPlayerRank() - 8) return 2;   // 对手名次数字小 ≥8 → 对手强得多
    if (b.rank <  getPlayerRank())     return 1;   // 对手更强
    return -1;                                     // 对手更弱
}
getOpponentPrestigeByStatus(status) {
    i = getPlayerRank() - status - 1;  i<0→0;  i>59→ return 99;
    return opponents[i].prestige;
}
```

### 2.3 结算表（由 §2.1 推出，`tools/career_sim.py` 已逐步核对）

| 最近一场 | 对手相对强度 | prestige 落点 | 名次变化 |
|---|---|---|---|
| **胜** | 强得多（status 2） | `opponents[r-3].prestige + 1` | **-2**（↑两名） |
| **胜** | 更强（status 1） | `opponents[r-2].prestige + 1` | **-1**（↑一名） |
| **胜** | 更弱（status -1） | 不变 | 0 |
| **负** | 更弱（status -1） | `opponents[r].prestige + 1` | **+1**（↓一名） |
| **负** | 更强（status 1/2） | 单场不变；**每 2 连败** → `+1` 名次 | 偶数连败 -1 |

（`r` = 结算前的名次；三处都恰好落在「目标名次的区间下界」，所以每次移动都是整齐的 ±1/±2。）

**可执行复核**（`tools/career_sim.py` 模拟 D，中段 rank 30 连输给 pub3 窗口里更强的对手 6 场）：
掉名次发生在第 **2、4、6** 场，rank 30 → 33 ⇒ 上表「偶数连败 -1」逐场命中。
底部（rank 61）时同一条规则会因 `getOpponentPrestigeByStatus` 的 `>59 → 99` 钳位而空转（模拟 B）。

### 2.4 ★ 两个实测到的「死逻辑 / 恒零值」

1. **`Challenge.getPrestigeForRace(I)I` 恒返回 0** —— 不是反编译失败：
   `tools/stack_depth.py --class …/Challenge.class` 的原样字节码就是

   ```
   #3 getPrestigeForRace(I)I   ok=True
       0 [0] 05 INT LITERAL 0
       5 [1] 16 RETURN
   ```
   而 `GmRace.java:1041–1047` 把它的返回值写进 `raceChron.setPrestige(...)`
   ⇒ **存档里的 `RaceChronicle.prestige` 永远为 0**，prestige 只能靠 §2.1 走。

2. **`Gamelogic.getPlayerReputation()F` 的循环条件是错的** —— 字节码实证：

   ```
   #14 getPlayerReputation()F   ok=True
       40 [1] 0d LOCAL_STORE slot 2          // local2 = races.size() - 1
       45 [0] 0b LOCAL_LOAD  slot 2
       50 [1] 14 FIELD_REF_STATIC Gamelogic.races
       55 [2] 10 INVOKE Vector.size ()I
       60 [2] 4d IGE                          // local2 >= size ?
       61 [1] 18 JMP_NE -> 527               // 为假就跳出
   ```
   `local2` 初值 `size-1`，`size-1 >= size` 恒假 ⇒ 循环体一次都不执行
   ⇒ **`getPlayerReputation()` 恒返回 `0.0F`**，唯一的调用点
   `frontend/PDAPopup.java:334` 拿到的一直是 0。
   *推断*（非实测）：源码本意应为 `while (local2 >= 0)`；循环体里的权重表
   （胜 status2→+2 / status1→+1 / status-1→+0.25；负 -0.5 / -1 / -2，按 `i/n` 加权）
   因此**从未生效**，重制时不必实现。

---

## 3. 名次阶梯表 + 可执行验证

产物：**`out_career_prestige.csv`**（61 行 = 名次 → prestige 区间 → 边界对手 → 推荐 pub）。

`tools/career_sim.py` 做的事：现场从伪码解析名册与常量 → 逐行复现
`getPlayerRank` / `getOpponentStatus` / `getOpponentPrestigeByStatus` / `updateRanking`
→ 自洽性校验（60 个名次区间全部 `✓`）+ 四组模拟 + 车辆 prestige 门槛表。实跑结果：

```
名册字段核对: prestige 严格递减 ✓  rank 与下标一致 ✓
              aggressivity 含负值（-0.898..0.999）  randomness 全在 0..1
一致性校验:   ✓ 全部 60 个名次区间自洽

模拟 A（开局 prestige=0，每场都赢、都挑该 pub 最强）:
  # 1 vs Tex          -> rank 59   # 2 vs Tex  -> rank 57   # 3 vs Tex -> rank 55
  ...
  #43 vs Matt Peacock -> rank  2   #44 vs Matt Peacock -> rank 1
  ⇒ 从最后一名登顶需 44 场全胜
模拟 B（起点连输 6 场给更强对手）: prestige 0→100，名次恒 61（底部的 streak 惩罚是空转）
```

★ 登顶后**还要再赢一场 `opponents[0]`（Matt Peacock）**才算通关：

```java
// GmRace.refreshResults
last.won == 1 && challenge.challenger.getName() == opponents[0].getName()
             && getPlayerRank() == 1  →  justWonTheGame = true; bastardRaceFinished = true;
```

---

## 4. 对手名册（60 人）与两处实测异常

产物：**`out_opponents.csv`**（本轮重写，列名修正）。

### 4.1 字段语义（来自 `Bot.<init>(String,Driver,FFFIII)` 的赋值顺序）

`(name, driver, aiLevel, aggressivity, randomness, prestige, sex, rank)`

| 字段 | 含义（实测证据） |
|---|---|
| `driver` | 头像/语音模型类：`drivers.crcman / crcman2..4 / crcgirl / crcgirl2..4`（8 个） |
| `aiLevel` | 1.0 → 0.0 递减；`Bot.activate()` 里直接作为 `AI_level` 与 `AI_params2` 的输入 |
| `aggressivity` | **有负值**，判定点是 ±0.4 / -0.2（`Bot.java:295–329`）、`GmRace.java:210` |
| `randomness` | 全在 0..1，且是**阶梯桶**（见 4.2），只喂 `AI_params2` 的摆动量 |
| `prestige` | 名次阶梯的阈值（§1.1） |
| `sex` | 0/1，用于挑语音/称谓 |
| `rank` | 1..60，等于下标+1 |

⚠ **旧 `out_opponents.csv` 把第 4、5 个浮点标反了**（`seed` / `aggression`）。
以 §4.1 的赋值顺序为准：第 4 个是 `aggressivity`（含负值），第 5 个是 `randomness`（0..1 阶梯）。
本轮已按正确列名重写。

### 4.2 分 pub 的特征（实测，按名册每 15 人切）

| pub | 名册下标 | 名次 | prestige | aiLevel | randomness |
|---|---|---|---|---|---|
| 1 `COOL market` | 45..59 | 46..60 | 1050..250 | **0.0（全员！）** | 0.9..1.0 |
| 2 `Peninsula shops` | 30..44 | 31..45 | 2450..1100 | 0.5..0.167 | 0.6..0.8 |
| 3 `Hyper Center` | 15..29 | 16..30 | 5250..2600 | 0.75..0.517 | 0.3..0.5 |
| 4 `Village Motel` | 0..14 | 1..15 | 10000..5450 | 1.0..0.767 | 0.0..0.3 |

★ 两个**异常**（实测，如实记录，不解释成设计）：
1. **pub 1 的 15 人 `aiLevel` 全是 0.0** —— 最低档的对手完全没有 AI 技能参数，
   只靠 `aggressivity` / `randomness` 区分。重制时若照抄 aiLevel 会让 pub1 毫无难度。
2. **`Mikage`（下标 40，rank 41）`aiLevel = 0.533333`**，夹在 `Jay(0.35)` 与
   `Ferryman(0.316667)` 之间 —— 名册里**唯一**一处 aiLevel 逆序。
   *推断*：原数据疑似笔误（按上下文应为 `0.333333`）。

---

## 5. 难度橡皮筋：`aiLevelMul` 三兄弟

```java
// Gamelogic 静态初值
aiLevelMul  = 1.1;    aiLevelMul2 = 1.5;    aiLevelMul3 = 0.5;
```

`Bot.activate()`（`Bot.java:45–70`）合成真正的 `usedAILevel`：

```java
usedAILevel = aiLevel;
if (raceSum < 10)                       usedAILevel *= 0.5;              // 前 10 场：半技能
else {
    if (aiLevelMul < 1.0)               usedAILevel *= aiLevelMul;       // 只在「已被削弱」时才乘
    if (getOpponentStatus(this) == 2)   usedAILevel *= 1.5;              // 强得多的对手再加强
    else if (this.rank < getPlayerRank())                                    // 比我强的对手
        usedAILevel *= 1.0 + (getPlayerRank() - rank) / 35.0;            // 越多名就加强越多
}
command("AI_level " + usedAILevel + " 1.0 -1 " + (2.5 - usedAILevel));
```

输赢时的更新（`Gamelogic.lostRace(F)`，`Gamelogic.java:1793`）：

```java
lostRace(x) {                                  // x = challenger.usedAILevel，由 GmRace.java:1031 传入
    aiLevelMul *= (1.0 - 0.0 / (raceSum + retries + 10));   // ★ 第一项恒等于 1，空操作（实测：局部变量 local1 = 0.0）
    aiLevelMul *= (1.0 - (1.0 - x) * 0.03);                 // 最多 -3%/场，对手越强削得越多
}
```

* ⇒ **输一场最多把 AI 削 3%**（对手够强时），赢不恢复；`aiLevelMul` 被写进存档（§8）。
* 重置点**只有一处**：`Gamelogic.resetCareer()`（`Gamelogic.java:2009–2027`）里 `aiLevelMul = 1.1`，
  与 `prestige/raceSum/winSum/retries/offeredRaces/trialProgress` 一起归零 ⇒ **比赛中不会自动复位**，
  削下去就一直削（同一存档内单调递减）。

---

## 6. 挑战生成（`ChallengeOffer`）

### 6.1 常量（`ChallengeOffer.?()V`，实测）

| 常量 | 值 | 作用 |
|---|---|---|
| `STRONGER_OPP_PROBABILITY` | **0.65** | 在 pub 窗口内额外向上抽「强得多的对手」的概率（`getOpponentIndex`） |
| `PINK_SLIPS_PROBABILITY` | **0.33** | 挑战是「赌车（pink slips）」而不是赌零件的概率（`createChallengeOffer`） |
| `SAME_CAR_IN_PUB_PROBABILITY` | **0.3** | 抽粉红条奖品车时，**把玩家自己当前那辆车剔掉**的概率（`getCarsAtCurrentPub`，`ChallengeOffer.java:214`） |
| `MAX_BET_NUMBER` | **3** | ✗ **死常量**：除静态初始化外无引用（`new Bet[3]` 是字面量 3） |

### 6.2 对手抽取（`getOpponentIndex()`）

```java
if (preferredBot > -1) return preferredBot;
if (getPlayerRank() == 61 && random() < 0.7) findAcceptableOpponent = true;   // 开局 70% 去找「可挑战的」
base = 59 - (pubIndex - 1) * 15;                     // pub 窗口起点
pos  = getPlayerRank() % 15;                         // 我在窗口里的相对位置
// 主循环（≤1000 次）：65% 概率取「更强」的对手，否则窗口内随机；跳过 lastFiveOpponents
local3 = base - (I)(random() * 15);
local3 = (local3 < 0) ? base : local3;
if (random() <= 0.65) { local4 = 16 - pos;  local3 = base - (I)(random()*(pos-1)) - local4; }
```

* 结果必须是 `whatsUp(i,0) == BOTTALK_OFFER`（愿意开价）的对手，否则重抽。
* **最近 5 个对手**（`lastFiveOpponents`，`addToLastFiveOpponents` 在挑战生成时入队）不会被连续重复抽到。

### 6.3 赛道抽取（`getTrackID()`）

从 `player.items.listMaps()` 里挑 `pubIndex` 相同的图；**`winSum >= 3` 才随机**，
否则固定取第 0 张；`local3 < 1000` 次内避免与 `lastMapID1/2`（最近两场）重复；
这两值在 `loadChronicles` 时由存档恢复（`Gamelogic.java:1499–1513`）。

### 6.4 赌注生成（`createPartOffer(IVehicle)`）

* `new Bet[3]`：槽 0 = 性能件、槽 1/2 = 外观件（`createPartOffer` 的选件逻辑）：
  只从「对手车有、我没有」的件里挑；性能件要求 `stage == 我的最大 stage + 1`（即下一阶段升级件）；
  外观件要求 `stage > 0`。
* `winSum < 10` 时随机把一个槽置 null 再把另一个设成 prestige 赌注（`new Bet(2)`）；
  `10 <= winSum < 15` 时清掉槽 2 ⇒ **赢得越多，对手赌的东西越多**。
* 名册下标 0/1/2（Matt Peacock / Stan Karew / Ted Cutter）有**专属座驾**：
  `VID_06_Fujin_MX_Matt_Peacock` / `VID_06_Hornet_Wega_Stan_Karew` / `VID_97_Raptor_ZX_Ted_Cutter`。
* 玩家胜出后 `Challenge.apply(1)` 把对手赌注转给玩家（`Bet` 6 种类型：
  `BET_TYPE_Prestige=1 / PerformPart=2 / StylingPart=3 / IVehicle=4 / WholeStage=5 / WholeStyle=6`）；
  输掉则按同样类型从玩家车上拆件（`apply(0)`，`Challenge.java:84–144`）。
* `isForPinks()` = 非教学关、非快速赛、且第一个对手赌注是 `BET_TYPE_IVehicle`。

### 6.5 ★ 赌车奖励池与**车辆的 prestige 门槛**（`getPinkSlipsAvailable` / `getCarsAtCurrentPub`）

`getPinkSlipsAvailable(true)`（`ChallengeOffer.java:172`）决定「哪些车可以当粉红条奖品」：

```
if (player.vehicle.getMaxPossibleStage() < 1) return null;        // 车太素，不给赌车机会
cars = getCarsAtCurrentPub();                                     // 枚举全部车型，过滤见下
for each car:
    if (玩家已有该车 或 已有其宽体版(id + (10<<16)))              → 剔除
    if (arg0 && car.getMinPinkSlipsPrestige() > 玩家 prestige)     → 剔除（★ 门槛在这里）
```

`getCarsAtCurrentPub()` = 遍历 `IVehicle.VID_MAX`，只留 `belongsToPub(pubIndex)` 为真的车型；
若是玩家当前车且 `random() < 0.3` 再剔一个。

而门槛本身（`item/IVehicle.java:1697`）：

```java
getMinPinkSlipsPrestige() { return this.minPrestige / 2; }
getPrestige()             { return minPrestige + (maxPrestige - minPrestige) * potential / 4; }  // ★ 基类版
```

⇒ 每辆车在**自己的 TUFA 类构造器**里带一对 `minPrestige / maxPrestige` 字面量，
`minPrestige` 就是「生涯解锁门槛」，`minPrestige/2` 是「能赌它（粉红条）的门槛」。
全部 23 个车辆类的实测值见 **`out_vehicle_prestige.csv`**（`tools/career_sim.py` 生成），主干如下：

| 车辆类 | minPrestige | maxPrestige | 粉红条门槛(min/2) | `getPrestige()` 返回的常量 |
|---|---|---|---|---|
| `IVehicle_Hatch_S2`（开局车 Corus S2） | 10 | 7700 | 5 | 40 |
| `IVehicle_Hatch_Trend`（Trend 1983） | 1710 | 7290 | 855 | 40 |
| `IVehicle_Hatch_CycloneR`（Cyclone 2004） | 2180 | 9590 | 1090 | 130 |
| `IVehicle_Coupe_SD_T5`（Quaddro SD T5） | 2270 | 8380 | 1135 | 400 |
| `IVehicle_Sedan_DesertS`（NSR Desert 2003） | 3280 | 9180 | 1640 | 200 |
| `IVehicle_Sedan_MX`（Fujin MX 2006） | 3800 | 9740 | 1900 | 700 |
| `IVehicle_Coupe_RS`（Phoenix RS 1997） | 3810 | 8900 | 1905 | 350 |
| `IVehicle_Coupe_ZX`（Raptor ZX 1997） | 4130 | 9720 | 2065 | 500 |
| `IVehicle_Sedan_Wega`（Hornet Wega 2006） | 4320 | 9480 | 2160 | 700 |
| `IVehicle_Coupe_TornadoR` | 5560 | 10000 | 2780 | 650 |
| `IVehicle_Sedan_MX_N1` / `_Wega_N2` / `_ZX_N3` | **1** | 10000 / 9600 / 9200 | 0 | 700 / 700 / 500 |
| 各 `*_WB`（宽体版） | ✗ 未在子类里赋值（应继承/由转换流程设置） | — | — | 与基车同值 |

* `*_N1/_N2/_N3` 是三名对手（Matt Peacock / Stan Karew / Ted Cutter）的**专属车**：
  `minPrestige = 1` ⇒ 从开局就可赌；这也解释了 §6.4 里他们对阵时的专属座驾。
* `stylPrestigeMul` / `perfPrestigeMul` **不是恒 1.0**，而是**逐车**不同（`*_WB` 与自己的基车同值，
  实测 23 个类共 11 组）：`Hatch_S2 = 0.25/0.35`、`Hatch_Trend = 0.3/0.4`、`Hatch_CycloneR = 0.5/0.6`、
  `Sedan_DesertS = 0.55/0.6`、`Coupe_RS = 0.6/0.6`、`Coupe_SD_T5 = 0.75/0.65`、`Coupe_TornadoR = 0.9/0.8`、
  `Sedan_Wega = 0.95/0.95`、`Sedan_MX = 1.0/1.0`、`Coupe_ZX = 1.0/0.9`。
  *推断*：它缩放「外观件/性能件给车主带来的 prestige」——越好的车改装收益越高，开局车只有 1/4。
  两个列已写进 `out_vehicle_prestige.csv`。
* 每辆车另有 `perfectTuning` / `dropTable` / `tuningValue` 三张 24 项数组（改装件的掉落/完美改装配表，属改装子系统）。
* ⚠ **两处 `getPrestige` 并存且数值不一致**（`IVehicle_Sedan_MX`：子类常量 700 vs 基类插值公式）
  ⇒ ✗ 未确认哪一条在实际算「这辆车的 prestige 值」，见 §10。

---

## 7. pub 与教学关（trials）

### 7.1 4 个 pub（`Pub.java:2`，`PubInfo.<init>(…,5×Pori,FFFFFF,String)`）

| index | 名字 | 车库地图 | 车流 spline | `startsAt` | `stopsAt` | `disappearsAt` | `maxSpeed` |
|---|---|---|---|---|---|---|---|
| 1 | COOL market | `maps/suburban_b.rpk` | `maps/suburban_b/Track_00.spl2` | 60.0 | {10.0, 35.0} | {180.0, 190.0} | 60.0 |
| 2 | Peninsula shops | `maps/harbor_b.rpk` | `maps/harbor_b/Track_00.spl2` | 225.0 | {188.0, 200.0} | {158.0, 163.0} | 40.0 |
| 3 | Hyper Center | `maps/business_b.rpk` | `maps/business_b/Track_00.spl2` | 155.0 | {119.0, 136.0} | {92.0, 95.0} | 55.0 |
| 4 | Village Motel | `maps/coastline_b.rpk` | `maps/coastline_b/Track_00.spl2` | 35.0 | {98.8, 118.0} | {70.0, 75.0} | 55.0 |

★ 这组浮点是**对手车在 pub 门前那条 spline 上的位置（米）**，语义已核实到使用点
（`frontend/PubWindow.java:430–500`）：
`startsAt` = 对手车生成点（缺省 25.0）；进入 `stopsAt[0]..[1]` 区间后停靠，
并把 `AI_maxspeed` 按区间内比例从 10% 线性升到 100% 的 `maxSpeed`（转成 m/s：`/3.6`）；
越过 `disappearsAt` 区间（缺省 90..110）则 `OFFER_CAR_OUT`。
另有 `playerPos/Ori`、`playerOfferPos/Ori`、`opponentOfferPos/Ori`、`backCamPos/Ori`、`offerCamPos/Ori`
共 5 组 Pori（坐标+朝向），以及 `mapStr`（地图类名）。

### 7.2 pub 与名次/教学关的对应

* 推荐 pub：`getSuggestedPubIndex() = 5 - min((rank-2)/15 + 1, 4)`
  ⇒ rank 61..47 → pub1，46..32 → pub2，31..17 → pub3，16..1 → pub4（见 CSV 最后一列）。
* 开局排位：`getBotsBeforeMe()` = `rank-2`（当 3 ≤ rank ≤ 11）否则 **10**；`getBotsAfterMe()` = **5**
  ⇒ 单机赛起跑线上「10 前 + 我 + 5 后」。
* 教学关：30 条（`out_trials.csv`），`TRIALS_PER_SERIE = 3` ⇒ 10 个系列；
  `Pub.enter()` 把当前 trial 的地图映射成 pub（**实测映射**）：
  `Suburban/Boulevard → pub 1`、`Highway/Harbor/Industrial → pub 2`、
  `Business/Urban/Observatory → pub 3`、`Coastline/Hills → pub 4`。
* 教学关的赛道记录用 `opRank = 100 + trialProgress`（`GmTrial.java:165`），
  而 `updateRanking` / `getWinningRate` 都只处理 `opRank < 100`
  ⇒ **教学关不进 prestige 阶梯，也不算胜率**（机制清晰，实测）。
* 完成一个系列 → `newConversoinAvailable = true`（原版变量名就是拼错的 Con_vers_o_in），
  在 `GmTrial.deinitGameMode()` 里消费：**`Gamelogic.convertToWideBody()`**
  ⇒ 教学关的奖励是**宽体改装**（车辆 item id `+ (10 << 16)`，`Gamelogic.java:280–302`），并自动存档。
* 每场赛后 `setNewRaceChronicle` 把记录压进 `races`（上限 `MAX_RACECHRONICLE = 15`，FIFO 覆盖）。

---

## 8. 生涯存档格式（`save/career/00N.sav`）—— 完整字段顺序

`Gamelogic.save/load`（`Gamelogic.java:1358–1445`），
`SAVEFILEID_MAIN = -1754971391`，`SAVEFILEVERSION_MAIN = 16`：

```
[I] SAVEFILEID_MAIN
[I] SAVEFILEVERSION_MAIN
[Str] 存档时间字符串  ("Y.M.D. H:MM")
--- Player.save() （顺序为 save 侧实测，两侧已对齐核对）---
  [Str] nickName
  [I]   lastVehicle（-1 时改写为 IVehicle.VID_default）
  [I]   车辆数 carCount
  每辆车:  [I] 车辆 id
           [I] 件数
           每件: [I] 件 id, [I] status(0/1)
  [I] × PRESTIGE_VECTOR_SIZE(15)  lastPrestigeValues
        ★ save 侧是**倒序**写出（下标 14 → 0），load 侧用 addPrestigeValue 头插，正好还原顺序
  [I]   pubIndex（save 写的是 1 基的 getPubInfo().getPubIndex()，load 做 -1）
  [I]   getDriverType() —— 实测就是 Player.sex 字段本身（`Player.java:452` `getDriverType(){return this.sex;}`），
        load 侧用 setSex() 读回，不矛盾
  [I]   mainMenuTuningPageIndex [I] mainMenuCarsOpen [I] mainMenuTuningOpen
--- Gamelogic ---
  [I] winSum  [I] raceSum  [I] retries  [I] offeredRaces
  [F] aiLevelMul
  [I] races.size()，随后每条 RaceChronicle 18 个字段（见下）
  [I] bastardRaceFinished  [I] trialsCompleted  [I] trialProgress
  [I] × 30  trials[i].completed
  [I] prestige                       ← ★ 生涯进度只存这一个整数（+ 15 个历史值）
```

`RaceChronicle` 的 18 个字段（`RaceChronicle.save`，顺序即磁盘顺序）：

```
splineLeft(I) crashes(I) won(I) rescue(I) repair(I) bestLapTime(F) pushes(I)
trackID(I) TOD(I) laps(I) mycar(I) mystage(I) opcar(I) opstage(I)
pinks(I 0/1) prestige(I) opstatus(I) oprank(I)
```

* 初始化值：`trackID=-1, TOD=-1, laps=-1, mycar=-1, mystage=-1, opcar=-1, opstage=-1,
  pinks=false, prestige=0, opstatus=-2, oprank=-1`。
* `loadChronicles` 还会用最后两场的 `trackID` 回填 `lastMapID1/2`（同图规避）。
* 选项文件 `save/game/options` 见 docs（`SAVEFILEID = -19088744`，`SAVEFILEVERSION = 37`，
  且兼容 36/35/33 —— 字段表已在 `util/Config.java` 完整落盘）。

---

## 9. 重制时的取舍

| 原版机制 | 重制建议 |
|---|---|
| prestige = 唯一进度量 + 60 人阶梯 | **照抄**，阶梯表直接用 `out_career_prestige.csv` |
| `getPlayerRank` 的 61 档名次 | 照抄（注意 1 最好、61 最差，别反） |
| `rankingScores/Names`（XP→称号） | 照抄 40 级 + `Intergalactic Pro`；但 **XP 的产出规则要自己设计**（原版在服务端） |
| `updateRanking` 的 ±1/±2 与偶数连败 | 照抄；「胜更弱对手 0 收益」是它逼玩家往上打的关键 |
| `getPrestigeForRace` | **忽略**（恒 0） |
| `getPlayerReputation` | **忽略**（恒 0，循环条件写错） |
| pub 的 4 个场景 + spline 停靠 | 场景照抄；`startsAt/stopsAt/disappearsAt/maxSpeed` 是可用的一手数据 |
| `aiLevelMul` 橡皮筋 | 可照抄；注意 3%/场 的削弱无恢复、且只在 `raceSum >= 10` 后生效 |
| 教学关 | 照抄 30 条 + 3 条/系列 + 宽体奖励；`opRank = 100+x` 的隔离手法值得保留 |
| 赌注系统（6 种 Bet） | 照抄；这是原版唯一的「经济」，没有现金货币 |
| 车辆 prestige 门槛（`minPrestige/2`） | **照抄**，`out_vehicle_prestige.csv` 已是可直接入库的车表 |
| `stylPrestigeMul` / `perfPrestigeMul` | 照抄（逐车 0.25–1.0，别当成恒 1.0 漏掉） |

---

## 10. 未知与待办

| 项 | 状态 |
|---|---|
| XP（`USER_PARAM_XP`）在哪累加、每场给多少 | ✗ **Java 层无写入点**，在元服务器/原生侧 |
| `Gamelogic.getPlayerReputation` 权重表是否有第二实现 | ✗ 未查原生侧 |
| `PubInfo` 的 5 组 Pori 坐标是否与实际地图吻合 | ✗ 未与 `out_named_*.txt` 的地图数据对拍 |
| `offeredRaces` 的语义 | ✓ 实测**从不自增**：只有静态初值 0 / save / load / `resetCareer` 四处出现 ⇒ 死字段，重制可省 |
| 存档槽号来源 | ✓ 实测 `curSaveSlot = 存档路径.substring(14,15)`（`Gamelogic.java:1444`）⇒ 路径固定为 `save/career/00N.sav` |
| `MAX_BET_NUMBER` / `SAME_CAR_IN_PUB_PROBABILITY` 的使用点 | ✓ 已找到（前者是死常量，后者在 `ChallengeOffer.java:214`），详见 §6.1 |
| 车辆的 `getPrestige()`：子类常量（如 700）与基类插值公式（min/max/potential）并存，哪条在跑 | ✗ 未确认 |
| `*_WB`（宽体版）类的 `minPrestige/maxPrestige` 由谁赋值（子类构造器里没有） | ✗ 未追 |
| `justWonTheGame` 之后的流程（通关演出/重置） | ✗ 未追 |
| 改装件表 `perfectTuning`/`dropTable`/`tuningValue`（每车 24 项） | ✗ 未解读（属改装子系统，应并入 docs/35–41 一线） |
