# 59 · 最小可玩竖向切片（数据 → 可开场景）

**状态**：✅ 成立（真实工程 `-batchmode` 实跑：**exit 0 / 47 项断言 0 ✗ / 跑完整圈**）；作者手开一圈后的四条反馈已修（见 §10）
**工具**：`Assets/LASR/Scripts/Slice/*`（运行时）+ `Scripts/Editor/LasrSlice{SceneBuilder,SelfTest}.cs`
**产物**：`Assets/LASR/Scenes/Slice_suburban_track0.unity`、批处理跑出的 `SLICE_SELFTEST_REPORT.txt`

---

## 0. 一句话结论

赛道**不再需要手工摆**：`splines.json` 的主线样条 → 等间距折线 → 双面 ribbon + `MeshCollider`，加上 `tracks.json` 的检查点/发车位，一键生成可开场景；几何与**真实幽灵录像逐点对得上**（起点线 58.74 m 完全一致、4 个检查点弧长最大差 0.13 m）。车在无人值守下**跑完一整圈 1610.3 m**：倒计时 → 起跑 → **4/4 检查点** → 跨过起点线 `Lap = 1 / Finished = True`，全程 `y − 路面 ≥ −0.65 m`、无 NaN、圈速约 137 s。

## 1. 管线与产物

| 文件 | 职责 |
|---|---|
| `Slice/LasrTrackGeometry.cs` | 样条 → 折线 → 路面 ribbon + `MeshCollider`；检查点 `isTrigger` 盒；发车位；弧长采样 / 局部投影 / 行车方向判定 |
| `Slice/LasrRaceLogic.cs` | **纯 .NET**（零 `UnityEngine`）比赛规则：倒计时 → 起跑 → 顺序检查点 → 计圈 / 最佳圈 → 完赛停表 |
| `Slice/LasrSliceCar.cs` | `Rigidbody` + 四轮射线悬挂 + 摩擦圆轮胎（**不用 `WheelCollider`**）；唯一输入入口 `Throttle/Brake/Steer`；`AutoDrive` 供无人值守跑测 |
| `Slice/LasrRaceDirector.cs` | 把逻辑接到场景：每帧 `Tick`、检查点触发/弧长两条推进路径、行车方向自动判定 |
| `Slice/LasrGhostPlayer.cs` | 吃 `Data/sample_ghost_*.json` / `sample_replay_*.json`（按列名驱动，两种形状都吃），位置线性 + 四元数 slerp |
| `Slice/LasrSliceHud.cs` | IMGUI HUD（刻意不引 Canvas/URP 依赖），只读逻辑与车的只读属性；**底部有操作提示** |
| `Slice/LasrKeyboardInput.cs` | **键盘驾驶**（人在编辑器里手开）：W/S/A/D 或方向键、空格 全力刹车、`R` 吸附回路线、`P` 切自动/手动、`T` 幽灵重播；有人的输入就自动让出 AutoDrive。场景里默认 `AutoDrive=false`（自检跑的时候自己打开） |
| `Slice/LasrCheckpointTrigger.cs`、`LasrSimpleChaseCamera.cs`、`LasrFallbackAutoDriver.cs` | 单文件单 `MonoBehaviour`（Unity 硬规则，见 §6） |
| `Editor/LasrSliceSceneBuilder.cs` | 菜单 `Tools ▸ LASR ▸ 切片 ▸ 构建场景` + 静态 `Build(mapId, trackIndex)`；**反射挂组件**，所以写代码的两方互不阻塞编译 |
| `Editor/LasrSliceSelfTest.cs` | 静态 `Run()`：构建 + **47 项断言** + 进 Play 跑 N 秒采遥测 + 硬超时 + 报告；退出码：全绿 0 / 有 ✗ 为 2 |

```bash
# 批处理验收（不要加 -quit，Run 会在 Play 跑完后自己 Exit）
"C:/Program Files/Unity/Hub/Editor/6000.6.3f1/Editor/Unity.exe" -batchmode -nographics \
  -projectPath "<工程>" -executeMethod Lasr.EditorTools.LasrSliceSelfTest.Run \
  -lasrPlaySeconds=20 -logFile "<工程>/Logs/slice.log"
```

## 2. 数据 → 几何（实测，suburban/track0）

