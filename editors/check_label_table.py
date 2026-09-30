"""独立复核 `data/literal_labels.json` 的可信度（不信任生成器的自述）。

对每个「类 + 方法」做两件事：
  1. **个数校验**：标签个数必须 == 该方法的字节码 INT/FLOAT 字面量个数；
  2. **值级校验**：标签里带的数字（不含 `#参数N`/`#下标` 那类结构标记里的数字）
     必须与同一序号的字节码字面量相符（容忍一元负号 / int↔float32 / 伪码 7 位有效数字）。

值只从字节码取，标签只用于**显示** —— 所以就算个别标签错了，也不会改错数据；
但仍要能说清「表有多可信」。

    cd editors && ../.capenv/Scripts/python.exe check_label_table.py [json] [车包个数]
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lasr_core import vdata  # noqa: E402

PLAIN_NUM = re.compile(r"^-?\d+\.?\d*$")


def num_of(label):
    """标签本身是不是一个纯数字（值）；结构标记不算。"""
    s = (label or "").strip()
    if not s or "#" in s:
        return None
    if PLAIN_NUM.match(s):
        return float(s)
    return None


def close(a, b):
    return abs(a - b) <= max(1e-3, abs(b) * 1e-5)


def main():
    here = Path(__file__).resolve().parent
    jp = Path(sys.argv[1]) if len(sys.argv) > 1 else here / "data" / "literal_labels.json"
    n_pack = int(sys.argv[2]) if len(sys.argv) > 2 else 4
    raw = json.loads(jp.read_text(encoding="utf-8"))
    g = vdata.find_game_dir()
    packs = sorted((p.parent.parent.name, p.parent.name, p)
                   for p in g.glob("vehicles/*/*/classes.zip"))[:n_pack]

    classes = checked = bad_cnt = bad_val = filled = total_lit = 0
    for car, body, zp in packs:
        ed = vdata.ZipPartEditor(g, zp)
        for e in ed.part_entries():
            cs = e.split("/")[-1][:-6]
            st = ed.load(e)
            classes += 1
            m = raw.get(cs)
            if not m:
                continue
            for meth in st.tufa.methods:
                lits = list(st.tufa.literals(meth))
                total_lit += len(lits)
                labs = m.get(meth.name)
                if not labs:
                    continue
                checked += 1
                if len(labs) != len(lits):
                    bad_cnt += 1
                    if bad_cnt <= 3:
                        print("  个数不符 %s.%s 标签%d 字面量%d"
                              % (cs, meth.name, len(labs), len(lits)))
                    continue
                for lab, (i, _o, _k, v) in zip(labs, lits):
                    if lab:
                        filled += 1
                    n = num_of(lab)
                    if n is None:
                        continue
                    if not close(n, float(v)):
                        bad_val += 1
                        if bad_val <= 5:
                            print("  值不符 %s.%s[%d] 标签=%r 字节码=%r"
                                  % (cs, meth.name, i, lab, v))

    print("表      : %s（%d 类有标签）" % (jp, len(raw)))
    print("抽查    : %d 车包 / %d 类 / %d 个有标签的方法" % (len(packs), classes, checked))
    print("个数不符: %d" % bad_cnt)
    print("值级不符: %d" % bad_val)
    print("结论    : %s" % ("表可用 ✓（显示用；值永远从字节码取）"
                          if bad_cnt == 0 and bad_val == 0 else "有问题 ✗"))
    return 0 if (bad_cnt == 0 and bad_val == 0) else 1


if __name__ == "__main__":
    raise SystemExit(main())
