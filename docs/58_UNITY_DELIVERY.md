# 58 · Unity 6.6 资产交付包（`remaster/unity_project/`）

> 目标：把逆向产物变成**能直接在 Unity 里开工**的工程 —— 网格 / 贴图 / 音频 / 音乐 / 数据 / C# 工具，
> 不依赖原版游戏、Python 或本仓库。
> 生成器：`remaster/tools/pack_unity.py`（幂等，约 20 秒）；包校验：`remaster/tools/verify_unity_package.py`（19 项）；
> 工程内自检：菜单 `Tools ▸ LASR ▸ 导入自检（资产）` 或 `-executeMethod Lasr.ImportSelfTest.Run`。
> 交付说明（给使用者看的一页）：`remaster/unity_project/README.md`（源：`remaster/unity_package_readme.md`）。

---

## 0. 一句话结论

`remaster/unity_project/` 是一个**可用 Unity 6000.6.3f1 直接打开**的工程：
**764 网格（OBJ + GLB 两族）／1,218 贴图／262 WAV／13 Ogg／23 数据集** 全在 `Assets/LASR/` 下，
配 C# 数据层与 Editor 工具把导入设置、材质绑定、音频参数自动化。
**本机上已实测**：Python 侧 19/19 校验通过；Unity 批处理导入 + 自检 **exit 0**（规模、缩放、材质贴图绑定、UV、数据全部核对）。

---

## 1. 目录与产物

```
remaster/unity_project/                 ← 交付物（可直接 Unity 打开）
├── README.md                           交付说明（导入步骤 / 约定 / 已知缺口）
├── ProjectSettings/ Packages/          起手工程设置（内置渲染管线 + Gamma，见 §5 建议）
├── Tests~/                             dotnet 测试工程（Unity 忽略 ~ 结尾目录）
└── Assets/LASR/
    ├── Meshes_OBJ/<组>/**              764 OBJ + 665 MTL（零依赖主路径；贴图路径已重写）
    ├── Meshes_GLB/<组>/**              764 GLB（材质/alpha 写死，单位已烘）
    ├── Textures/<组>/**               1,218 PNG（与网格同构目录）
    ├── Audio/<bank>/*.wav              262 WAV
    ├── Music/*.ogg                     13 首
    ├── Data/                           23 数据集 + 18 schema + 5 辅助 JSON + 5 sample
    └── Scripts/                        运行时（LasrJson/LasrData/LasrDataUnity）+ Editor 工具
```

辅助 JSON（本包生成，非逆向数据本体）：

| 文件 | 内容 |
|---|---|
| `Data/texture_info.json` | 每张贴图：尺寸 / alpha 分类与覆盖率 / 是否 sRGB / 角色（base·mask·shadow·dirt·extra）+ 置信度 + `alpha_mode_hint` |
| `Data/material_map.json` | 每个网格：主贴图、零件级 mask/shadow/dirt（**inferred**）、OBJ 与 GLB 路径 |
| `Data/mesh_textures.csv` | 极简边表（obj → base_texture），C# 侧零依赖读取，材质自动绑定用 |
| `Data/audio_meta.json` | 每条采样：循环点、频率、声道、3D 参数、分类；音乐清单 |
| `Data/mesh_import.json` | 单位 / 坐标 / 轴向约定（含「数据 JSON 是原生帧」的说明） |
| `Data/package_manifest.json` | 全量清单：每类计数、数据集条数、源文件 sha256（校验基准） |

工具（`remaster/tools/`）：

* `pack_unity.py` —— 生成包（`--limit/--tex-limit` 冒烟、`--no-obj/--no-glb/--no-music`、`--keep` 增量）
* `verify_unity_package.py` —— 只读校验：GLB 结构 / 引用 / 计数 / 哈希 / 与数据层交叉校验

---

## 2. 实测结论（本机，Unity 6000.6.3f1，全部可复现）