* 主线 = `maps/suburban/Track_00.spl2`；按弧长重采样（2 m 间距）得 **806 点 / 1608.8 m**，与 `splines.json` 声明 1606.6 m 差 **+0.135%**（A/B 两族切向归一都过了）。
* 路面 = 1 块 **3224 顶点 / 3220 三角 / 1 MeshCollider**；宽度取样条宽列（本图 3.6–10.5 m）。**路面之外什么都没有**（原版靠原生物理地形兜底）→ 这是 §5 掉出路面的空间条件。
* 检查点 **4 个**、发车位 **8 个**（`tracks.json`），全 13 条赛道合计 82 个检查点与索引一致。
* **与真实录像交叉验证**（本轮最强的一条证据）：切片的起点线 s = 58.74 m 与 `sample_ghost_*` 的 `start_line_s` **完全一致**；4 个检查点弧长与幽灵文件 `checkpoint_s` 逐个对上，**最大差 0.13 m**。
* 检查点触发盒：数据是 `size = (20.00, 7.50, 0.25) m` 且**盒心比路面高 6–7.5 m** ⇒ 照原值做触发器永远压不到。切片按「最薄 2 m + Y 向扩到路面以下 1.5 m」重建，报告里同时打印数据值与实际值。

## 3. ★ 行车方向 = raw s 递减（本轮最重要的数据结论）

`splines.json` 的点序方向**不是**行车方向——车沿 **s 递减** 跑。换算 `driveS = (L − rawS) mod L`，切向取反。三条独立证据：

1. `sample_replay` 476 帧真实坐标投到样条折线上：**116 步前进 / 1 步后退**；
2. `sample_ghost` 的 s 列 = `(−s) mod L` 且随行驶递增；帧内 raw s 66.98 → 58.68（−8.3 m）**恰等于** `lap.distance_m = 8.3`；
3. 起跑后首帧位移与 `start_point.yaw` 方向点乘 = **−1**。

按「递减」折算 `tracks.json` 的检查点顺序为圈内里程，**10/10 赛道单调**（按「递增」一条都不单调）。suburban 圈内里程 = 0 / 435.9 / 778.3 / 1350.9 m。

**检查点编号**：数据的 `index 1` 就是起终点线（suburban cp1 行车里程 = 0.0 m，与 `start_point` 重合）⇒ 逻辑索引 = 数据 index − 1；一圈 = 1 → 2 → … → N−1 → 0（`docs/48 §5.4`）。原版车头 = 模型局部 −Z，`start_point.ypr[0]` 是几何口径 raw 切向。urban 是唯一 yaw 反向的图（点乘 −0.995），两个信号一起翻转、规则自洽。

## 4. 比赛规则逻辑（纯 .NET，可 dotnet 测）

`dotnet run --project Tests~/SliceLogicTests` → **88 / 88 断言全过**（倒计时→起跑、顺序推进、错序/重复忽略并计 `WrongHits`、完整圈后 `BestLap` 更新、多圈完赛停表、固定 dt 时间累加、N=1 退化、`Restart`、越界下标、`Log()` 单行）。回归：`Tests~/LasrDataTests` **348 / 348**。

## 5. 车「开不住」是怎么查出来并修掉的（过程值得留档）

**现象**：车起步到 95 km/h 后 **t≈8.5 s 冲出路面、y 从 117 m 掉到 −84 m**（自由落体），只过 1/4 检查点。

**判别**（关键：先分清「跟线不行」还是「路面有洞」—— 看掉坑前的横向偏离 vs 该处路面半宽）：t=6.5 s 偏离 0.90 m / 半宽 3.98 m（正常）→ t=7.5 s 偏离 5.94 m **>** 半宽 5.51 m → t=8.5 s 偏离 12.60 m 且 y 已低于路面 5.43 m ⇒ **是开出路面边缘再自由落体，不是网格有洞**（另证：806 站站距 1.89–2.12 m 无缺口、幽灵录像逐帧投影全在路面内、沿赛车线 202 点 `OverlapBox` 扫出实体异物 0 个）。

**三条根因**：

1. **【主因】投影窗口跨不过闭环接缝**：`ProjectToRoute(pos, hint, ±80 m)` 在 raw s = 0 / L 处弧长口径不连续 ⇒ 车过接缝后组件里程从 1601.5 卡成 0、前视点落到车**身后** ⇒ 猛打方向冲出路面（也解释了「自算里程卡在起点线」）。
2. **横向项符号写反**：`- lateralErrM * 0.02` 是正反馈（车在航线右侧时应往右打），把 0.9 m 偏离一路放大到 5.9 m。
3. **相对路宽的车速太快**：恒 28 m/s（100 km/h）对最窄 7.2 m 路面 + R≈22 m 的弯（起点后第一个弯在圈内 84–88 m）。

