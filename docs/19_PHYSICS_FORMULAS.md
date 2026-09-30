# 19 · 物理函数内部（P5 第三块）

> 有了 `docs/18_NATIVE_API.md` 的函数清单之后，这一块就是「按地址读公式」。
> 工具：`tools/native_fn.py`（带浮点常量解码、native 调用名标注、字段路径数据流）。

## 1. 先解决"读不懂"的问题

MSVC x86 的浮点代码裸看没有意义，所以工具做了三件事：

| 现象 | 工具处理 |
|---|---|
| `push 0x3c23d70a` | 注释成 `float 0.01` |
| `movss xmm0, [0x6e7df0]` | 读出该地址的 4 字节并注释成 `= 0.0174533` |
| `call 0x483f50` | 查 `out_native_methods.json` 注释成 `-> Chassis.getTorque(FF)F` |
| `movss [ecx+0xf8], xmm0` | 追 `mov/lea reg,[parent+off]` 链，输出 `[this]+0x24d4+0xf8` |

```bash
python tools/native_fn.py --fn 0x44e4b0            # 反汇编 + 注释
python tools/native_fn.py --summary 0x483f50 ...   # 批量：常量/字段/被调者
python tools/native_fn.py --props                  # 全部属性 handler 的字段写入
```

**踩到的坑**（都修了）：把**未加方括号**的操作数当成内存读取 → 浮点常量列全是
`-136.7676239` 这种垃圾（那其实是代码地址）；`dword ptr [ecx + 0xf8]` 这种两词前缀
让 `^\S*\s*\[` 正则匹配失败 → 写入表整片为空。

## 2. 曲线机制（引擎扭矩曲线）—— 全套已确认

`Chassis.getTorque(FF)F` 是薄包装，真身在 **`0x44e4b0`**：

```asm
mov  esi, [edi + 0x24d4]          ; ★ 引擎子对象
mov  eax, [esi + 4]               ; ★ 点数组基址
mov  ecx, [esi]                   ; ★ 点数量
comiss xmm5, [eax + ecx*8 - 8]    ; 与最后一个点比较（越界分支）
lea  ecx, [esi + 0x108]           ; ★ 多项式系数数组
call 0x44e040                     ; → Horner 求值
call 0x44e0c0                     ; → 点表查值（越界时用）
```

### 2.1 结构

```
struct Curve {
    u32   count;        // +0x00
    struct Pt { f32 x, y; }* pts;   // +0x04  ← pts[i] = 8 字节
    ...
    f32   coef[?];      // +0x108 ← 多项式系数（Horner 用）
};
```

`0x44e0c0`（**点表查值**）是这条结构的独立旁证 —— 它按 `[ecx + eax*8]` 取 x、
`[ecx + eax*8 + 4]` 取 y：

```asm
if (x < pts[0].x)       return pts[0].y;            // 低端钳位
if (x >= pts[n-1].x)    return pts[n-1].y;          // 高端钳位
二分/线性找 i 使 pts[i].x <= x < pts[i+1].x
若找不到              return [0x733b0c];           // 全局缺省值
否则在 pts[i-1] 与 pts[i] 之间线性插值
```

⇒ 引擎用的是「**点表 + 线性插值 + 两端钳位**」；`0x733b0c` 是全局缺省浮点
（同一个全局在 `setEngineInertia` 里也被当作可调限值比较，说明它可被配置/调试命令修改）。

### 2.2 多项式求值 `0x44e040` = Horner

```asm
xmm1 = 0
loop:  xmm1 = xmm1 * x + c[i]      // ((c0·x + c1)·x + c2)·x + …
```

按 4 项展开、从**高次往低次**取系数 ⇒ 引擎对曲线还做一层多项式平滑/外推，
系数在 `curve + 0x108`。**重制若只做点表插值，会在曲线拐点处与原生手感产生偏差** ——
要完全复刻就得连这层多项式一起实现。

### 2.3 另一条具体公式（`Chassis.setTorque(F)V` → `0x44e6d0`）

```asm
if (arg >= 1.0)  return 0.1;
else             return 1.0 - arg*arg*0.6;      // f(x) = 1 - 0.6x²
```

常量出处：`0x6e766c = 1.0`、`0x6ec554 = 0.6`、`0x6ed44c = 0.1`（均在 `.rdata` 浮点池）。

### 2.4 扭矩公式的乘法链

```asm
movss xmm2, [edi + 0x23c0]
mulss xmm2, [edi + 0x2298]
mulss xmm2, xmm0          ; xmm0 = 曲线求值结果
```

⇒ `torque = curve(rpm) × [engine+0x23c0] × [engine+0x2298]`（两个系数槽）。

### 2.5 顺手拿到的 `.rdata` 缺省值池（属性 handler 用）

