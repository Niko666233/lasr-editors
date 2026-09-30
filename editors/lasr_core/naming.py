"""零件类名 → 人话（族名中文 + 阶段/式样中文）。

类名形如 `<Body>_<族>_<变体>`，例如 `Coupe_RS_IEngine_stage_IV`、
`Hatch_S2_F_Bumper_style_II`。族名与变体名来自 10 台车 1850 个类名的实测枚举
（见 editors/out_catalog_report.txt），中文译名按语义给，拿不准的保留英文。
"""

# 零件族 → 中文（原厂车身件、外观件、性能件）
FAMILY_CN = {
    # 车身外观（原厂件带 I 前缀的是「店内可换」件）
    "FL_Door": "前左车门", "FR_Door": "前右车门", "R_Door": "后车门",
    "F_Bumper": "前保险杠", "IF_Bumper": "前保险杠(店)", "R_Bumper": "后保险杠",
    "IR_Bumper": "后保险杠(店)", "Hood": "引擎盖", "IHood": "引擎盖(店)",
    "IF_Doors": "前车门(店)", "IR_Door": "后门(店)", "IR_Door_Wing": "后门+尾翼(店)",
    "Trunk": "后备箱盖", "ITrunk": "后备箱盖(店)", "ITrunkRWing": "后备箱+尾翼(店)",
    "L_sideskirt": "左侧裙", "R_sideskirt": "右侧裙", "R_wing": "尾翼",
    "IChassRWing": "底盘尾翼(店)", "Interior": "内饰", "IInterior": "内饰(店)",
    "SteeringWheel": "方向盘", "ISteeringWheel": "方向盘(店)",
    "Muffler": "排气", "IMuffler": "排气(店)",
    "ICTF_Lightbar": "警灯条",
    # 性能件（可调参数最多的就是这些）
    "IEngine": "引擎", "ITransmission": "变速箱", "IGearbox": "齿轮箱",
    "IDiffs": "差速器", "IRunningGear": "传动/悬挂总成", "INitrous": "氮气",
    "IWeightReduction": "减重件", "IRims": "轮圈", "ITyres": "轮胎",
    "Rim_F_ST": "前轮圈(前)", "Rim_R_ST": "后轮圈(后)", "Rim_U_ST": "轮圈",
    "Tyre_F_ST": "前轮胎(前)", "Tyre_R_ST": "后轮胎(后)", "Tyre_U_ST": "轮胎",
    "WeightReduction": "减重件(原厂)",
    # 其他
    "IPaintjob": "车漆", "ISticker": "贴纸",
}

# 变体 → 中文
VARIANT_CN = {
    "stock": "原厂", "custom": "定制", "custom1": "定制1", "custom2": "定制2",
    "custom3": "定制3", "track": "赛道", "drift": "漂移", "rally": "拉力",
    "WB": "宽体", "style_I": "外观I", "style_II": "外观II", "style_III": "外观III",
    "style_IV": "外观IV", "style_WB": "外观宽体",
    "stage_I": "一阶", "stage_II": "二阶", "stage_III": "三阶",
    "stage_IV": "四阶", "stage_V": "五阶", "stage_WB": "宽体阶",
    "0": "式样0", "1": "式样1", "2": "式样2", "3": "式样3", "4": "式样4",
}


def split_class(short):
    """`Coupe_RS_IEngine_stage_IV` -> ('Coupe_RS', 'IEngine', 'stage_IV')。

    族名判定：第一个以大写字母开头、且以 `I` 开头的 token 起，到变体前为止；
    找不到 `I` 前缀时就退化成「去掉车体前缀的剩余部分」。
    """
    parts = short.split("_")
    for i, p in enumerate(parts):
        if len(p) > 1 and p[0] == "I" and p[1].isupper():
            rest = parts[i:]
            for j, q in enumerate(rest):
                if q in VARIANT_CN:
                    return ("_".join(parts[:i]), "_".join(rest[:j]) or "_".join(rest),
                            "_".join(rest[j:]))
            return ("_".join(parts[:i]), "_".join(rest), "")
    for i, p in enumerate(parts):
        if p in VARIANT_CN:
            return ("_".join(parts[:i]), "_".join(parts[i:-1]) or p, parts[-1])
    return ("", short, "")


def describe(short):
    """给类名一句人话：'引擎 · 四阶' / '前保险杠(店) · 外观II'。"""
    _body, fam, var = split_class(short)
    fn = FAMILY_CN.get(fam)
    vn = VARIANT_CN.get(var)
    if fn and vn:
        return "%s · %s" % (fn, vn)
    if fn:
        return fn if not var else "%s · %s" % (fn, var)
    if vn:
        return "%s · %s" % (fam or short, vn)
    return short
