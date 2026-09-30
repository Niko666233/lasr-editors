# 格式速查（纯规格，证据见 00_FINDINGS.md）

## FLZD — 自研压缩容器 ✅ 完全破解

```
struct FlzdHeader {          // 13 字节
    char magic[4];           // "FLZD"
    u32  payload_plus_4;     // = payloadSize + 4 = fileSize - 9
    u32  uncompressed_size;
    u8   level;              // 9..13，其余拒绝
};                           // payload 从 offset 13 开始，到 EOF
```

解码：`flzd_decode(src=payload, srcLen, dst, dstCap=uncompressed_size, level)`
算法：Huffman + 二叉树匹配器 + 符号→字符串字典链（**非** LZW/zlib/LZMA/FastLZ）

实现：**不重写算法**，用 Unicorn 执行 `LASR.exe!0x1AC0`（见 `tools/lasr_flzd.py`）

---

## TUFA v4 — 自研类/资源定义容器 ✅ 容器已解，opcode 待破

```
struct TufaHeader {          // 12 字节
    char magic[4];           // "TUFA"
    u32  version;            // 4
    u32  signature;          // 0x0001451E （所有类相同）
};
// 之后是分块序列，直到 EOF
struct Chunk {
    char tag[4];             // "CONS" | "FILD" | "MTHD" | "CLSS" | "TREE"
    u32  size;               // 数据字节数
    u8   data[size];         // size 之后紧跟下一块（无对齐）
};
```

| tag | 作用 | 状态 |
|---|---|---|
| `CONS` | 常量池。首 u32 = 条目数 | 字符串可读，字段布局待定 |
| `FILD` | 字段表 = `u32 n` + `n × (u32 size, size bytes)`；每条 8 字节 = `<u32 CONS 索引><u32 类型>` | 部分 |
| `MTHD` | 方法表，一串小整数 | 待定 |
| `CLSS` | 类头，24 字节定长 | 部分 |
| `TREE` | **每方法一段代码** = `u32 n` + `n × (u32 size, size bytes)` | ✅ 2224/2224 类精确闭合 |

### TREE 载荷（已实测，见 `02_VM_INTERNALS.md`）

```
u32 count
count × ( u32 size ; size bytes )     // 每个 blob = 一个方法体
```

blob 内是帧序列 `<u8 opcode> [u32 operand]`，**`0x16` = 终止符**
（14869/14879 条记录以之结尾 = 99.93%）。已知操作数宽度：

| opcode | 操作数字节 |
|---|---|
| `0x03` | 0 |
| `0x16` | 0（终止符） |
| `0x05` `0x0b` `0x11` `0x14` `0x20` `0x21` | 4 |

帧序列构成**语法树**（1 个叶类型 `0x0C` + 36 个容器类型），不是栈式字节码。

操作码名字表（从 `LASR.exe` .rdata 挖出，原文）：
`EXCLAMATION ANDAND SHORTCUT_OR SHORTCUT_AND DUP_X2 DUP_X1 DELETE ARRAY_ACCESS
EMPTYDIMS ARRAY_INIT ARRAY_STORE NEWARRAY PUTFIELD_QUICK PUTFIELD_STATIC
PUTFIELD_INSTANCE JMP_EQ2 JMP_EQ JMP_NE RETURN FIELD_REF_QUICK FIELD_REF_STATIC
FIELD_REF_INSTANCE INVOKESTATIC INVOKESPECIAL INVOKE LOCAL_CLEARN LOCAL_CLEAR
LOCAL_STORE LOCAL_CREATE LOCAL_LOAD "RID LITERAL"(原文笔误=INT LITERAL) STRING
LITERAL CHAR LITERAL FLOAT LITERAL INT LITERAL BOOL LITERAL NULL LITERAL
INSTANCEOF CAST N/A`

`out_class_inventory.md`（仓库根，由 `tools/inventory.py` 生成）列出全部 2224 个类。

---