| 地址 | 值 |
|---|---|
| `0x6e7668` | `-1` |
| `0x6e766c` | `1` |
| `0x6e7664` | `10` |
| `0x6e7650 / 0x6e7680 / 0x6e7688 / 0x6e768c` | `0.05` |
| `0x6ec554` | `0.6` |
| `0x6ed44c` | `0.1` |
| `0x6ea6d4` | `0.5` |

这些就是「属性未配置时的缺省」的来源。

## 3. setter 的通用模板（所有属性都是这个形状）

以 `setEngineInertia(F)F` @0x485c30 为例（45 条指令）：

```asm
mov  edx, [esp + 0xc]        ; 参数
lea  eax, [esp] / push ...   ; 准备取返回值的槽
call 0x652ab0                ; VM：取浮点实参
mov  eax, [0x8dcb2c]         ; VM 环境
push eax / push edx / call 0x643bf0   ; → eax = 接收者包装
mov  esi, [eax + 8]          ; ★ 原生对象 = this
push 1 / push 0xa0000000 / mov ecx, esi / call 0x55a230
                             ; VM：检查挂起异常（返回值 < 0 即异常）
mov  edx, [esi + 0x24]       ; VM 类偏移表索引
mov  eax, [edx*4 + 0x7439b0] ; ★ 每类字段基址表
add  eax, esi
mov  eax, [eax + 0x64]       ; ★ 车物理对象
movss xmm0, [esp+4]
comiss xmm0, [0x733b0c]      ; ★ 与一个「运行时可调」全局阈值比较
jbe  skip
mov  ecx, [eax + 0x24d4]     ; ★ 引擎子对象
movss [ecx + 0xf8], xmm0     ; ★ 写入 engine+0xf8
```

价值不在这一条，而在于**每个属性都由同一模板生成** ⇒ 可以用数据流机械抽取
（`--props` 模式），无需逐个手工读。

## 4. 属性 → 字段映射（`out_property_fields.csv`，92 项）

抽样（表中 `[eax]` 即"车物理对象"，`+0x4878` 是从 `entity` 到物理对象的固定偏移）：

| 属性 | 表 | 写入路径 |
|---|---|---|
| `enginepower` | table_1 | `+0x4878 + {0xe8, 0xec, 0xf8, 0x100, 0x108, 0x118}` |
| `maxsteer` | table_1 | `+0x4878 + 0xbd8`（转向组 `+0xbd4/+0xbd8/+0xbe4`） |
| `spring` | table_1 | `+0x40 + 0x0` |
| `friction` | table_2 | `+0x330`（= `pacdata` 同一槽） |
| `pacdata` | table_2 | `+0x330` |
| `osd_turbo` | table_1 | `+0x3c34`、`+0x18/0x1c/0x20` |
| `sfx_engine_up/down/exhaust` | table_1 | `+0x10/0x14/0x18/0x1c...`（声音槽组） |

`Chassis` 方法侧的独立佐证（`--summary` + `--fn`）：

| 方法 | 写入 | 与属性表一致？ |
|---|---|---|
| `setEngineInertia(F)F` @0x485c30 | `engine+0xf8` | ✓ 与 `enginepower` 的 `+0xf8` 同槽 |
| `setSteerWheelRadius(F)V` @0x486bf0 | `engine+0xbdc` | ✓ 落在转向组 |
| `setAckermann(F)V` @0x486c70 | `engine+0xbe4` | ✓ 转向组第三槽 |
| `setEngineLoss(F[F)V` @0x485d70 | 常量 `0.5` | — |
| `setBuck(IIFFFF)I` @0x488930 | 常量 `-1.0 / 1.0` | — |
| `getTorque(FF)F` @0x483f50 | 常量 `0.01 / 1.0`，调 `0x44e4b0` | — |

**覆盖率的诚实说明**：165 个唯一 handler 里 132 个有写入、92 个可归名。
剩下的分两类：**无字段的属性**（纯旗标，如 `wheelbones`）与
**通过共享辅助函数写字段的**（写入发生在被调者里，数据流跟踪不外传）。
逐条补全需要在几个共享 helper（`0x55a230` 一族）上做参数映射 —— 已列为后续工作。

## 5. 其它已确认细节

* `engine+0x24d4` 这个**引擎子对象**同时被 `getTorque`（读）与各 setter（写）使用 ⇒
  它就是重制时要复刻的「发动机对象」，字段至少含 `+0xf8`(惯量)、`+0xbdc`(方向盘半径)、
  `+0xbe4`(转向组)、`0x108..0x118`(查找表)、`+0x23c0/+0x2298`(扭矩倍率)。
* `[0x733b0c]` 等全局**在运行时被比较**的浮点，是"可调限值"（配置文件/调试命令能改），
  重制时可当作可调参数导出。
* `[0x7439b0]` = **每类字段基址表**（VM 用来把 Java 字段映射进原生对象），
  是解析任何 Java↔原生对象对应关系的钥匙。
