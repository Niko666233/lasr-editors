# 文档索引 / Analysis Notes

这些是从一个更大的逆向工作区里挑出来的**分析笔记**，记录「工具要读写的那些格式长什么样」，
以及每个结论是怎么被证实的。按编号排序，入口是 [`00_INDEX.md`](00_INDEX.md)（全量索引）
与 [`01_ROADMAP.md`](01_ROADMAP.md)（进度与未解项）。

**与两个编辑器最相关的几篇：**

| 文档 | 内容 |
|---|---|
| [`02_VM_INTERNALS.md`](02_VM_INTERNALS.md) · [`08_VM_OPCODES.md`](08_VM_OPCODES.md) | TUFA 容器与自研 VM 字节码（工具「原地改 4 字节字面量」的依据） |
| [`14_CAR_DATA.md`](14_CAR_DATA.md) | 车辆/零件参数在类里的分布 |
| [`50_DATA_LAYER.md`](50_DATA_LAYER.md) | 数据层总览（存档、车型、零件槽位） |
| [`55_STATS_AND_SLOTS.md`](55_STATS_AND_SLOTS.md) · [`56_SLOT_GEOMETRY.md`](56_SLOT_GEOMETRY.md) | 性能条 7 项的数据来源 + ITEMSLOT ↔ 物理槽 |
| [`35_TYRE_COMPOUNDS.md`](35_TYRE_COMPOUNDS.md) · [`37`](37_PACEJKA_SLOTS.md)–[`41`](41_TYRE_REMAKE_SPEC.md) | 轮胎配方与 Pacejka 槽（抓地力 µ 在哪） |
| [`48_RACE_SESSION_RULES.md`](48_RACE_SESSION_RULES.md) | 一局比赛的会话规则（含氮气奖励刻度） |
| [`60_EDITORS.md`](60_EDITORS.md) | **两个编辑器自身的实现说明、测试矩阵与已知缺口** |
| [`61_PART_PARAM_LOCATIONS.md`](61_PART_PARAM_LOCATIONS.md) | 三类「看着找不到值」的参数到底在哪（外观件/氮气/轮胎/减重/涡轮） |

**注意：** `annex/`（游戏原始文本/数据转储）与各类解包产物**刻意不在本仓库**，
原因见根目录 [NOTICE.md](../NOTICE.md)。文档里提到 `out_pseudo/`、`extracted/` 等路径，
是该工作区内部的分析输入，不随本仓库分发。

所有文档同样由 AI 生成，结论以文档内标注的实测为准；标着「未验证 / 待实机」的部分
尚未经过人工上机确认。
