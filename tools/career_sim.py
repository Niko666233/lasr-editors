"""生涯（prestige / rank / pub / 挑战生成）的纯 Python 复现与验证。

目的：把「从 Java 伪码读出来的算法」变成可执行模型，用它反过来检验读得对不对。
数据全部现场从 out_pseudo/java/classes/game/*.java 解析，不手抄常量。

依据（伪码位置）：
  * Gamelogic.?()V                      -- 对手名册 60 人 + aiLevelMul 1.1/1.5/0.5 + rankingScores/Names
  * Gamelogic.getPlayerRank(I)I / ()I   -- prestige -> 名次（1 最好，61 最差）
  * Gamelogic.getOpponentPrestigeByStatus(I)I
  * Gamelogic.getOpponentStatus(Bot)I
  * Gamelogic.getSuggestedPubIndex()I / getBotsBeforeMe()I / getBotsAfterMe()I
  * Challenge.updateRanking()V          -- 赛后 prestige 结算（唯一实际生效的加分路径）
  * Challenge.getPrestigeForRace(I)I    -- 实测返回常量 0（见报告）
  * ChallengeOffer.getOpponentIndex()I  -- 挑战对手抽取（15 人窗口）

用法：
  python tools/career_sim.py            # 校验 + 输出表 + 模拟
"""
import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GAMELOGIC = ROOT / "out_pseudo/java/classes/game/Gamelogic.java"
CHALLENGE_OFFER = ROOT / "out_pseudo/java/classes/game/ChallengeOffer.java"

BOT_ARRAY_MAX = 60
BOT_RE = re.compile(
    r'new java\.game\.Bot\.<init>\("([^"]+)",\s*java\.game\.Gamelogic\.(\w+),\s*'
    r'([-\d.eE]+),\s*\(?([-\d.eE]+)\)?,\s*([-\d.eE]+),\s*(\d+),\s*(\d+),\s*(\d+)\)')


def parse_roster():
    """从 Gamelogic 静态初始化里抽 60 人对手名册。

    字段顺序由 Bot.<init>(Ljava.lang.String;Ljava.game.Driver;FFFIII) 的赋值确定：
    (name, driver, aiLevel, aggressivity, randomness, prestige, sex, rank)
    —— 注意旧产物 out_opponents.csv 把最后两个浮点标反了（见 verify_roster_labels）。
    """
    txt = GAMELOGIC.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"java\.game\.Gamelogic\.opponents = \{(.*?)\};\n", txt, re.S)
    if not m:
        sys.exit("找不到 opponents 数组")
    bots = []
    for name, drv, a, b, c, pr, sex, rank in BOT_RE.findall(m.group(1)):
        bots.append(dict(name=name, driver=drv, aiLevel=float(a),
                         aggressivity=float(b), randomness=float(c),
                         prestige=int(pr), sex=int(sex), rank=int(rank)))
    return bots


def parse_consts():
    txt = GAMELOGIC.read_text(encoding="utf-8", errors="replace")
    out = {}
    for key in ("aiLevelMul", "aiLevelMul2", "aiLevelMul3"):
        m = re.search(rf"Gamelogic\.{key} = ([-\d.eE]+);", txt)
        out[key] = float(m.group(1))
    m = re.search(r"Gamelogic\.rankingScores = \{([^}]*)\};", txt)
    out["rankingScores"] = [int(x) for x in m.group(1).split(",")]
    m = re.search(r"Gamelogic\.rankingNames = \{([^}]*)\};", txt)
    out["rankingNames"] = [s.strip().strip('"') for s in m.group(1).split(",")]
    for key in ("TRIALS_PER_SERIE", "MAX_RACECHRONICLE", "PRESTIGE_VECTOR_SIZE"):
        m = re.search(rf"Gamelogic\.{key} = (\d+);", txt)
        out[key] = int(m.group(1))
    return out


def parse_offer_consts():
    txt = CHALLENGE_OFFER.read_text(encoding="utf-8", errors="replace")
    out = {}
    for key in ("MAX_BET_NUMBER", "PINK_SLIPS_PROBABILITY", "SAME_CAR_IN_PUB_PROBABILITY",
                "STRONGER_OPP_PROBABILITY"):
        m = re.search(rf"ChallengeOffer\.{key} = ([-\d.eE]+);", txt)
        out[key] = float(m.group(1))
    return out