**另有两个隐藏物理坑**（不修就永远动不了）：轮子探地射线起点只在车壳碰盒下沿之上 0.05 m，一旦托底四条射线全打到路面**之下** ⇒ 悬挂/轮胎力全 0，车变成死盒子（实测 150 s 冻在原地、油门 1.00 而速度 0）；车壳碰盒一路拖地（全油门只爬 0.3 m/s）。

**修法（全部落地并实测）**：① 闭环焊死（补 1.51 m 接缝站）+ 投影按周期 L 展开、跨接缝连续；② `AutoDrive` 换纯跟踪（前视 8–22 m 随速缩放）+ 曲率限速 `v = √(5.5R)`（前方 60 m 取最小且算刹得住）+ 横向回中（符号修正，0.15 rad/m，最高优先级）+ 转向变化率限幅 3/s；③ 路面半宽下限 4.6 m + 两侧 1.5 m 隐形护栏；④ 探地射线起点抬高 0.6 m + 忽略 trigger + 跳过自身碰体，车壳碰盒拆成「门盒触发器 + 抬高保险杠（局部 y 0.65–1.35）」；⑤ 自愈：横向 > 半宽+2.5 m 或 y < 路面−8 m ⇒ 回位清速度；速度 < 0.5 m/s 持续 1.5 s ⇒ 记录诊断 + 沿路线前移 4 m（本轮触发 6 次、每次救回）；⑥ `AutoDriveTargetSpeedMs` 28 → **15 m/s（54 km/h，为「跑得完」刻意调慢）**、`sleepThreshold = 0` + 每帧 `WakeUp`、质心降到 0.22 m 抗翻车。

**最终实测（真实工程 `-lasrPlaySeconds=240`）**：`EXIT = 0`、**33 项断言 0 ✗**、`问题：0（全通过）`；车动 447.9 m（= 离发车位最远水平距离；本圈实跑 1610.3 m）、组件速度峰值 71.6 km/h、`Hits = 4 / Lap = 1 / Finished = True`、跨线时刻 t ≈ 136.5 s、`min(y − 路面) = −0.65 m`、无 NaN、幽灵前 20 s 位移 111.2 m、掉坑恢复 0 次。

## 6. Unity 硬事实（本轮实测，都会咬人）

1. **只给「类名 == 文件名」的 MonoBehaviour 建 MonoScript**：同文件里的第二个 MonoBehaviour、或类名与文件名不一致的（`LasrDataBehaviour` 曾写在 `LasrDataUnity.cs`）进 Play 会被判成 missing script 剥掉。⇒ 一个 MonoBehaviour 一个同名文件（本轮因此拆出 4 个文件，并把 `LasrDataBehaviour.cs` 单独落盘——**这是对既有交付包的真修复**）。
2. **要存进场景的数据结构必须 `[System.Serializable]`**，否则进 Play 变空表（曾致自动驾驶拿不到路线，车 20 s 只挪 0.3 m）。
3. **`-batchmode` 下收到尾就 `EditorApplication.Exit(code)`**，别等 Play 自己退出（`isPlaying = false` 会卡住主循环）。
4. 同一 `projectPath` **不能并发两个 Unity 实例**（`Aborting batchmode: … another Unity instance is running`）；**跑批处理期间改 .cs 会强制重编译打断 Play**（外层退出码会变成 127 之类的杂音，别当代码错）。
5. **`Component.name` 改的是 `GameObject` 的名字**：`gate.name = "LasrGateTrigger"` 把 `Car_Player` 改了名 ⇒ 整轮「找不到 Car_Player」空跑。
6. 本机另有 Unity **5.6.7f1**（`C:/Program Files/Unity/Editor/Unity.exe`）；命令务必用 Hub 路径 `…/Hub/Editor/6000.6.3f1/Editor/Unity.exe`。

## 7. 数据层缺口清单（切片暴露出来的）

