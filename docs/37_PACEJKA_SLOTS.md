# 37 · Pacejka 36 槽语义标定（原生 setter 路线）

> `docs/20` §2 留了一句「具体语义待逐个确认」。本文用**原生标量 setter 的写入偏移**
> 把其中 7 个槽标定了出来，并且**与 Java 的 `pacVarIdxs` 索引表交叉验证**。
> 方法可复制 —— 剩余槽位照同一路子继续。

## 1. 方法（可复用）

`out_native_methods.csv` 里 `WheelRef` 类有**一整排标量 setter**，每个只写一个字段：

```
setFrictn_x(F)  setStiction(F)  setStiffness(F)  setBearing(F)
setMaxLoad(F)   setLoadSmooth(F)  setCPatch(FFFF)  setRollRes(F)
setDrive(F) setSteer(F) setWidth(F) setRadius(F) ...
```

反汇编任意一个，形状完全一致：

```asm
mov  edx, [esp+4]          ; Java 参数
lea  eax, [esp+4] / lea ecx, [esp+4]
push eax / push ecx / push edx
call 0x652ab0              ; ★ 参数解包（Java float → C++ float）
mov  eax, [0x8dcb2c]       ; ★ 一个全局
mov  ecx, [esp+0xc]
call 0x643bf0              ; ★★ 「由 wheel 取 tyre 对象」，返回值在 eax
movss xmm0, [esp+4]
movss [eax + 偏移], xmm0   ; ★★★ 写入偏移 ⇒ 槽号 = (偏移 − 0x20C) / 4
ret
```

★ 关键锚点（本轮新得）：
- **`0x652ab0`** = 参数解包（每个 `WheelRef` setter 都先调它）
- **`0x643bf0`** = 「wheel → tyre 对象」的取值函数
- **`0x8dcb2c`** = 解包路径上被读的全局
- **Pacejka 数组基址 `+0x20C`，36 个 f32 槽**（`docs/20` §1）

## 2. ★ 已标定的槽（每条都有两条独立判据）

| 槽 | 语义 | 判据 A：C++ setter 的写入偏移 | 判据 B：是否出现在 `pacVarIdxs_v3` |
|---|---|---|---|
| **0** | **stiction**（静摩擦） | `setStiction` → `+0x20C`（=基址+0） | ✓ 在表内 |
| **2** | **µ / 地面抓地缩放** | 由数据差值独立推出（`docs/35` §4：9 个配方只有此项随路面变化；越野胎 5 项） | ✓ **表首项** |
| **4** | **stiffness**（刚度） | `setStiffness` → `+0x21C`（=基址+4） | ✓ 在表内 |
| **11** | **maxLoad**（最大载荷） | `setMaxLoad` → `+0x238`（=基址+11） | ✓ 在表内 |
| **12** | **frictn_x**（纵向摩擦） | `setFrictn_x` → `+0x23C`（=基址+12） | ✓ 在表内 |
| **13** | **bearing**（轴承/迟滞，**推断**） | `setBearing` 的存储语句落在 `setFrictn_x`(12) 与 `setLoadSmooth`(14) 之间（反汇编窗口被截断，未直接读到偏移 ✗） | ✓ 在表内 |
| **14** | **loadSmooth**（载荷平滑） | `setLoadSmooth` → `+0x244`（=基址+14） | ✓ 在表内 |

★★ **闭环的意义**：这 7 个槽号在 `pacVarIdxs_v3` 里出现的**顺序与位置完全吻合**
```
pacVarIdxs_v3 = { 2, 12, 0, 4, 13, 11, 14, 3, 17, 10, 1, 6, 7, 8, 18, 19, 15, 16, 34, 35 }
                   ↑   ↑  ↑  ↑   ↑   ↑   ↑
                  µ  fx  st 刚 轴 载 平
```
⇒ **写入偏移路线与 Java 索引表路线互相验证**（两条独立证据链给同一结论）。
`common_pacVarIdxs = {15,16,26,24,25,22,23}` 的 7 项则**不在**这两个集合里 —— 属另一组
「全轮胎共享量」（`docs/20` 推测为参考载荷/温度一类，仍待确认 ✗）。

## 3. 本轮白捡的两条结论

- ★ **`setRollRes` 是空实现** —— `0x4da7a0` 处只有一条 `ret`。⇒ **原版没有实现滚动阻力**。
  重制时若加上，手感会与原版不同。
