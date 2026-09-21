def prepare(context):
    operations = [context.read_json("stream.json")]
    if context.option("tksave_expand.reopen_stream"):
        operations.append(context.read_json("reopen.json"))
    if context.data_path("WarPC.dat"):
        size = context.data_size("WarPC.dat", compressed=True)
        if size > 150722:
            operations.append({
                "type": "patch_imm32",
                "id": "tksave_expand.buffer",
                "name": "存读档缓冲区扩容",
                "desc": "存读档缓冲区长度跟随实际 WarPC 数据，加上原有 9200 字节前缀",
                "value_scan": True,
                "expect_value": 159922,
                "new_value": 9200 + size,
                "expect_count": 0,
            })
    if "tkskill_expand" in context.enabled_ids:
        operations.append(context.read_json("persistence.json"))
    return operations