| # | 现象 | 影响 / 待办 |
|---|---|---|
| G1 | 检查点触发盒数据 `size.z = 0.25 m`、盒心高路面 6–7.5 m，照原值做触发器压不到 | 与 `docs/48` 的未决项「Trigger 三个 float 是 **size 还是 halfsize**」直接相关；需实机开 `Config.showTriggers` 目视。切片暂时重建盒 |
| G2 | 路面宽度只有样条宽列，**没有护栏/路面外碰撞体** | 原版靠原生地形（ODE）兜底，数据层不提供 ⇒ 重制必须自造（护栏或宽地板） |
| G3 | 幽灵样本 `sample_ghost_suburban_track0_niko_lap1.json` 只有 **61 帧 ≈ 6.1 s @10 Hz** | 与整圈（1.6 km）不符 ⇒ 需确认是「采样片段」还是解析漏帧（`docs/54` 记 dt 中位 0.1009 s） |
| G4 | 没有「路线限速 / 曲率」数据 | 原版 AI 用原生 `Controller` + 29 命令 + `catchup_*`（`docs/21`）⇒ 重制要自己从样条算，或解原生 AI 命令表 |
| G5 | `tracks[].visualisation_bounds` 的 Y 退化（min/max 都 −10） | 只能当 XZ 用（已知，`docs/50`）；Gizmo/边界别拿它当高度 |
| G6 | glTFast **已在 `manifest.json`（6.20.0）** | 原记的 A8 缺口「GLB 路径未验证」现在可测 |
| G7 | 闭环接缝：样条首尾相距 1.51 m，弧长口径在 s=0/L 处不连续 | 任何「按弧长做局部窗口搜索」的代码都会在接缝处失效（本轮掉出路面的主因）⇒ 消费方要按周期 L 展开 |

## 8. 未解清单（✗）

* **`WrongHits = 3`**：CP2/CP3/CP4 每处在有效命中后 0.2–0.3 m 又在 2 m 薄门盒里二次进入各多计 1 次（不影响 `Hits/Lap`）⇒ 正式实现要按原版「命中 nextCP 才算」+ 去抖窗口。
* **卡住自愈触发 6 次**：车低速蹭到隐形护栏被楔住（每次都被救回）⇒ 护栏几何/摩擦还要调，或改「滑行引导」而非硬墙。
* **幽灵车是混合体**：真数据只有 6.9 s，之后是按录像末段速度沿路线续跑（G3 的直接后果）。
* **遥测噪声**：报告里「速度峰值 237.3 km/h」「位移 447.9 m」是采样抖动/回位瞬移与「离发车位最远距离」口径造成的伪值（真实车速 ≈71.6 km/h、本圈 1610.3 m）。
* **只在 suburban/track0 验过**：另 12 条赛道未跑（urban 的 yaw 反向已识别，理论上需翻转两个信号）。
* **未做**：AI 对手车、救援/回位规则、碰撞与损伤、音效接入、正式 HUD（当前 IMGUI 只是调试面板）、场景环境网格（只用了 ribbon，`track_*` 大网格未摆）。
* **手感**：已按作者手开反馈调过（§10 ②③），**仍需要作者复评**（`AutoDrive` 跑圈用的 15 m/s 只是无人值守的下限，手动不受限；场景里选中 `Car_Player` 可在 Inspector 直接调全部手感参数）。

## 9. 怎么亲手开（给作者的操作步骤）

1. Unity Hub 打开 `remaster/unity_project`（版本 **6000.6.3f1**）。首次打开会导入几分钟。
2. 若模型没贴图/材质是粉的：菜单 `Tools ▸ LASR ▸ 重导全部模型（并绑定贴图）`，再 `Tools ▸ LASR ▸ 应用音频设置`。
3. 打开场景 `Assets/LASR/Scenes/Slice_suburban_track0.unity`（**已在 Build Settings 里**）。想换图/换赛道走 `Tools ▸ LASR ▸ 切片 ▸ 构建场景`（当前 = `suburban` / track 0）。
4. 按 **Play**。倒计时 3 秒后起跑；HUD 左上角有速度/挡位/转速/圈数/检查点/时间/最佳圈，底部一行是操作提示。
5. 操作：**W/S/A/D**（或方向键）油门刹车转向，**空格** 全力刹车，**R** 把车吸附回路线（冲出路面或卡住时用），**P** 在「人开 / 自动跑」之间切换（想先看它自己跑一圈就按 P），**T** 幽灵车重播。
6. 幽灵车 `Car_Ghost` 重放 `Data/sample_ghost_suburban_track0_niko_lap1.json`（真数据只有 6.9 s，之后按录像末段速度沿路线续跑）。
7. 命令行验收（不开编辑器）：见 §1 的批处理命令；报告写在工程根 `SLICE_SELFTEST_REPORT.txt`。

> 复现：验收标准的逐条对照见 `docs/01_ROADMAP.md §3①`；数据层与包的约定见 `docs/58`；设计约定见 `remaster/unity_project/IDEA.md`。

## 10. 作者手开一圈后的四条修复（2026-09-29，真工程 exit 0 / 47 ✓ 0 ✗）