- ★ **`setPacejka` 三个重载的签名含义**（来自原生方法表，比 `docs/20` 更明确）：
  | 签名 | 含义 |
  |---|---|
  | `(IF)V` | 单值：`setPacejka(int varIdx, float val)` |
  | `(IIF)V` | `setPacejka(int tyreIdx, int varIdx, float val)` |
  | `(I[I[F)V` | **批量**：`setPacejka(int tyreIdx, int[] varIdxs, float[] vars)` ← Java 侧走这个（`PacVals.setpacVals`） |

## 4. 剩余待标定的槽

`pacVarIdxs_v3` 里尚未命名的：**3, 17, 10, 1, 6, 7, 8, 18, 19, 15, 16, 34, 35**
（槽 18 已知「写入时 ×1e-4」= 有单位换算，`docs/20` §1）。

继续标定的两条路：
1. **仍走 setter 路线**：把 `WheelRef` 剩下那些 setter（`setCPatch(FFFF)`、`setTyre(FFF)`、
   `setArm(FFFFFFF)`、`setHub(FFFFFFFFFF)`、`setInstantCenter(FFFFFF)`、`setEBD(FFF)`、
   `setDamping(FF)`、`setInertia(F)F`）逐个反汇编完（本轮有的窗口被截断）。
2. **走力公式路线**：反汇编轮胎力计算函数，看每个槽参与哪个式子
   （`F = D·sin(C·atan(B·φ − E·(B·φ − atan(B·φ))))` 的 B/C/D/E 及其载荷/胎压修正项）。
   这条路能一次性给出**公式级**的语义，但需要先定位力计算函数（尚未定位 ✗）。

## 5. 本轮新增锚点与「已排除」的路径（下轮别再走）

### 5.1 新锚点

| 地址/偏移 | 含义 | 依据 |
|---|---|---|
| **`+0x140C`** | ★ `setPacTable([I)` 写入的目标（`add edi, 0x140C` @ `0x48362F`），一个 **int[]** 表，由计数循环 `xor esi,esi / test ebx,ebx / jle` 逐项拷入 | `0x4835e0` 反汇编 |
| `0x652ab0` | 参数解包（Java float → C++），每个 `WheelRef` setter 首调 | 11 个 setter 一致 |
| `0x643bf0` | 「wheel → tyre 对象」，返回值在 `eax`（可带第 2 参数取别的对象，见 `setPacTable` 里连续两次调用） | 同上 |
| `0x8dcb2c` / `0x8dcb30` | 解包路径上被读的两个全局 | 同上 |

### 5.2 已排除（省下重复劳动）

- ✗ **`0x20C` 作为指令位移的读取端不存在**：全 `.text` 里 `0C 02 00 00` 只有 6 处
  （`0x48200f`、`0x483278`、`0x483452`、`0x4834ce`、`0x4835c5`、`0x48532d`），
  逐一对齐后**全是写入端或指令字节巧合**（`0x48200f` 实为 `or al,2` 的立即数）。
- ✗ **`lea reg,[reg+0x20C]` 模式不存在**（按 `8D` + disp32 modrm 扫全 `.text`，0 命中）。
  ⇒ 力计算代码**不是**用 `0x20C` 位移直接寻址系数的，必然经由**缓存指针**或
  `+0x140C` 那套表。（★ **已解决**：见 `docs/38_PACEJKA_DATA_LAYOUT.md` ——
  `+0x140C` 是 32 项 int[] 索引表，紧邻一个 `32 × 144 字节` 的系数装载循环。）
- ✗ **`WheelRef` 其余 setter 不写 Pacejka 槽**（逐个反汇编结果）：
  `setEBD(FFF)` → `+0xC4/+0xC8/+0xCC`；`setDamping(FF)` → `+0x3C/+0x40`；
  `setInertia(F)F` → `+0x60`；`setArm` → `+0x64`；`setCPatch(FFFF)` → `+0x24`。
  ⇒ 只有 `setStiction`/`setStiffness`/`setMaxLoad`/`setFrictn_x`/`setLoadSmooth`
  这 5 个写系数数组（槽 0/4/11/12/14），setter 路线**到此为止**。
- ✗ `setBearing`（槽 13）的存储语句仍未直接读到：它在 `0x48330e` 调了 `0x5668d0`
  （与 `'inconsistent Pacejka array sizes!'` 同一打印/断言助手），随后 `movss` 写的是
  `[esi+…]` 而 `esi` 来自 `mov esi,eax`（`0x643bf0` 的返回），**按 `[eax+…]` 的模式 grep
  会漏掉它** —— 重查时请改用 `esi`。
