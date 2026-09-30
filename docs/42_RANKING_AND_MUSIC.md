# 42 · 名次分数表（`rankingScores`）与音乐集机制

> 两块都来自 `out_pseudo/java/`，**纯静态、无需实机**。
> 名次表是「数值与规则」里最直接可用的数据之一。

## 1. ★ `rankingScores` —— 完整 40 项（`Gamelogic.java:110`）

```java
java.game.Gamelogic.rankingScores = {
    28,     100,    255,    516,    950,    1588,   2481,   3681,   5130,   6971,
    9218,   11893,  14800,  17868,  21196,  24939,  29214,  34341,  40426,  47306,
    54891,  63216,  72314,  82420,  93492,  105585, 118123, 131339, 145225, 159931,
    176791, 194932, 214225, 234506, 255997, 278957, 302739, 327824, 353986, 381506
};
```

**语义**（`Gamelogic.java:1170`–`1219` 的换算函数）：

```
rank(score):
    从最高位往下找第一个满足  score >= rankingScores[i]  的 i
    若 score < rankingScores[0]  →  单独的低档处理
    返回值 = i + 1            （1 基名次）
```

⇒ 这是**分数 → 名次阈值表**（不是名次 → 分数）。重制时可直接照搬为
「达到第 N 名所需的分数」。

### 1.1 数值特征（实测）

* 首值 **28**、末值 **381506**、共 **40 级**
* **相邻比值整体递减**（最高 `3.5714` → 最低 `1.0777`），但 ✗ **并非严格单调递减**
  （中间有局部回升）—— 说明它是**手工调过的曲线**，不是一条纯公式生成的等比数列。
  ⇒ **必须逐值照抄，不能用一个公式重算**。
* 全部为整数，无负值。
* ★ 配套的 `rankingNames`（`Gamelogic.java:111`，本行与 §3 是 docs/43 补上的）：
  `{"Rookie", "Beginner", "Junior", "Senior", "Amateur", "Semi-pro", "Pro", "National Pro"}` —— 8 档 × 5 级
  （等级 = 下标/5，档内编号 `-F/-E/-D/-C/-B/-A`）。**语义与单位见 docs/43 §1.2**：
  它比的是 **XP（`MetaServer.USER_PARAM_XP`）**，不是 prestige。

产物：`out_ranking.csv`（40 行：`rank, score_threshold, ratio_to_prev`）。

## 2. 音乐集机制（澄清一个伪问题）

### 2.1 集合定义（`sound/Sound.java:2`–`5`）

```
MUSIC_SET_NONE    = -1
MUSIC_SET_MAIN    =  0
MUSIC_SET_INGAME  =  1
MUSIC_SET_CREDITS =  2
```

### 2.2 磁盘侧只有**一个**集合目录

```java
// game/Init.java:34
java.sound.Sound.addMusicSet("music");
```

⇒ `music/` 下的 13 个 `.ogg`（编号 **01–12 + 14**，13 号缺失）全部属于**同一个池**。

### 2.3 ★ 曲目是按**名字**点播的，集合只是容器

```java
// Gamelogic.changeMusic(String name)
case GST_INGAME:  setVolume(CHANNEL_MUSIC, Config.ingameMusicVolume);
                  changeMusicSet(MUSIC_SET_MAIN);
                  findTrack(name);          // ★ 按名字找曲
case GST_MENU:    setVolume(CHANNEL_MUSIC, Config.menuMusicVolume);
                  changeMusicSet(MUSIC_SET_MAIN);
                  findTrack(name);          // ★ 同上
case GST_PUB:     changeMusicSet(MUSIC_SET_NONE);
```

★ 结合上轮结论「曲目文件名前缀 = 曲目 ID」（`Sound.findTrack("<编号>")`）⇒
**具体播哪首由调用方给出的名字/编号决定**，与集合编号**不是**一一对应。

### 2.4 各处的集合使用（实测）

| 位置 | 调用 |
|---|---|
| `game/Init.java:34` | `addMusicSet("music")`（装载） |
| `game/frontend/GameIntro.java:139` | `changeMusicSet(MUSIC_SET_MAIN)` |
| `game/frontend/mainMenu.java:145` | `changeMusicSet(MUSIC_SET_NONE)` |
| `game/frontend/mainMenu.java:660` | `changeMusicSet(MUSIC_SET_MAIN)` |
| `game/Gamelogic.java:1080 / 1088` | `changeMusicSet(MUSIC_SET_MAIN)`（GST_INGAME / GST_MENU 两分支） |
| `game/Gamelogic.java:1092` | `changeMusicSet(MUSIC_SET_NONE)`（GST_PUB） |
| **`game/Track.java:2444`** | ★ `changeMusicSet(MUSIC_SET_INGAME)` —— **赛道内** |

★ 另有 `Sound.java:50` 自己调了一次 `changeMusicSet(MUSIC_SET_NONE)`（初始化）。

### 2.5 重制时的对应关系

| 原版 | 重制建议 |
|---|---|
| 集合 = 运行时容器（4 个） | 可直接**省略**，用「播放列表 + 按名点播」实现 |
| `findTrack("<编号>")` | 保留「**编号即曲名**」的约定，直接把 13 个文件按 01–12+14 命名 |
| `menuMusicVolume` / `ingameMusicVolume` | 两个独立音量，照抄 |
| ✗ `MUSIC_SET_CREDITS` 的使用点 | **未找到**（可能在原生侧或未启用） |

## 3. 未知与待办

| 项 | 状态 |
|---|---|
| `MUSIC_SET_CREDITS` 在哪被使用 | ✗ 未找到（Java 侧无引用） |
| 各上下文**具体**播哪首（`findTrack` 的实参从哪来） | ✗ 未追（调用方传入的 `local0`） |
| 13 号文件缺失是否为官方如此 | ✓ 已确认（编号连续 01–12 + 14） |
| `rankingScores` 的单位（是否可直接当分数用） | ✅ **已定案（docs/43 §1.2）**：单位是 **XP**（`MetaServer.USER_PARAM_XP = 12`），比较对象 `Player.xpBeforeRace`；XP 的累加不在 Java 层 |
| `rankingNames` 的用法 | ✅ **已定案（docs/43 §1.2）**：`rankingNames[level/5] + "-" + FEDCBA[level%5]`，8 档 × 5 级 |

> ⚠ §1 正文里「达到第 N 名所需的分数」这一措辞应读作「达到第 N 级**称号**所需的 XP」——
> 它与「生涯名次」（`getPlayerRank` 1..61，单位 prestige）是两套完全独立的系统，见 docs/43 §1。
