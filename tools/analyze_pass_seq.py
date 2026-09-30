"""把赛道内实时采集的渲染目标切换记录，还原成"每帧通道序列 + 发起函数"。

输入：out_tracer.jsonl（tools/attach_trace.py 产出）
每条记录：{t, kind, slot, ret, tid, esp}
  kind = Present / SetRenderTarget / SetDepthStencilSurface
  ret  = 调用者的返回地址（D3D 方法入口处 [esp]，本次修复后有效）

输出：
  1. 总览与配对性
  2. 前几帧的完整序列（谁在切换）
  3. 每个调用者的命中次数（= 哪个引擎函数负责切 RT）
  4. 是否出现"非 10 次"的异常帧

用法: python tools/analyze_pass_seq.py [out_tracer.jsonl]
"""
import collections
import json
import sys


def load(path):
    recs = []
    for line in open(path, encoding="utf-8", errors="replace"):
        line = line.strip()
        if not line:
            continue
        try:
            recs.append(json.loads(line))
        except Exception:
            continue
    return recs


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "out_tracer.jsonl"
    recs = load(path)
    kinds = collections.Counter(r.get("kind") for r in recs)
    print(f"总记录 {len(recs)}")
    for k, v in kinds.most_common():
        print(f"  {k}: {v}")

    # 按帧切分：Present 为帧边界
    frames, cur = [], []
    for r in recs:
        k = r.get("kind")
        if k == "Present":
            frames.append(cur)
            cur = []
        elif k in ("SetRenderTarget", "SetDepthStencilSurface"):
            cur.append(r)
    print(f"\n完整帧数（有帧尾的）: {len(frames)}")

    # 每帧的事件数分布
    dist = collections.Counter(len(f) for f in frames)
    print("每帧 RT/SDS 事件数分布:", dict(sorted(dist.items())[:8]))

    # 配对性：RT 后是否紧跟 SDS
    bad_pair = 0
    for f in frames:
        for i in range(0, len(f) - 1, 2):
            a, b = f[i], f[i + 1]
            if not (a["kind"] == "SetRenderTarget" and b["kind"] == "SetDepthStencilSurface"):
                bad_pair += 1
    print(f"RT→SDS 配对异常次数: {bad_pair}")

    # 前 3 帧的完整序列
    print("\n=== 前 3 帧的通道序列（每行 = 一次 RT 切换）===")
    for fi, f in enumerate(frames[:3]):
        print(f"--- 帧 {fi}：{len(f)} 个事件 ---")
        for r in f[:24]:
            print(f"   t={r.get('t'):>7} {r.get('kind'):<22} ← 调用者 {r.get('ret')}")
        if len(f) > 24:
            print(f"   …… 还有 {len(f) - 24} 条")

    # 每个调用者的次数（谁是通道切换的发起者）
    print("\n=== 调用者统计（谁在切换渲染目标）===")
    per_caller = collections.Counter()
    for f in frames:
        for r in f:
            per_caller[(r.get("kind"), r.get("ret"))] += 1
    for (k, ret), v in per_caller.most_common(12):
        print(f"  {k:<22} ← {ret}   x{v}")

    # 调用者模式：每帧的调用者序列是否固定
    print("\n=== 每帧「调用者序列」的重复情况 ===")
    pat = collections.Counter(tuple(r.get("ret") for r in f) for f in frames)
    for p, v in pat.most_common(3):
        print(f"  出现 {v} 帧: " + " → ".join(str(x) for x in p[:12])
              + (" …" if len(p) > 12 else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
