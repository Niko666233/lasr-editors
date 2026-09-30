# 18 · 原生 API 全表（VM ⇄ 引擎）

> P5 第二块。**LASR.exe 自带一份完整的 native 方法清单**——只要认出注册模式，
> 一个脚本就能把「Java 能调引擎的哪些函数、参数是什么」全部导出。

## 1. 注册模式

```asm
mov  ecx, [0x771154]          ; JavaMachine 实例
push 0x483400                 ; ① 原生函数地址（.text 内）
push 0x6e960c                 ; ② Java 方法签名串，例 '(IF)V'
push 0x6ee3f0                 ; ③ 方法名，例 'setPacejka'
push 0x6ee0b4                 ; ④ 点分 Java 类名，例 'java.game.parts.WheelRef'
call 0x652910                 ; registerNative(vm, class, name, sig, fn)
```

四参数都是紧邻的 `push imm32`（`0x68`），**从 call 往前按 5 字节步进取 4 个**即可
稳定解析（**不要**从任意地址开始反汇编——不保证指令边界，会得到垃圾串）。

工具：`tools/native_methods.py`
产出：**`out_native_methods.csv` / `.json` —— 1,523 个 native 方法 / 94 个类 /
签名 100% 可解**。

```bash
python tools/native_methods.py --dump
python tools/native_methods.py --class java.game.parts.Chassis
python tools/native_methods.py --grep pacejka
```

**独立复核（全量，非抽样）**：1,523 条记录中

| 判据 | 结果 |
|---|---|
| call 前四连 `push imm32`（`0x68`）模式成立 | **1,523 / 1,523** |
| `fn` 地址落在 `.text` 段内 | **1.0000** |
| 签名形如 `(…)X`（以 `(` 开头且含 `)`） | **1.0000** |
| 类名以 `java.` 开头且为点分名 | **1.0000** |
| 重载映射到相邻但不同的函数地址（`setPacejka` 三版 → `0x483400/0x483460/0x4834e0`） | ✓ |

（第一次跑出的是**移位**结果：我把倒序收集的列表又 `reverse()` 了一次，
`name` 列里落进签名 —— 四个字段全都偏一格但**看起来仍然合理**，
所以这类批量提取必须做一次上面这种语义自检，否则会静默错。）

## 2. 规模

| 类 | native 方法数 | 说明 |
|---|---|---|
| `java.gui.Component` | 168 | **整个 UI 是原生实现**（Java 只是壳） |
| `java.gui.Frame` | 152 | 窗口/控件框架 |
| `java.gui.Gauge` | 100 | 仪表盘 |
| `java.game.parts.Chassis` | **66** | **车辆物理核心** |
| `java.game.parts.WheelRef` | **44** | **轮胎/悬挂/关节** |
| `java.util.resource.GameRef` | 43 | 资源系统 |
| `java.game.parts.Part` | 41 | 部件（槽位/磨损/贴花） |
| `java.gui.TabList` / `HSlider` / `Background` … | 19–42 | UI 其余 |
| `java.util.resource.GroundRef` | 31 | 地面/赛道引用 |
| `java.game.Replay` | 24 | 回放 |
| `java.io.Input` | 14 | 输入 |

> **修正一个旧印象**：`java.gui.*` 占了大半——游戏的 UI **不是** Java 画的，
> 而是一堆 native 控件类，Java 侧只做布局与逻辑。重制时要还原的是**布局数据**，
> 不是 GUI 绘制代码。

## 3. `java.game.parts.Chassis`（66）—— 手感全在这里