## RPAK — 资源包 ✅ 已解（可解包）

```
struct RpakFile {
    char magic[4];           // "RPAK"
    u32  index_size;         // 0x200 = 512 （所有发行版一致）
    u8   index[index_size];  // 512 字节索引：u32 子包数 + 长度前缀名表
                             //  ("system.rpk", "maps", "global_cubemap", ...)
    // 之后是资源链，**连续无缝**：
    Resource res[];
};
struct Resource {
    char tag[4];             // 4 字节 ASCII 标签
    u32  size;
    u8   data[size];
};
```

**已确认标签**（带载荷内部 magic 交叉验证）：

| tag | 载荷 | 数量示例 |
|---|---|---|
| `ISCX` | 以 `INVO` 开头 → 网格 | 每辆车 61 个 |
| `IDDS` | 完整 DDS 文件（`DDS ` magic，**全部 DXT5**）| 每辆车 95 个 |
| `m_ic` | 嵌套容器块（例 7.5 MB） | 少 |
| `RPAK` | 归档头本身 | 1 |

**验证**：`Hornet_Wega_2006.rpk` → 156 个资源、**99.95% 字节覆盖**、1 处间隙（索引区）。
`drivers/*.rpk` → 各 1 网格 + 1 贴图。

解包器：`tools/rpak_extract.py OUTDIR --all`
输出：`extracted_rpak/<archive>/NNNN_<tag>.dds|.iscx`

**体积**：`maps/*.rpk` 235 MB、`vehicles/*.rpk` 81 MB、`frontend.rpk` 32 MB。

---

## INVO v4 — 网格 ⏳ 头部已解，顶点流待定

```
0000 "INVO"
0004 u32 4              // version = 4
0008 u32 4              // (常量)
000C u32 0
0010 u32 44   u32 1     // 子流目录：<u32 相对偏移><u32 计数> 对
0018 u32 196  u32 4
0020 u32 208  u32 5
0028 u32 584  u32 0
0030 u32 152  u32 57
0038 ...
003F u8  len            // 长度前缀名字，例 len=8 → "interior"
0040 "interior"
```

实测样本：`vehicles/Hornet_Wega_2006` 第 95 号 `ISCX`（620 B，名字 `interior`）。
5 条子流；偏移 `44/196/208/584/152`、计数 `1/4/5/0/57`。

网格体数据可见 float32 三元组与 `ff ff ff ff`（= -1.0f）分隔符，
以及 `0c 0c 0c ff` 形式的 RGBA 材质色。

加载器报错串：`"Invalid mesh version! -> %s"`（用于定位解析器）。

实例：`.scx`/`.SCX` 独立文件 11 个；RPAK 内嵌 200+ 个。

---

## 明文格式（可直接使用）✅

| 文件 | 格式 |
|---|---|
| `*.bon` | 文本骨骼层级 |
| `*.scm` | 文本材质表：`materials N` / `material <i> <name>` / `type <n>` / `<texname> <rgba> <params>` |
| `*.spl2` | 制表符分隔浮点路径点（赛道/AI 样条）|
| `*.gtmp` | 文本 GUI Editor 模板 |
| `formats.als` | 文本 UI 字体/颜色样式 |
| `locale/LASR.*` | UTF-8(BOM) 多语言文本 |
| `*.cp`? / `font/*.bfnt` | 位图字体，待查 |

## 待解格式

| 文件 | magic | 猜测 |
|---|---|---|
| `*.matrixdata` | `19 00 00 00` | 骨骼动画矩阵关键帧 |
| `*.shz` | `01 00 00 00` | `shadowz` 静态光影遮罩 |
| `*.ptx` | `00 00 00 00` | 点云 |
| `routes/*.tga` | `00 00 02 00` | 非标准 TGA |
| `*.fmv` | `84 10 FF FF` | 自研视频 |
| `*.fev`/`*.fsb` | `FEV1` / `FSB*` | FMOD（用官方 SDK 解）|