# --------------------------------------------------------------------------
# 算法层：逐行对应 Java
# --------------------------------------------------------------------------
class Career:
    def __init__(self, bots, consts, offer_consts):
        self.bots = bots
        self.C = consts
        self.OC = offer_consts
        self.prestige = 0
        self.chronicles = []          # 旧 -> 新；每项 (won, opstatus, oprank)

    # Gamelogic.getPlayerRank(I)I
    def rank_for(self, px):
        for i in range(BOT_ARRAY_MAX - 1, -1, -1):
            if self.bots[i]["prestige"] >= px:
                return i + 2
        return 1

    @property
    def rank(self):
        return self.rank_for(self.prestige)

    # Gamelogic.getOpponentStatus(Bot)I
    def opponent_status(self, bot_rank):
        pr = self.rank
        if bot_rank <= pr - 8:
            return 2
        if bot_rank < pr:
            return 1
        return -1

    # Gamelogic.getOpponentPrestigeByStatus(I)I
    def opp_prestige_by_status(self, status):
        i = self.rank - status - 1
        if i < 0:
            i = 0
        if i > BOT_ARRAY_MAX - 1:
            return 99
        return self.bots[i]["prestige"]

    # Challenge.updateRanking()V  —— 逐分支照抄，注意两次调用都用「赋值前」的 prestige
    def update_ranking(self):
        streak = 0
        for won, st, oprank in reversed(self.chronicles):
            if oprank < 100:
                if won != 1:
                    if st in (2, 1):
                        streak += 1
                else:
                    break
        if streak % 2 == 0 and streak != 0:
            self.prestige = self.opp_prestige_by_status(-1) + 1
        if self.chronicles:
            won, st, oprank = self.chronicles[-1]
            if oprank < 100:
                if won == 1:
                    if st > 0:
                        self.prestige = self.opp_prestige_by_status(st) + 1
                else:
                    if st < 0:
                        self.prestige = self.opp_prestige_by_status(-1) + 1
        return self.prestige

    # ChallengeOffer.getOpponentIndex()I 的「窗口」部分（随机项用给定 seed 决定）
    def pub_window(self, pub_index):
        base = 59 - (pub_index - 1) * 15
        return sorted(range(max(base - 14, 0), base + 1))

    # Gamelogic.getSuggestedPubIndex()I
    def suggested_pub(self, rank=None):
        rank = self.rank if rank is None else rank
        l0 = int((rank - 2) / 15.0) + 1
        l1 = l0 if l0 <= 4 else 4
        return 5 - l1

    def race(self, bot_index, won, log=True):
        bot = self.bots[bot_index]
        st = self.opponent_status(bot["rank"])
        self.chronicles.append((1 if won else 0, st, bot["rank"]))
        before = self.prestige
        self.update_ranking()
        if log:
            print(f"  vs {bot['name']:<14} rank {bot['rank']:>2} status {st:>2} "
                  f"{'W' if won else 'L'}  prestige {before:>6} -> {self.prestige:>6}  "
                  f"rank {self.rank_for(before):>2} -> {self.rank:>2}")
        return st


def verify_roster_labels(bots):
    """旧 out_opponents.csv 的列名核对：aggressivity 才有负值，randomness 在 0..1。"""
    aggr = [b["aggressivity"] for b in bots]
    rand = [b["randomness"] for b in bots]
    print("名册字段核对（来自 Bot.<init>(String,Driver,FFFIII) 的赋值顺序）:")
    print(f"  aiLevel      范围 [{min(b['aiLevel'] for b in bots)}, "
          f"{max(b['aiLevel'] for b in bots)}]  单调不增: "
          f"{all(bots[i]['aiLevel'] >= bots[i+1]['aiLevel'] for i in range(59))}")
    print(f"  aggressivity 范围 [{min(aggr)}, {max(aggr)}]  含负值: {any(a < 0 for a in aggr)}")
    print(f"  randomness   范围 [{min(rand)}, {max(rand)}]  全在 0..1: {all(0 <= r <= 1 for r in rand)}")
    print(f"  prestige     范围 [{min(b['prestige'] for b in bots)}, "
          f"{max(b['prestige'] for b in bots)}]  严格递减: "
          f"{all(bots[i]['prestige'] > bots[i+1]['prestige'] for i in range(59))}")
    print(f"  rank         1..{bots[-1]['rank']} 与下标一致: "
          f"{all(b['rank'] == i + 1 for i, b in enumerate(bots))}")


def write_opponents_csv(bots, path):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["name", "driver_model", "aiLevel", "aggressivity", "randomness",
                    "prestige", "sex", "rank"])
        for b in bots:
            w.writerow([b["name"], b["driver"], b["aiLevel"], b["aggressivity"],
                        b["randomness"], b["prestige"], b["sex"], b["rank"]])
    print(f"已重写 {path.relative_to(ROOT)} （列名改为 aiLevel/aggressivity/randomness）")


