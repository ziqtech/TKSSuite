def _skill_count(context):
    if not context.data_path("TKSkill.dat"):
        return None
    size = context.data_size("TKSkill.dat", compressed=True)
    if size <= 0 or size % 94:
        raise ValueError("TKSkill.dat 必须由完整的 94 字节技能记录组成")
    count = size // 94
    if count > 697:
        raise ValueError(f"TKSkill.dat 有 {count} 条技能，当前最多支持 697 条")
    return count


def detect(context):
    count = _skill_count(context)
    if count is not None and count > 350:
        return f"TKSkill.dat 有 {count} 条技能，必须同时保护定义表、学习状态和存档"
    if context.data_path("WarPC.dat.tksx"):
        return "存在扩展技能初始状态文件 WarPC.dat.tksx"
    return None


def prepare(context):
    if not context.enabled:
        return [context.read_json("baseline_scan.json"),
                context.read_json("baseline_menu.json")]
    if _skill_count(context) is None:
        raise ValueError("扩展技能支持需要 TKSkill.dat")
    return [context.read_json("state.json"), context.read_json("table.json")]
