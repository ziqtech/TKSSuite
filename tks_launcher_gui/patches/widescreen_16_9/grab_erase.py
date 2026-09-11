# -*- coding: utf-8 -*-
"""grab 时刻的光标擦除 (烤前清除)。

页面机在鼠标事件后会 grab(画布 ← 后备表面), 把上一帧画在后备表面的光标
"烤"进画布 (push 每帧重放 → 光标无限叠加)。本块在 grab 拷贝前把光标矩形
从后备表面恢复掉: 校验后备内容仍精确等于"上一帧画完的样子" (scratch 此刻
仍保有上一帧解码结果, 未 refill), 一致才用 BKBUF 恢复背景。
pushad/popad 全保护 (grab_copy 的 ebp 帧指针与寄存器不破坏, src 基址压栈
后经 [esp] 引用; 循环内 ebp 作行计数, 不能走 [ebp+0xC])。

寄存器映射 (verify/restore 循环内):
  edi = 后备行指针   esi = BKBUF 行指针 (verify) / 拷贝源
  ebx = scratch 行指针                    edx = 列计数
  ebp = 行计数器 (pushad 保护, 不影响 grab_copy 的 [ebp+x] 参数访问)

VA 常量与 cave_code.py 的占位地址保持一致 (重定位窗口覆盖):
  槽位 [0x660800, 0x660899) + BKBUF 精确单值窗口 0x6F6898。
"""
import struct

_LPITCH_VA = 0x00A2ACD8       # 游戏 ddsd 的 lPitch (未重定位)
_BK_VALID = 0x66087C
_BK_STRIDE = 0x660884
_BK_DST = 0x660880
_BK_W = 0x660890
_BK_H = 0x660894
_BK_X0 = 0x660888
_BK_Y0 = 0x66088C
_CUR_PX = 0x660874
_CUR_PY = 0x660878
_SCRATCH_VA = 0x660898
_BKBUF_VA = 0x6F6898
_SENTINEL = 0xFE1F
_MAX_W = 256
_MAX_H = 128