```text
配置   createTypeBegin()V  configureType(String)V  configureVisual(...)V  createTypeEnd()V
传动   setGearRatios([FFF)V  setTransmissionTimes(FFFFFF)V  setAckermann(F)V
       setSteerWheel(FF)V  setSteerWheelRadius(F)V  setEngineInertia(F)F
       setDrivetrainInertia(F)F  setEngineLoss(F[F)V  setRevLimit(FFFFF)V
       setTurboParams([FI)V  setExhaustParams(FF)V  setNitro(FF)V
       setTorque(F)V  setCooling(FFF)V  setDirtType(I)V  setBuck(IIFFFF)I
质量   getMass()F  getCM()Vector3  getMin/getMax()Vector3
状态   getRPM()F  getSpeed()F  getLateralG()F  getLongitudinalG()F  getGear()I
       getTurboPressure()F  getN2OTankLevel()F  getSalaTemp(I)F
       getRevLimiterState()I  getRealSteeringAngle()F  getNitroState()I  getMileage()F
车轮   getWheels()I  getWheelInfo(I)WheelRef  getWheelPos(I)Vector3
       getWheelLoad/getWheelY/getWheelSlip/getWheelSlipR/getWheelBeta
       getWheelRollingR/getWheelAngVel/getWheelCamber (I)F
       getWheelPac(II)F  getWheelMaterial(I)I  getWheelDamage(I)String  setWheelDamage(I,String)V
差速   getDifferential(I)CarDifferential  getDiffLock(I)F  getDiffInput(I)F
其它   getFFBactvalues()[F  setSlipLogMode(I)V  getInfoBlock()[F
       setHornSFX(ResourceRef,FI)V  setNitroSFX(ResourceRef,F)V  getSfxTable(I)SfxTable
       forceUpdate()V  preCache()V
```

## 4. `java.game.parts.WheelRef`（44）—— 轮胎与悬挂

```text
位置   getPos()Vector3  setPos(Vector3)  getYpr()Ypr  setYpr(Ypr)
几何   getRadius()F  setRadius(F)  setWidth(F)  setArm(FFFFFFF)  setHub(FFFFFFFFFF)
       setInstantCenter(FFFFFF)  setOppWheel(I)
轮胎   setPacejka(IF)V   setPacejka(IIF)V   setPacejka(I[I[F)V   setPacTable([I)V
       setCPatch(FFFF)V  setFrictn_x(F)  setSliction(F)  setStiffness(F)
       setRollRes(F)  setBearing(F)  setTyre(I)  setTyre(FFF)  setMaxLoad(F)  setLoadSmooth(F)
悬挂   setForce(F)  setMass(F)  setDamping(F)  setDamping(FF)  setInertia(F)F
       setRestLen(F)  setMinLen(F)  setMaxLen(F)
驱动   setDrive(F)  getDrive()F  setSteer(F)  getSteer()F
制动   setBrake(F)  getBrake()F  setEBD(FFF)V  setHBrake(F)  getHBrake()F
其它   getBone(I)ResourceRef  getDamage()F
```

**`setPacejka(I[I[F)V`**（下标数组 + 值数组）对应 Java 侧看到的
`local2.setPacejka(local3, PacejkaGlobals.common_pacVarIdxs, PacejkaGlobals.common_pacVars)`
——重制时逐条实现这 3 个重载就能还原轮胎模型。

## 5. `java.game.parts.Part`（41）—— 部件

```text
配置   createTypeBegin()V  configureType(String)V  configureMesh(ResourceRef[,I[,I]])V
       configureTexture(ResourceRef)V  configureVisual(...)V  createTypeEnd()V
槽位   getSlots()I  getSlotID(I)I  getSlotIndex(I)I  slotIDOnSlot(I)I
       getSlotDamage(I)String  setSlotDamage(I,String)V  setSlotPos(I,Vector3,Ypr)V
       getSlotPos(I)Vector3  getSlotBoneID(I)I  disableSlot(II)V  isSlotDisabled(I)I
外观   getMesh/setMesh(I)I  getTexture/setTexture(I)I  renderType  getLogo()I
       setDirt(FI)  getDirt()F  applyDecal(ResourceRef,PartDecal)V  flap(I)I
状态   getWear/setWear/setMaxWear  getTear/setTear  getMass()F  getVehicle()Vehicle
声音   setSfxLoopParams(FF)I
```

## 6. 重制时的用法

1. **参数值** → Java 侧（`out_pseudo/`，已 100% 结构化）+ `out_config*.json`（9,849 行配置）；
2. **参数语义与结构布局** → 本表 + `docs/17_PHYSICS_BINDING.md`（属性表 + 字段偏移）；
3. **运行时行为** → 直接用本表的函数地址反汇编（`0x483f50` = `getTorque(FF)F` 等），
   逐个函数就能把数值公式挖干净——**不需要再猜任何入口**。

> 这条把 P5 从「需要大海捞针」变成了「按清单逐个函数读公式」。
