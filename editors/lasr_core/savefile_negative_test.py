# 反例测试：构造可疑存档字典，确认 validate() 真的会报出警告。
import sys
sys.path.insert(0, ".")
from editors.lasr_core import savefile as sf

# 1) 真实存档：应无警告
real = sf.load("C:/Games/LASR/save/career/001.sav")
print("真实存档 validate():", sf.validate(real) or "（无警告）")

# 2) 人为构造可疑值
s = sf.load("001_workcopy.sav")
s["lastVehicle"] = 99
s["cars"] = [
    {"vehicle": 0x20000009 | 0, "parts": []},                     # ok 车
    {"vehicle": 0x40000001, "parts": []},                          # type 位错
    {"vehicle": 0x20000000 | (30 << 16), "parts": []},             # 索引越界
    {"vehicle": sf.make_vehicle_id(5),
     "parts": [[sf.make_part_id(3, 7), 1], [sf.make_part_id(5, 2), 5]]},  # 一个 vidx 不符 + status 非法
]
s["winSum"] = 10
s["raceSum"] = 3
s["prestige"] = 0xFFFFFFFF
s["prestigeValues"][0] = 0x80000000
s["driverType"] = 9
s["pubIndex"] = 0
s["trialProgress"] = 99
s["trials"][0] = 2
s["aiLevelMul"] = -1.0
s["chronicles"][0]["bestLapTime"] = float("nan")
warns = sf.validate(s)
print("\n反例 validate() 共 %d 条警告:" % len(warns))
for w in warns:
    print("   [!]", w)

# 3) 零件 id 拆分/拼接自洽
for idx in (0, 1, 9, 22):
    for case in (0, 1, 65535):
        i = sf.make_part_id(idx, case)
        assert sf.split_id(i) == (1, idx, case), (idx, case, sf.split_id(i))
print("\n零件 id 拼接/拆解自洽性: OK (0..22 索引 x {0,1,65535} case)")

# 4) 合成一个带零件的存档并往返
syn = sf.load("001_workcopy.sav")
syn["cars"] = [{"vehicle": sf.make_vehicle_id(3),
                "parts": [[sf.make_part_id(3, 100), 1], [sf.make_part_id(3, 250), 0]]}]
blob = sf.build(syn)
back = sf.loads(blob)
print("\n合成存档(带 2 零件): 重建 %d 字节, 车 %d 台, 零件 id 0x%08x/0x%08x"
      % (len(blob), len(back["cars"]),
         back["cars"][0]["parts"][0][0], back["cars"][0]["parts"][1][0]))
print("二次往返逐字节一致:", sf.build(back) == blob)