def build_grab_erase() -> bytes:
    code = bytearray()

    def emit(b: bytes) -> None:
        code.extend(b)

    def j32(cond: str) -> int:
        op = {'jo': 0x80, 'jno': 0x81, 'jb': 0x82, 'jae': 0x83, 'je': 0x84,
              'jne': 0x85, 'jbe': 0x86, 'ja': 0x87, 'js': 0x88, 'jns': 0x89,
              'jp': 0x8A, 'jnp': 0x8B, 'jl': 0x8C, 'jge': 0x8D, 'jle': 0x8E,
              'jg': 0x8F}[cond]
        pos = len(code)
        emit(b'\x0F' + bytes([op]) + b'\x00\x00\x00\x00')
        return pos

    def jmp32() -> int:
        pos = len(code)
        emit(b'\xE9\x00\x00\x00\x00')
        return pos

    def i32(v: int) -> bytes:
        return struct.pack('<I', v)

    emit(b'\x60')                                    # pushad
    emit(b'\x8B\x75\x0C')                            # mov esi,[ebp+0xC] ; src(后备)
    emit(b'\x56')                                    # push esi → [esp]
    # 逐像素归属恢复: 仅当 dst 仍等于本帧我们写入的光标像素 (scratch 非哨兵)
    # 才用 BKBUF 背景覆盖; 被游戏局部重绘碰过的像素不动。
    a_pop = None
    emit(b'\xA1' + i32(_BK_VALID))                   # mov eax,[BK_VALID]
    emit(b'\x85\xC0')                                # test eax,eax
    pa0 = j32('je')                                  # jz A_DONE
    emit(b'\xA1' + i32(_BK_STRIDE))                  # mov eax,[BK_STRIDE]
    emit(b'\x03\xC0')                                # add eax,eax ; 像素宽 → 字节行距
    emit(b'\x3B\x05' + i32(_LPITCH_VA))              # cmp eax,[lPitch]
    pa1 = j32('jne')                                 # jne A_DONE
    emit(b'\x3B\x35' + i32(_BK_DST))                 # cmp esi,[BK_DST]
    pa2 = j32('jne')                                 # jne A_DONE
    emit(b'\xA1' + i32(_BK_W))                       # mov eax,[BK_W]
    emit(b'\x85\xC0')
    pa3 = j32('je')
    emit(b'\x3D' + i32(_MAX_W))
    pa4 = j32('ja')
    emit(b'\x8B\x0D' + i32(_BK_H))                   # mov ecx,[BK_H]
    emit(b'\x85\xC9')
    pa5 = j32('je')
    emit(b'\x81\xF9' + i32(_MAX_H))
    pa6 = j32('ja')
    emit(b'\xFC')                                    # cld
    emit(b'\x33\xED')                                # xor ebp,ebp ; y=0
    a_rrow = len(code)
    # 后备行指针 edi = src + ((by+y)*BK_STRIDE + bx)*2
    emit(b'\x8B\xC5')                                # mov eax,ebp
    emit(b'\x03\x05' + i32(_BK_Y0))                  # add eax,[BK_Y0]
    emit(b'\x0F\xAF\x05' + i32(_BK_STRIDE))          # imul eax,[BK_STRIDE]
    emit(b'\x03\x05' + i32(_BK_X0))                  # add eax,[BK_X0]
    emit(b'\x8D\x3C\x00')                            # lea edi,[eax+eax]
    emit(b'\x03\x3C\x24')                            # add edi,[esp] ; src 基址
    # BKBUF 行指针 ebx = BKBUF + y*512
    emit(b'\x8B\xDD')                                # mov ebx,ebp
    emit(b'\xC1\xE3\x09')                            # shl ebx,9
    emit(b'\x81\xC3' + i32(_BKBUF_VA))               # add ebx,BKBUF
    # scratch 行指针 esi = SCRATCH + ((by+y-PY+240)*640 + (bx-PX+320))*2
    emit(b'\x8B\xC5')                                # mov eax,ebp
    emit(b'\x03\x05' + i32(_BK_Y0))                  # add eax,[BK_Y0]
    emit(b'\x2B\x05' + i32(_CUR_PY))                 # sub eax,[CUR_PY]
    emit(b'\x05\xF0\x00\x00\x00')                    # add eax,240
    emit(b'\x69\xC0\x80\x02\x00\x00')                # imul eax,eax,640
    emit(b'\x8B\x15' + i32(_BK_X0))                  # mov edx,[BK_X0]
    emit(b'\x2B\x15' + i32(_CUR_PX))                 # sub edx,[CUR_PX]
    emit(b'\x81\xC2\x40\x01\x00\x00')                # add edx,320
    emit(b'\x03\xC2')                                # add eax,edx
    emit(b'\x8D\x04\x00')                            # lea eax,[eax+eax] ; 像素索引→字节偏移(×2)
    emit(b'\x05' + i32(_SCRATCH_VA))                 # add eax,SCRATCH
    emit(b'\x8B\xF0')                                # mov esi,eax
    emit(b'\x8B\x15' + i32(_BK_W))                   # mov edx,[BK_W]
    a_vpx = len(code)
    emit(b'\x66\x8B\x06')                            # mov ax,[esi] ; 上帧解码值
    emit(b'\x66\x3D' + struct.pack('<H', _SENTINEL))
    pa7 = j32('je')                                  # je A_NEXT (透明位: 未写过)
    emit(b'\x66\x3B\x07')                            # cmp ax,[edi] ; 仍是我们的值?
    pa8 = j32('jne')                                 # jne A_NEXT (被游戏改过, 不动)
    emit(b'\x66\x8B\x03')                            # mov ax,[ebx] ; 快照背景
    emit(b'\x66\x89\x07')                            # mov [edi],ax ; 恢复
    # A_NEXT:
    code[pa7 + 2:pa7 + 6] = struct.pack('<i', len(code) - (pa7 + 6))
    code[pa8 + 2:pa8 + 6] = struct.pack('<i', len(code) - (pa8 + 6))
    emit(b'\x83\xC7\x02')                            # add edi,2
    emit(b'\x83\xC6\x02')                            # add esi,2
    emit(b'\x83\xC3\x02')                            # add ebx,2
    emit(b'\x4A')                                    # dec edx
    pa11 = j32('jne')
    code[pa11 + 2:pa11 + 6] = struct.pack('<i', a_vpx - (pa11 + 6))
    emit(b'\x45')                                    # inc ebp
    emit(b'\x3B\x2D' + i32(_BK_H))                   # cmp ebp,[BK_H]
    pa12 = j32('jb')
    code[pa12 + 2:pa12 + 6] = struct.pack('<i', a_rrow - (pa12 + 6))
    a_pop = len(code)                                # A_DONE 入口 = pops 处
    emit(b'\x5E')                                    # pop esi (配对 push esi)
    emit(b'\x61')                                    # popad
    a_end = len(code)
    for pp in (pa0, pa1, pa2, pa3, pa4, pa5, pa6):
        code[pp + 2:pp + 6] = struct.pack('<i', a_pop - (pp + 6))
    return bytes(code)