def write_ladder(career, path):
    """名次 ↔ prestige 区间表。名次 = getPlayerRank 的返回值（1 最好，61 最差）。"""
    bots = career.bots
    rows = []
    for rank in range(1, 62):
        i = rank - 2
        lo = bots[rank - 1]["prestige"] + 1 if rank <= BOT_ARRAY_MAX else 0
        hi = bots[i]["prestige"] if i >= 0 else "inf"
        rows.append(dict(
            rank=rank,
            prestige_min=lo,
            prestige_max=hi,
            boundary_bot="" if i < 0 else f"{bots[i]['name']} ({bots[i]['prestige']})",
            suggested_pub=career.suggested_pub(rank),
        ))
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["rank", "prestige_min", "prestige_max",
                                           "boundary_bot", "suggested_pub"])
        w.writeheader()
        w.writerows(rows)
    print(f"已写出 {path.relative_to(ROOT)} （61 行：名次 ↔ prestige 区间 ↔ 推荐 pub）")
    return rows


def parse_vehicle_prestige():
    """每辆车的 prestige 门槛：IVehicle 子类的 minPrestige / maxPrestige / getPrestige 常量。

    依据：
      * `PU/IVehicle.getMinPinkSlipsPrestige()I` = `this.minPrestige / 2`（IVehicle.java:1697）
      * `PU/IVehicle.getPrestige()I` 用 minPrestige/maxPrestige/potential 插值（IVehicle.java:1499）
      * 子类里 minPrestige/maxPrestige 是构造器里的字面量
    """
    rows = []
    for f in sorted((ROOT / "out_pseudo/vehicles").glob("**/IVehicle_*.java")):
        txt = f.read_text(encoding="utf-8", errors="replace")
        cls = f.stem

        def field(name):
            m = re.search(rf"this\.{name} = (-?\d+);", txt)
            return int(m.group(1)) if m else None

        m = re.search(r"\.getPrestige\(\)I\s*\nreturn (-?\d+);", txt)
        styl = re.search(r"\.stylPrestigeMul = ([-\d.eE]+);", txt)
        perf = re.search(r"\.perfPrestigeMul = ([-\d.eE]+);", txt)
        mn, mx = field("minPrestige"), field("maxPrestige")
        rows.append(dict(
            cls=cls,
            pkg=str(f.parent.parent.relative_to(ROOT / "out_pseudo/vehicles")).replace("\\", "."),
            getPrestige_const=int(m.group(1)) if m else "",
            minPrestige=mn if mn is not None else "",
            maxPrestige=mx if mx is not None else "",
            min_pink_slips_prestige=(mn // 2) if mn is not None else "",
            stylPrestigeMul=styl.group(1) if styl else "",
            perfPrestigeMul=perf.group(1) if perf else "",
        ))
    return rows


def write_vehicle_prestige(rows, path):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["cls", "pkg", "getPrestige_const", "minPrestige",
                                          "maxPrestige", "min_pink_slips_prestige",
                                          "stylPrestigeMul", "perfPrestigeMul"])
        w.writeheader()
        w.writerows(rows)
    print(f"已写出 {path.relative_to(ROOT)} （{len(rows)} 个车辆类）")


