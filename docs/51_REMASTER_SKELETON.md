# 51 · 重制骨架：`out_*` → 引擎无关数据层

> 覆盖面：`remaster/`（23 数据集 / 18 schema / 80 项校验）+ 四条只有这份文档写的数据事实。
> 标注：✓ = 机械提取或双路核对过；✗ = 仍未定（写清验证方法）；「模板残留」= 字节里真写着但非玩家所见值。
>
> **数据集清单、置信度图例、两族 spline、重跑坑 → 看 [`../remaster/README.md`](../remaster/README.md)（权威版，本文不重复）。**
> 目的：把 90+ 份 `out_*` 逆向产物归一化成现代引擎可直接读的一层，
> 让重制项目不必再碰 Java 伪码与私有格式。数据语义核实见 `docs/48`–`docs/50`、`docs/52`–`docs/57`。

## 1. 规模（`validate.py --stats`，全部机械计数）

| 维度 | 值 | 维度 | 值 |
|---|---|---|---|
| 地图 | 15（10 主图 + 4 `_b` 小图 + 1 test） | 赛道 | 13（+ test 图 3 条 dev） |
| 检查点 | 82 | banner 触发器 | 606 |
| spline | 70 条（68 可行驶 + 2 赛前镜头） | 路线总长 | **200,320.7 m** |
| 声学盒 | 463（room + reverb） | 场景实例 | 15,179 |
| 车辆变体 | 23（10 车 + 宽体） | 零件类 | 1,808（其中 **973 个 `kind` 有字节码真值**） |
| 轮胎套件 | 11 | 对手 / 段位 / 试炼 | 60 / 61 / 30 |
| UI 布局 / 文本 | 1058 / 445 | locale | 75 段 940 键 |
| 音乐 / FSB 采样 | 13 / 264（→ 262 WAV） | AI 指令 | 29 |
| 装配 | 671 零件类 / 447 带网格 / 63 槽 | 网格 | 602 车包条目 / 467 id 全解 |

## 2. 重制时才容易踩的四条（✓ 已查实）

1. **spline 有两族**：A 族（53 条，`width` 4 列）切向可直接当 Hermite 切向；B 族（17 条，等宽）
   **必须先按 `|t0|/弦长` 归一到弦长**，否则误差可达 **14.5%**（归一化后中位 0.41%）。
   实现：`remaster/tools/sample_spline.py --tangent-mode auto`；详见 `remaster/README.md` §3。
2. **起点朝向 = `yaw = atan2(dx, dz)`，单位弧度**，`yaw` 基准 `+Z` 轴，`ypr[1]/ypr[2]` 是 pitch/roll。
   判据：10 张主图里 7 张与最近 spline 段方向差 <3.8°，2 张 ±180°（起点贴路线末端）、
   1 张 −15°（发车格朝向本就与出弯不同）⇒ 重制的发车位朝向不用再试。
3. **检查点 XZ 全落在赛道真实可视化边界内（82/82）**：要用 `tracks.json` 的 `visualisation_bounds`
   （来自赛道类），**不要用** `maps.json` 里的模板残留 `bounds`（其 Y 退化到 `-10/-10`，不能判高度）。
4. **按 id 取网格，不要按名字**：材质表 id↔名在 WB（宽体）区整体平移一件，
   `data/mesh_id_map.json` 的 `resolved_id` 才是可用值（`docs/57 §8`）。

## 3. 骨架里**没有**的东西（✗ 别指望）

| 缺什么 | 原因 | 去哪找 |
|---|---|---|
| 美术 / 音频本体 | ✅ 已导出：1,218 纹理 PNG、764 网格 OBJ、665 MTL、262 WAV、13 Ogg | `docs/52`、`docs/31` |
| 零件性能增益 | ✅ 已闭环：`onInstall()` 推物理参数 → 原生 info block | `docs/55` |
| TOD 昼夜切换行为 | Java 层未实现（索引传入 `prepareTrack(MapTrack,int)` 后从未被读） | `docs/50 §9`「TOD」行 |
| 商店 / 赠予 / 试炼发零件 | 事件无 handler（断头）；与「游戏里没有钱」一致 | `docs/50 §9`「商店」行 |
| 32 人房发车位映射 | `startOrder[8]` vs `Racers[32]`，需联机实机 | `docs/50 §9`「发车位」行 |
| 联机大厅 / 房间 / 聊天 | 前端里整类不存在 | `docs/49 §12` |
| 手性 / 宽度左右符号 | 数据侧无法自证 | `remaster/engine/mapping.md §0.2` 给了验证方法 |

## 4. 怎么继续用

```bash
python remaster/tools/build.py            # 改数据源后重建（幂等，或 --only tracks）
python remaster/tools/validate.py         # 80 项断言，失败即 exit 1 → remaster/report.json
python remaster/tools/sample_spline.py --list
python remaster/tools/sample_spline.py --spline "boulevard/Track_00_normal" --step 10 --format csv
```

扩展优先级见 `01_ROADMAP.md` §3（竖向切片 → 资产交付包 → 补漏）。