| 项 | 结果 | 判据 |
|---|---|---|
| 包结构校验 | **19/19 通过** | `verify_unity_package.py` |
| GLB 合法性 | 764/764 | 分块长度自洽、accessor ⊆ bufferView ⊆ buffer、POSITION 带 min/max、图片 uri 全部落地 |
| 顶点交叉校验 | **1,081,563** | 与 `remaster/validate.py` 的 `mesh_verts` 完全一致（两条独立路径） |
| **Unity 全量导入自检** | **exit 0**（`LASR_IMPORT_REPORT.txt`） | 764 模型 / 1,218 贴图 / 262 WAV / 13 Ogg / 52 JSON 全部导入；**0 编译错误**（C# 层 6,356 行全部编译通过） |
| **C# 数据层（工程内实跑）** | **23/23 数据集通过** | `Lasr.EditorTools.LasrPackageTools.ValidateImport`：23 文件 / 7.6 MiB 解析 0.22 s，sha256、字节数、count 全部相符 |
| Unity 导入自检（子集工程） | **exit 0** | 65 模型 / 131 贴图 / 24 音频 / 52 TextAsset，机制与全量一致（先跑的子集，用来快速迭代） |
| 单位换算 | ✓ | chassis 包围盒 **1.709 × 1.191 × 3.648 m**（源 170.9 × 119.1 × 364.8 cm ⇒ globalScale 0.01 生效） |
| 材质 → 贴图绑定 | ✓（需 `LasrModelMaterialFixer`） | 536 条边表 → **1,072 个材质槽**自动绑上（`chassis → stock_interior.png` 等） |
| UV 约定 | ✓ **V 未翻转**（原样导入） | 对 4,000 个源 `vt` 做集合假设检验：原样匹配 **4,420** / 翻转(1-v) 匹配 **27** |
| 数据 / 音频导入 | ✓ | 23 数据集 + 辅助 JSON 全部成 TextAsset；262 WAV 全成 AudioClip |
| 纹理导入设置 | ✓（`LasrAssetPostprocessor` 生效） | 抽样：`stock_interior.png` sRGB + maxSize 1024；`track_other_comb.png` 2048 —— 与 `texture_info.json` 一致 |
| GLB 路径 | ✗ **未能验证** | 工程未装 glTFast ⇒ `.glb` 只作为普通资产存在（模型计数 0）。见 §4 A8 |

> 工程跑过一遍全量导入后 `Library/` 约 **881 MB**（工程合计 1.3 GB）。想从零重来：删掉 `Library/` 即可，
> Unity 会重新导入（约 3–5 分钟）。`LASR_IMPORT_REPORT.txt` 留在工程根，是那一次自检的原始报告。

### 2.1 两个必须知道的行为（都是实测出来的）

1. **Unity 的 OBJ 导入器不会绑 `.mtl` 里的贴图**：它按 `newmtl` 建出材质（名字对），但 `mainTexture` 为空。
   ⇒ 交付包里的 `LasrModelMaterialFixer`（`OnPostprocessModel` + `Data/mesh_textures.csv`）负责补上；
   装了这个脚本**之后**需要跑一次 `Tools ▸ LASR ▸ 重导全部模型（并绑定贴图）` ——
   因为 Unity 6 的导入结果**按内容哈希缓存**，模型没变就不会再触发导入回调（我踩过：`touch` 无效）。
2. **UV 原样进入 Unity**：源 `.obj` 的 `vt` 的 V 范围是 **[−1, 1]**（不是常见 [0,1]），Unity 不做翻转换算。
   GLB 里按 glTF 规范（左上原点）**翻了 V**；OBJ 保留原点约定原样 —— 两条路径在规范上等价，
   但 GLB 那条**没有实机验证**（见 A8）。

---

## 3. 交付包里的 C# 层

| 文件 | 作用 |
|---|---|
| `Scripts/LasrJson.cs` | 自写最小 JSON 解析器（零依赖，Unity 无 `System.Text.Json`） |
| `Scripts/LasrData.cs` | 纯 .NET 数据加载器：`Data/*.json` → 节点树 + 类型化投影（`Tracks`/`Splines`/`RaceRules`/`Vehicles`/…） |
| `Scripts/LasrDataUnity.cs` | Unity 薄封装（路径解析 / `TextAsset[]` 重载） |
| `Scripts/Editor/LasrPackageTools.cs` | 导入校验、应用纹理设置、应用音频设置（按 `audio_meta.json` 设 loop/压缩 + 生成 `LasrAudioCatalog.asset`） |
| `Scripts/Editor/LasrAssetPostprocessor.cs` | 模型缩放 `0.01`、纹理 sRGB/alpha/压缩（按 `texture_info.json`） |
| `Scripts/Editor/LasrModelMaterialFixer.cs` | **OBJ 材质 → 主贴图**自动绑定 + 一键重导（§2.1 的补丁） |
| `Scripts/Editor/LasrImportSelfTest.cs` | 资产导入自检（计数 / 缩放 / UV / 材质），可跑批处理 |
| `Scripts/Editor/LasrTrackGizmos.cs` | 用 `tracks.json` 在场景里画检查点 / 发车位 / banner / 边界（Y 退化的模板边界只画 XZ 平面 + 四角竖标，不当高度用） |

### 3.1 C# 层是怎么验的（不是「写完就算」）