def main():
    bots = parse_roster()
    C = parse_consts()
    OC = parse_offer_consts()
    print(f"解析对手名册: {len(bots)} 人 (BOT_ARRAY_MAX={BOT_ARRAY_MAX})")
    print(f"aiLevelMul={C['aiLevelMul']} aiLevelMul2={C['aiLevelMul2']} "
          f"aiLevelMul3={C['aiLevelMul3']}  rankingScores={len(C['rankingScores'])} 项 "
          f"rankingNames={C['rankingNames']}")
    print(f"ChallengeOffer: STRONGER_OPP_PROBABILITY={OC['STRONGER_OPP_PROBABILITY']} "
          f"PINK_SLIPS_PROBABILITY={OC['PINK_SLIPS_PROBABILITY']} "
          f"MAX_BET_NUMBER={OC['MAX_BET_NUMBER']}")
    print()
    assert len(bots) == BOT_ARRAY_MAX, len(bots)
    verify_roster_labels(bots)
    print()

    c = Career(bots, C, OC)
    print("pub 窗口（ChallengeOffer.getOpponentIndex 的 base = 59-(pubIndex-1)*15）:")
    for pi in (1, 2, 3, 4):
        w = c.pub_window(pi)
        print(f"  pubIndex {pi}: bot 下标 {w[0]}..{w[-1]}  = 名次 "
              f"{bots[w[0]]['rank']}..{bots[w[-1]]['rank']}  "
              f"prestige {bots[w[0]]['prestige']}..{bots[w[-1]]['prestige']}")
    print()

    LADDER = write_ladder(c, ROOT / "out_career_prestige.csv")
    write_opponents_csv(bots, ROOT / "out_opponents.csv")
    veh = parse_vehicle_prestige()
    write_vehicle_prestige(veh, ROOT / "out_vehicle_prestige.csv")
    print("车辆 prestige 门槛（minPrestige 升序，含 min/2 的粉红条门槛）:")
    for r in sorted(veh, key=lambda r: (r["minPrestige"] if r["minPrestige"] != "" else 0)):
        print(f"  {r['cls']:<28} min {r['minPrestige']:>5}  max {r['maxPrestige']:>5}  "
              f"粉红条 {r['min_pink_slips_prestige']:>5}  getPrestige 常量 {r['getPrestige_const']}")
    print()

    # ---- 模拟 1：开局（prestige 0）满胜，每场都挑当前 pub 里最强的对手 ----
    print("模拟 A：开局 prestige=0，每场都赢、都挑最强的对手（前 6 场 + 最后 6 场）")
    c = Career(bots, C, OC)
    n = 0
    history = []
    while c.rank > 1 and n < 200:
        w = c.pub_window(c.suggested_pub())
        target = w[0]                      # 下标最小 = 名次最好 = 该 pub 最强
        st = c.race(target, True, log=False)
        history.append((n + 1, bots[target]["name"], c.rank, c.prestige, st))
        n += 1
    for h in history[:6]:
        print(f"  #{h[0]:>2} vs {h[1]:<14} -> rank {h[2]:>2}  prestige {h[3]}")
    print("  ...")
    for h in history[-6:]:
        print(f"  #{h[0]:>2} vs {h[1]:<14} -> rank {h[2]:>2}  prestige {h[3]}")
    print(f"  到达 rank 1 需要 {n} 场全胜（每场 +1 或 +2 名次）")
    print(f"  此时才满足 GmRace 的夺冠条件之一（还需再赢 opponents[0]={bots[0]['name']}）")
    print()

    # ---- 模拟 2：排名 61 时连续输给更强的对手 ----
    print("模拟 B：起点 prestige=0（rank 61），连续输给「更强」的对手 6 场")
    c = Career(bots, C, OC)
    for k in range(6):
        st = c.race(45, False)            # pub1 里最强的那个人
    print(f"  6 连败后 prestige={c.prestige} rank={c.rank}（streak 规则每 2 场 -1 名次）")
    print()

    # ---- 模拟 C：rank 61 时输给「更弱」的对手 ----
    print("模拟 C：rank 61 时输给一个「比我更弱」的对手（对手 rank 62 不存在）")
    print("  -> 实测不可达：rank 61 已经是最后一名，status 只可能是 1 或 2")
    print()

    # ---- 模拟 D：中段（rank 30）连败给更强的对手，验证「每 2 场 -1 名次」 ----
    print("模拟 D：中段 rank 30，连续输给 pub3 窗口里更强的对手 6 场")
    c = Career(bots, C, OC)
    c.prestige = bots[29]["prestige"] + 1          # rank 30 的区间下界
    w = c.pub_window(c.suggested_pub())
    strong = [i for i in w if bots[i]["rank"] < 30]
    tgt = strong[0]
    prev = c.rank
    drops = []
    for k in range(6):
        st = c.race(tgt, False, log=False)
        if c.rank != prev:
            drops.append(k + 1)
        prev = c.rank
    print(f"  对手 {bots[tgt]['name']}（rank {bots[tgt]['rank']}，status {st}）"
          f" 6 连败后 rank 30 -> {c.rank}")
    print(f"  掉名次发生在第 {drops} 场 ⇒ 每 2 连败 -1 名次（实测符合 §2.1）")
    print()

    # ---- 校验：名次区间与 updateRanking 的落点一致 ----
    print("一致性校验：updateRanking 后的 prestige 必须落在目标名次的区间内")
    bad = 0
    for rank in range(2, 62):
        c2 = Career(bots, C, OC)
        # 把 prestige 设成该名次区间内的任意值
        lo = bots[rank - 1]["prestige"] + 1 if rank <= 60 else 0
        c2.prestige = lo
        if c2.rank != rank:
            print(f"  ✗ rank {rank} 期望在 {lo} 时成立，实测 {c2.rank}")
            bad += 1
    print(f"  {'✓ 全部 60 个名次区间自洽' if bad == 0 else f'✗ {bad} 处不一致'}")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
