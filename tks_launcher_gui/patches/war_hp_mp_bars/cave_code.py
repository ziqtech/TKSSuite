# -*- coding: utf-8 -*-
"""
战场头顶血条内力条 (war_hp_mp_bars) — cave 带注释机器码源

战场头顶血条内力条：所有存活单位头顶居中显示 52x6 血条(1px 描边环 + 2px 圆角 + 三段配色:
≥60% 绿 / ≥30% 琥珀 / 其余红) + 52x4 内力条(亮蓝, 更细且紧贴血条下方),
内区 50 列 = 10 格 × (4 列填充 + 1 列格线), 按当前待机帧精灵几何精确锚定头顶。

完整版本历史与逆向细节见 patch.json 的 _comment 字段。

【定位与约定】
  - 本文件是给人阅读的带注释机器码源, 与 patch.json 的 cave_code 字节级一致。
  - 启动器运行时只读取 patch.json; 本文件不会被加载, 纯作历史备注与可读性存档。
  - 由 tks_launcher_gui/tests/test_war_hp_mp_bars_cave.py --write 生成。

v6 (现代化样式): 由 50x5 纯红/纯蓝矩形改为 52x6(血) + 52x4(内力) 现代条 ——
  1px 描边 / 2px 圆角(逐行内缩 2,1,0,0,1,2 与 2,1,1,2) / 内分 10 格
  (每格 4 列填充 + 1 列格线, 满格 40 列) / 三段配色 + 亮蓝内力;
  HP 未满 1 格的存活单位至少保留 1 列 (原版此情形整条不画)。
v5.1 (16:9 兼容): 行步长与右边界改为运行时读取 [0x4E7CC8]
  (视口/画布宽: 原版 640 / 宽屏补丁 856)。宽度硬编码会让宽屏下每行漂 216px
  并丢掉右缘单位的条。
"""
CAVE_CODE = bytes([
    0x60,                                                          # 0000  pushal
    0x81, 0xEC, 0xC0, 0x00, 0x00, 0x00,                            # 0001  sub esp, 0xc0
    0xFC,                                                          # 0007  cld
    0x8B, 0x45, 0x08,                                              # 0008  mov eax, dword ptr [ebp + 8]
    0x89, 0xE5,                                                    # 000B  mov ebp, esp
    0x89, 0x45, 0x00,                                              # 000D  mov dword ptr [ebp], eax
    0x8B, 0x0D, 0xC8, 0x7C, 0x4E, 0x00,                            # 0010  mov ecx, dword ptr [0x4e7cc8]
    0x89, 0x4D, 0x04,                                              # 0016  mov dword ptr [ebp + 4], ecx
    0x0F, 0xB6, 0x0D, 0x82, 0xF8, 0x9D, 0x00,                      # 0019  movzx ecx, byte ptr [0x9df882]
    0x83, 0xF9, 0x20,                                              # 0020  cmp ecx, 0x20
    0x76, 0x02,                                                    # 0023  jbe 0x27
    0xB1, 0x20,                                                    # 0025  mov cl, 0x20
    0x89, 0x4D, 0x08,                                              # 0027  mov dword ptr [ebp + 8], ecx
    0xC7, 0x45, 0x0C, 0x00, 0x00, 0x00, 0x00,                      # 002A  mov dword ptr [ebp + 0xc], 0
    0x8B, 0x45, 0x0C,                                              # 0031  mov eax, dword ptr [ebp + 0xc]
    0x8B, 0x4D, 0x08,                                              # 0034  mov ecx, dword ptr [ebp + 8]
    0x39, 0xC8,                                                    # 0037  cmp eax, ecx
    0x0F, 0x8D, 0x53, 0x01, 0x00, 0x00,                            # 0039  jge 0x192
    0x31, 0xD2,                                                    # 003F  xor edx, edx
    0x8A, 0x90, 0x5A, 0x70, 0x9D, 0x00,                            # 0041  mov dl, byte ptr [eax + 0x9d705a]
    0x83, 0xFA, 0x20,                                              # 0047  cmp edx, 0x20
    0x0F, 0x83, 0x3A, 0x01, 0x00, 0x00,                            # 004A  jae 0x18a
    0x69, 0xC2, 0x1E, 0x04, 0x00, 0x00,                            # 0050  imul eax, edx, 0x41e
    0x05, 0x7A, 0x70, 0x9D, 0x00,                                  # 0056  add eax, 0x9d707a
    0x0F, 0xBF, 0x48, 0x0A,                                        # 005B  movsx ecx, word ptr [eax + 0xa]
    0x89, 0x4D, 0x10,                                              # 005F  mov dword ptr [ebp + 0x10], ecx
    0x85, 0xC9,                                                    # 0062  test ecx, ecx
    0x0F, 0x8E, 0x20, 0x01, 0x00, 0x00,                            # 0064  jle 0x18a
    0x0F, 0xB7, 0x48, 0x0C,                                        # 006A  movzx ecx, word ptr [eax + 0xc]
    0x89, 0x4D, 0x14,                                              # 006E  mov dword ptr [ebp + 0x14], ecx
    0x0F, 0xB7, 0x48, 0x10,                                        # 0071  movzx ecx, word ptr [eax + 0x10]
    0x89, 0x4D, 0x18,                                              # 0075  mov dword ptr [ebp + 0x18], ecx
    0x0F, 0xB7, 0x48, 0x14,                                        # 0078  movzx ecx, word ptr [eax + 0x14]
    0x89, 0x4D, 0x1C,                                              # 007C  mov dword ptr [ebp + 0x1c], ecx
    0x0F, 0xBF, 0x04, 0x95, 0x02, 0xF8, 0x9D, 0x00,                # 007F  movsx eax, word ptr [edx*4 + 0x9df802]
    0x2B, 0x05, 0xA8, 0x42, 0x82, 0x00,                            # 0087  sub eax, dword ptr [0x8242a8]
    0x2D, 0x14, 0x00, 0x00, 0x00,                                  # 008D  sub eax, 0x14
    0x89, 0x45, 0x34,                                              # 0092  mov dword ptr [ebp + 0x34], eax
    0x0F, 0xBF, 0x04, 0x95, 0x04, 0xF8, 0x9D, 0x00,                # 0095  movsx eax, word ptr [edx*4 + 0x9df804]
    0x2B, 0x05, 0xAC, 0x42, 0x82, 0x00,                            # 009D  sub eax, dword ptr [0x8242ac]
    0x2D, 0x84, 0x00, 0x00, 0x00,                                  # 00A3  sub eax, 0x84
    0x79, 0x02,                                                    # 00A8  jns 0xac
    0x31, 0xC0,                                                    # 00AA  xor eax, eax
    0x89, 0x45, 0x38,                                              # 00AC  mov dword ptr [ebp + 0x38], eax
    0x8B, 0x4D, 0x04,                                              # 00AF  mov ecx, dword ptr [ebp + 4]
    0x83, 0xE9, 0x34,                                              # 00B2  sub ecx, 0x34
    0x8B, 0x45, 0x34,                                              # 00B5  mov eax, dword ptr [ebp + 0x34]
    0x39, 0xC8,                                                    # 00B8  cmp eax, ecx
    0x0F, 0x87, 0xCA, 0x00, 0x00, 0x00,                            # 00BA  ja 0x18a
    0x8B, 0x45, 0x38,                                              # 00C0  mov eax, dword ptr [ebp + 0x38]
    0x3D, 0xD6, 0x01, 0x00, 0x00,                                  # 00C3  cmp eax, 0x1d6
    0x0F, 0x87, 0xBC, 0x00, 0x00, 0x00,                            # 00C8  ja 0x18a
    0x8B, 0x45, 0x10,                                              # 00CE  mov eax, dword ptr [ebp + 0x10]
    0x69, 0xC0, 0x28, 0x00, 0x00, 0x00,                            # 00D1  imul eax, eax, 0x28
    0x8B, 0x4D, 0x18,                                              # 00D7  mov ecx, dword ptr [ebp + 0x18]
    0x85, 0xC9,                                                    # 00DA  test ecx, ecx
    0x0F, 0x8E, 0x53, 0x00, 0x00, 0x00,                            # 00DC  jle 0x135
    0x31, 0xD2,                                                    # 00E2  xor edx, edx
    0xF7, 0xF1,                                                    # 00E4  div ecx
    0x85, 0xC0,                                                    # 00E6  test eax, eax
    0x75, 0x05,                                                    # 00E8  jne 0xef
    0xB8, 0x01, 0x00, 0x00, 0x00,                                  # 00EA  mov eax, 1
    0x83, 0xF8, 0x28,                                              # 00EF  cmp eax, 0x28
    0x76, 0x05,                                                    # 00F2  jbe 0xf9
    0xB8, 0x28, 0x00, 0x00, 0x00,                                  # 00F4  mov eax, 0x28
    0x89, 0x45, 0x20,                                              # 00F9  mov dword ptr [ebp + 0x20], eax
    0xB8, 0xCC, 0x4E, 0x00, 0x00,                                  # 00FC  mov eax, 0x4ecc
    0x8B, 0x4D, 0x20,                                              # 0101  mov ecx, dword ptr [ebp + 0x20]
    0x83, 0xF9, 0x18,                                              # 0104  cmp ecx, 0x18
    0x0F, 0x83, 0x13, 0x00, 0x00, 0x00,                            # 0107  jae 0x120
    0xB8, 0x80, 0xFD, 0x00, 0x00,                                  # 010D  mov eax, 0xfd80
    0x83, 0xF9, 0x0C,                                              # 0112  cmp ecx, 0xc
    0x0F, 0x83, 0x05, 0x00, 0x00, 0x00,                            # 0115  jae 0x120
    0xB8, 0xC6, 0xE1, 0x00, 0x00,                                  # 011B  mov eax, 0xe1c6
    0x89, 0x45, 0x24,                                              # 0120  mov dword ptr [ebp + 0x24], eax
    0x8B, 0x45, 0x38,                                              # 0123  mov eax, dword ptr [ebp + 0x38]
    0x89, 0x45, 0x2C,                                              # 0126  mov dword ptr [ebp + 0x2c], eax
    0xC7, 0x45, 0x28, 0x06, 0x00, 0x00, 0x00,                      # 0129  mov dword ptr [ebp + 0x28], 6
    0xE8, 0x6C, 0x00, 0x00, 0x00,                                  # 0130  call 0x1a1
    0x8B, 0x45, 0x14,                                              # 0135  mov eax, dword ptr [ebp + 0x14]
    0x85, 0xC0,                                                    # 0138  test eax, eax
    0x0F, 0x8E, 0x4A, 0x00, 0x00, 0x00,                            # 013A  jle 0x18a
    0x69, 0xC0, 0x28, 0x00, 0x00, 0x00,                            # 0140  imul eax, eax, 0x28
    0x8B, 0x4D, 0x1C,                                              # 0146  mov ecx, dword ptr [ebp + 0x1c]
    0x85, 0xC9,                                                    # 0149  test ecx, ecx
    0x0F, 0x8E, 0x39, 0x00, 0x00, 0x00,                            # 014B  jle 0x18a
    0x31, 0xD2,                                                    # 0151  xor edx, edx
    0xF7, 0xF1,                                                    # 0153  div ecx
    0x85, 0xC0,                                                    # 0155  test eax, eax
    0x75, 0x05,                                                    # 0157  jne 0x15e
    0xB8, 0x01, 0x00, 0x00, 0x00,                                  # 0159  mov eax, 1
    0x83, 0xF8, 0x28,                                              # 015E  cmp eax, 0x28
    0x76, 0x05,                                                    # 0161  jbe 0x168
    0xB8, 0x28, 0x00, 0x00, 0x00,                                  # 0163  mov eax, 0x28
    0x89, 0x45, 0x20,                                              # 0168  mov dword ptr [ebp + 0x20], eax
    0xB8, 0x5F, 0x4D, 0x00, 0x00,                                  # 016B  mov eax, 0x4d5f
    0x89, 0x45, 0x24,                                              # 0170  mov dword ptr [ebp + 0x24], eax
    0x8B, 0x45, 0x38,                                              # 0173  mov eax, dword ptr [ebp + 0x38]
    0x05, 0x06, 0x00, 0x00, 0x00,                                  # 0176  add eax, 6
    0x89, 0x45, 0x2C,                                              # 017B  mov dword ptr [ebp + 0x2c], eax
    0xC7, 0x45, 0x28, 0x04, 0x00, 0x00, 0x00,                      # 017E  mov dword ptr [ebp + 0x28], 4
    0xE8, 0x17, 0x00, 0x00, 0x00,                                  # 0185  call 0x1a1
    0xFF, 0x45, 0x0C,                                              # 018A  inc dword ptr [ebp + 0xc]
    0xE9, 0x9F, 0xFE, 0xFF, 0xFF,                                  # 018D  jmp 0x31
    0x81, 0xC4, 0xC0, 0x00, 0x00, 0x00,                            # 0192  add esp, 0xc0
    0x61,                                                          # 0198  popal
    0x0F, 0xBF, 0x15, 0x88, 0x6C, 0x9D, 0x00,                      # 0199  movsx edx, word ptr [0x9d6c88]
    0xC3,                                                          # 01A0  ret
    0x8D, 0x7D, 0x50,                                              # 01A1  lea edi, [ebp + 0x50]
    0x8B, 0x4D, 0x20,                                              # 01A4  mov ecx, dword ptr [ebp + 0x20]
    0xC7, 0x45, 0x40, 0x0A, 0x00, 0x00, 0x00,                      # 01A7  mov dword ptr [ebp + 0x40], 0xa
    0xBA, 0x04, 0x00, 0x00, 0x00,                                  # 01AE  mov edx, 4
    0x85, 0xC9,                                                    # 01B3  test ecx, ecx
    0x74, 0x09,                                                    # 01B5  je 0x1c0
    0x8B, 0x45, 0x24,                                              # 01B7  mov eax, dword ptr [ebp + 0x24]
    0x66, 0x89, 0x07,                                              # 01BA  mov word ptr [edi], ax
    0x49,                                                          # 01BD  dec ecx
    0xEB, 0x07,                                                    # 01BE  jmp 0x1c7
    0x66, 0xB8, 0x45, 0x29,                                        # 01C0  mov ax, 0x2945
    0x66, 0x89, 0x07,                                              # 01C4  mov word ptr [edi], ax
    0x83, 0xC7, 0x02,                                              # 01C7  add edi, 2
    0x4A,                                                          # 01CA  dec edx
    0x75, 0xE6,                                                    # 01CB  jne 0x1b3
    0x66, 0xB8, 0xE3, 0x18,                                        # 01CD  mov ax, 0x18e3
    0x66, 0x89, 0x07,                                              # 01D1  mov word ptr [edi], ax
    0x83, 0xC7, 0x02,                                              # 01D4  add edi, 2
    0xFF, 0x4D, 0x40,                                              # 01D7  dec dword ptr [ebp + 0x40]
    0x75, 0xD2,                                                    # 01DA  jne 0x1ae
    0xC7, 0x45, 0x30, 0x00, 0x00, 0x00, 0x00,                      # 01DC  mov dword ptr [ebp + 0x30], 0
    0x8B, 0x45, 0x30,                                              # 01E3  mov eax, dword ptr [ebp + 0x30]
    0x8B, 0x4D, 0x28,                                              # 01E6  mov ecx, dword ptr [ebp + 0x28]
    0x49,                                                          # 01E9  dec ecx
    0x29, 0xC1,                                                    # 01EA  sub ecx, eax
    0x39, 0xC8,                                                    # 01EC  cmp eax, ecx
    0x7E, 0x02,                                                    # 01EE  jle 0x1f2
    0x89, 0xC8,                                                    # 01F0  mov eax, ecx
    0x83, 0xF8, 0x02,                                              # 01F2  cmp eax, 2
    0x7E, 0x05,                                                    # 01F5  jle 0x1fc
    0xB8, 0x02, 0x00, 0x00, 0x00,                                  # 01F7  mov eax, 2
    0xB9, 0x02, 0x00, 0x00, 0x00,                                  # 01FC  mov ecx, 2
    0x29, 0xC1,                                                    # 0201  sub ecx, eax
    0x89, 0x4D, 0x3C,                                              # 0203  mov dword ptr [ebp + 0x3c], ecx
    0x8B, 0x45, 0x2C,                                              # 0206  mov eax, dword ptr [ebp + 0x2c]
    0x03, 0x45, 0x30,                                              # 0209  add eax, dword ptr [ebp + 0x30]
    0x0F, 0xAF, 0x45, 0x04,                                        # 020C  imul eax, dword ptr [ebp + 4]
    0x03, 0x45, 0x34,                                              # 0210  add eax, dword ptr [ebp + 0x34]
    0x03, 0xC1,                                                    # 0213  add eax, ecx
    0x8B, 0x55, 0x00,                                              # 0215  mov edx, dword ptr [ebp]
    0x8D, 0x3C, 0x42,                                              # 0218  lea edi, [edx + eax*2]
    0x8B, 0x45, 0x30,                                              # 021B  mov eax, dword ptr [ebp + 0x30]
    0x85, 0xC0,                                                    # 021E  test eax, eax
    0x74, 0x2E,                                                    # 0220  je 0x250
    0x8B, 0x45, 0x28,                                              # 0222  mov eax, dword ptr [ebp + 0x28]
    0x48,                                                          # 0225  dec eax
    0x3B, 0x45, 0x30,                                              # 0226  cmp eax, dword ptr [ebp + 0x30]
    0x74, 0x25,                                                    # 0229  je 0x250
    0x66, 0xB8, 0x82, 0x10,                                        # 022B  mov ax, 0x1082
    0x66, 0x89, 0x07,                                              # 022F  mov word ptr [edi], ax
    0x83, 0xC7, 0x02,                                              # 0232  add edi, 2
    0x8D, 0x74, 0x4D, 0x50,                                        # 0235  lea esi, [ebp + ecx*2 + 0x50]
    0xBA, 0x32, 0x00, 0x00, 0x00,                                  # 0239  mov edx, 0x32
    0x29, 0xCA,                                                    # 023E  sub edx, ecx
    0x29, 0xCA,                                                    # 0240  sub edx, ecx
    0x89, 0xD1,                                                    # 0242  mov ecx, edx
    0xF3, 0x66, 0xA5,                                              # 0244  rep movsw word ptr es:[edi], word ptr [esi]
    0x66, 0xB8, 0x82, 0x10,                                        # 0247  mov ax, 0x1082
    0x66, 0x89, 0x07,                                              # 024B  mov word ptr [edi], ax
    0xEB, 0x12,                                                    # 024E  jmp 0x262
    0x66, 0xB8, 0x82, 0x10,                                        # 0250  mov ax, 0x1082
    0xBA, 0x34, 0x00, 0x00, 0x00,                                  # 0254  mov edx, 0x34
    0x29, 0xCA,                                                    # 0259  sub edx, ecx
    0x29, 0xCA,                                                    # 025B  sub edx, ecx
    0x89, 0xD1,                                                    # 025D  mov ecx, edx
    0xF3, 0x66, 0xAB,                                              # 025F  rep stosw word ptr es:[edi], ax
    0xFF, 0x45, 0x30,                                              # 0262  inc dword ptr [ebp + 0x30]
    0x8B, 0x45, 0x30,                                              # 0265  mov eax, dword ptr [ebp + 0x30]
    0x3B, 0x45, 0x28,                                              # 0268  cmp eax, dword ptr [ebp + 0x28]
    0x0F, 0x82, 0x72, 0xFF, 0xFF, 0xFF,                            # 026B  jb 0x1e3
    0xC3,                                                          # 0271  ret
])