* **dotnet 侧真编译真跑**：`Tests~/LasrDataTests.csproj` 钉死 `LangVersion 9.0`（任何 C# 10+ 语法直接编译失败）、
  **零 PackageReference** + 清空 NuGet 源（离线可复现）；显式 `<Compile Include>` 只纳入数据层与断言程序。
  **348 条断言全过，退出码 0**：
  `dotnet run --project "remaster/unity_project/Tests~/LasrDataTests.csproj"`。
  这套断言抓出 5 个真 bug（`TryGet` 把 Null 单例覆盖成 null、构造函数没给 Root 赋值、
  `overall_length` 是 `{value,_confidence}` 包装、`maps.bounds` 判数组不判对象、样条 A/B 族条目认错）。
* **Unity API 桩编译**：`Tests~/UnityApiStubCheck/` 手写桩（只声明 6 个脚本用到的成员，签名按 6000.0 文档核对）
  把 Editor 脚本一起编一遍 ⇒ 抓出 3 个只有 Unity 才会报的错（把消息回调 `OnPreprocessModel` 写成 `override`、
  两个重载签名撞车 CS0111、把 `IReadOnlyList` 当节点用）。
* **最后在真 Unity 里编**：全量工程批处理 **0 编译错误**（见上表）。

> `package_manifest.json` 里 `datasets[].count` 的口径**不唯一**（三种，实测 23/23 命中）：
> `primary` = 主容器行数（tracks 13 / splines 70 / triggers 606…）、`_meta.count`（career 191 / stats 97…）、
> `top_sections` = 非 `_meta` 顶层节数（ui 4 / race_results 14…）。C# 侧用候选匹配，展示时会写明命中哪一种 ——
> 别把它当成「条数」的唯一定义。

---

## 4. 还没做的 / 已知缺口

| # | 项 | 说明 |
|---|---|---|
| A8 | **GLB 路径未验证** | 装 `com.unity.cloud.gltfast`（Unity Registry）→ 跑导入自检看 GLB 计数与贴图方向。glTF 的坐标系转换（glTFast 反转 X 轴）与我的 UV 翻转都属规范实现，但没在本机跑过 |
| B7 | **零件贴图 id → 文件名 未完全对位** | 536 个网格的**主贴图**由 `.mtl` 精确给出；零件类的 `texture_id`/`mask_texture`/`shadow_texture` 是资源 id，只解出 12/433（`material_map.json` 标 `inferred` 并保留原始 id）。补法：从 RPAK 目录记录尾部的 `(group\|type, index)` 反解 id 空间 |
| — | 2 条音频与他条共用文件 | 原导出时 `!` → `_` 冲突；`audio_meta.clips[]` 里带 `duplicate_of` |
| — | 材质是 PBR 近似 | 原版 Blinn-Phong + 内建 wreck/dirt 层 + 球谐环境光；精确公式见 `docs/22/23/30` |
| — | 工程默认 Gamma + 内置渲染管线 | 起手设置照抄 Unity 6.6 默认；重制建议切 **Linear**（Project Settings ▸ Player ▸ Color Space），URP 与否自定 —— 贴图 `sRGB` 标记已按角色给出 |
| ~~A8~~ ✅ | **GLB 路径可测了** | `manifest.json` 里**已有** `com.unity.cloud.gltfast 6.20.0`（`packages-lock` 已解析）⇒ 跑一次导入自检看 GLB 计数与贴图方向即可，不再是缺口 |
| 已修 | **`LasrDataBehaviour` 挂不进场景**（真缺陷） | 它原来写在 `LasrDataUnity.cs` 里，而 Unity **只给「类名 == 文件名」的 MonoBehaviour 建 MonoScript** ⇒ 场景里挂过它的对象进 Play 会变成 missing script 被剥掉。已拆成独立文件 `Scripts/LasrDataBehaviour.cs`（+ `[System.Serializable]` / `[AddComponentMenu]` 一并核过）。同时提醒：文档里「挂一个 `LasrDataBehaviour` 到场景」的说法此前是**做不到的**，现已成立 |

---

## 5. 复现 / 重跑

```bash
cd <LASR_Reverse_Engineering>
PY=./.capenv/Scripts/python.exe

$PY remaster/tools/pack_unity.py                    # 重建整个交付包（幂等；不碰 Scripts/）
$PY remaster/tools/verify_unity_package.py          # 19 项包校验
$PY remaster/tools/pack_unity.py --limit 8 --tex-limit 40 --out <临时目录>   # 冒烟

# Unity 侧（批处理，不用手点）：
"<Unity>/Editor/Unity.exe" -batchmode -nographics -quit \
  -projectPath remaster/unity_project \
  -executeMethod Lasr.ImportSelfTest.Run -logFile <日志>
# 交互：菜单 Tools ▸ LASR ▸ 重导全部模型 / 导入自检（资产）
```
