def prepare(context):
    size = context.data_size("TKSkill.dat", compressed=True)
    if size <= 32900:
        return []
    if "tkskill_expand" not in context.enabled_ids:
        raise ValueError("不能只放宽技能加载长度；必须启用完整的扩展技能支持")
    operation = context.read_json("length.json")
    operation["new_value"] = max(size, 65536)
    return [operation]