| # | 反馈 | 根因（实测，非猜测） | 修法与验证 |
|---|---|---|---|
| ① | **赛道方向与原版相反** | 发车位根节点朝向反 180°：`LookRotation(drive)` 把根 **+Z** 对到行车方向，而**原版车辆对象的前向 = 局部 −Z**（`docs/54` 录像四元数前向；`docs/56` 槽位表前大灯槽 z=−1.728 m / 尾灯 +1.578 m ⇒ 车体帧前方 = −Z）；再叠加 `CarVisualYawOffset = 180°` ⇒ 双重翻转 | `LookRotation(−drive)`（有数据自带 ypr 时优先用它）+ 视觉偏移 180°→0；`LasrSliceCar.Forward = −transform.forward` 统一所有前向用途。**回归断言**：8/8 格位车头·行车切向 = 1.000；`Car_Player` 与幽灵第 0 帧夹角 **0.9°**；起步 t≈0.4 s 位移·切向 = **0.982**（改前此刻 str=0.61 正在掉头）。我另从场景文件独立读出 `Car_Player` 局部 −Z = **(1.0, −0.0, −0.011)** = +x = 行车方向（改前 (−1,0,+0.011)） |
| ② | 悬挂太高太软、急转侧翻 | 量化：k=30 kN/m、行程 0.15 m、质心 0.22 m ⇒ 离地 0.66 m / 轮距 1.5 m ⇒ 侧翻门限 1.13 g **低于**轮胎能给的 1.2 g，**结构上必翻** | k→52 kN/m、c→3.6 kN·s/m、静止长度 0.35→0.28 m、行程→0.12 m、质心→**0.14 m**（门限提到 2.6 g）、新增前后防倾杆 22k/16k + 侧倾限幅、侧偏刚度 8→12、抓地 1.2→1.45、最大舵角 35→32°、转向衰减 110 km/h。实测：全程侧倾峰值 **13.9°**、`min(up·up)=0.971`（从未倒扣）、刹车时压缩峰值 0.091 m < 行程 0.12 m；满舵探针（67 km/h）min up·up=0.974 |
| ③ | 车轮看不到、刹车时陷进地里 | 三处叠加：轮位用车壳包围盒拍阈值（视觉 ±0.609/±1.13 vs 物理 ±0.75/±1.30）、轮心锚点 y=0 ⇒ 车体原点离地 −0.44 m（车壳与轮子都悬空）、**没有任何逐帧更新** | 构建器按**网格实测**注入布局（r=0.345 m、轮距 1.44 m、轴距 2.41 m、静止离地 **0.140 m**）；`LasrSliceCar` 新增 `LateUpdate`：轮心 = 接地点 + 半径 − 悬挂压缩、前轮转向、按轮角速度自转。实测：轮子视觉 4/4 由悬挂驱动、**轮底与路面最大偏差 0.018 m**、轮外沿 0.845 m ≥ 车壳半宽 0.855 m − 3 cm |
| ④ | 车壳贴图不正常 | 数据层把 `stock_interior.png`（内饰展开图：整图 32.7% 全透明，按面积加权**车壳 41.76% 的 UV 落在透明像素上**）当车壳主贴图 | 场景改用同车包 `paintjob_0.png`（1024²、车壳 UV 落透明像素 **0.00%**）+ 材质强制 Opaque。**但这是「按可判定证据挑的最佳候选」，标待确认**：材料表 chassis 主贴图槽 id=13，RPAK 目录里 13=glosspaint_0 / 14=paintjob_0 / 11=stock_interior，该车 paintjob 件资源 id = 26/32/45/46/133 ⇒ **id 空间未闭合（B7）**；B7 解了换个常量即可 |
| ⑤ | （顺手）手感调参入口 | — | `LasrCarSetup` 标 `[Serializable]`、`LasrSliceCar` 用 `[SerializeField]` 暴露 ⇒ **场景里选中 `Car_Player` 就能在 Inspector 调全部手感参数**（弹簧/阻尼/行程/质心/防倾杆/舵角/轮胎/刹车），不用改码、不用重建场景 |

**这四条里我独立复核过的**：真实工程 `-batchmode` 重跑 **exit 0 / 47 ✓ 0 ✗ / 0 编译错误**；上面 ①③ 的几何我从生成好的场景文件里另行读出确认；② 的值从场景 YAML 读得（`SuspensionStiffness: 52000`、`CenterOfMassYM: 0.14`、`AntiRollFrontNPerM: 22000`、`MaxSteerDeg: 32`）。
**✗ 仍然只能由人看的**：贴图好不好看、轮子在屏幕上到底显不显眼、幽灵车姿态观感 —— 全程 `-nographics` 批处理，**没有渲染过一帧**。
