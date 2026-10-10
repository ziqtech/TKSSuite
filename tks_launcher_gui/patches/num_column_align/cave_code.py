# -*- coding: utf-8 -*-
"""数字列对齐 (num_column_align) — 固定布局 cave 生成器

文件级: build_cave_block(cave_base, n) → 完整 cave 块字节。
运行时: 同一函数以 ctx.cave_addr 为 cave_base 调用 (n 来自引擎的 summon_limit,
        本补丁不使用, 保持默认 4 即可通过引擎的 2..8 校验)。

背景: 商店/场品/装备列表的行文本由 sub_4175D8 → wvsprintfA 按字节格式化
("%-N.Ns%d..."), TKT 名称中的 FCOLOR/FRESET 颜色宏字节计入宽度却不渲染,
带宏名称 (10 字节 vs 原版 6 字节) 的数字列整体左移 48px。

修法 (与 shop_price_align v2 相同): 每个 hook 点的 call sub_4175D8 换成
call cave; cave 内两段绘制 —
  1. 数字段: 在栈上压立即数拼出无填充格式串 ("%5dX%2d" / "%3d" / "%4d"),
     x = 名称列起点 + 名称列宽×12px, 直画数字 (字体半角 12px, 全角=2×半角,
     故 N 字节列宽恒等于 N×12px, 与名称字数无关);
  2. 名称段: 原栈 fmt 槽换成 "%s" (0x4E9977), x 保持原值, 尾调用 jmp 画名称,
     颜色宏由 TextStep 照常生效, ret 直达宿主的 add esp 续接点。
所有数字段 x 均满足 x+数字宽 < 640 页面字体画布宽 (sub_44E290 换行边界),
避开 v1 商店补丁踩过的剪裁问题。

布局 (块从 0x7F0 起, [0x000,0x7F0) 为零 — 前段避开 summon_extend 的 fixed 块
[0x680,0x7EB), 引擎按块内非零区间 [0x7F0,0x8A6) 硬编码预留):
  [0x7F0, 0x832)  entry_shop   66B  商店买/卖两处 hook 共用 (7 参数栈, x=285→477, "%5dX%2d")
  [0x832, 0x86C)  entry_bag    58B  场品列表 (6 参数栈, x=285→573, "%3d")
  [0x86C, 0x8A6)  entry_equip  58B  装备列表 (6 参数栈, x=240→360, "%4d")

栈约定: 引擎在 hook 点写 E8 call (patch_engine 一致), 进入 cave 时
[esp] = 返回地址, 其后为宿主压好的 7/6 个参数 (cdecl)。cave 只用
eax/ecx/edx/esi (esi 压栈保护), 不触碰宿主参数槽 (仅写 fmt 槽为 "%s"),
栈在 jmp 前精确回到进入时的 esp。
"""
from __future__ import annotations

BLOCK_BASE_OFFSET = 0x7F0  # 避开 summon_extend 的 fixed 块 [0x680, 0x7EB), 16 字节对齐

# 商店买/卖共用 (7 参数: obj,x,y,fmt,name,price,cnt; 数字段 "%5dX%2d" x=477)
SHOP_CAVE = bytes.fromhex(
    '56'                 # push esi
    '8B742418'           # mov esi,[esp+0x18]        ; esi = name
    '6825326400'         # push 0x00643225           ; "%2d\0"
    '6825356458'         # push 0x58643525           ; "%5dX" → 栈上 "%5dX%2d\0"
    '8D0424'             # lea eax,[esp]             ; eax = "%5dX%2d"
    'FF742428'           # push [esp+0x28]           ; cnt  [S0+0x1C]
    'FF742428'           # push [esp+0x28]           ; price [S0+0x18]
    '50'                 # push eax                  ; fmt
    'FF742424'           # push [esp+0x24]           ; y    [S0+0x0C]
    '68DD010000'         # push 0x1DD                ; x = 477 = 285+16×12
    'FF742424'           # push [esp+0x24]           ; obj  [S0+0x04]
    'B8D8754100'         # mov eax,0x4175D8
    'FFD0'               # call eax                  ; 数字段
    '83C420'             # add esp,0x20              ; 串2+串1+6参数
    'C744241477994E00'   # mov dword [esp+0x14],0x4E9977  ; fmt 槽 = "%s"
    '5E'                 # pop esi
    'B8D8754100'         # mov eax,0x4175D8
    'FFE0'               # jmp eax                   ; 名称段 (尾调用)
)

# 场品列表 (6 参数: obj,x,y,fmt,name,num; 数字段 "%3d" x=573)
BAG_CAVE = bytes.fromhex(
    '56'                 # push esi
    '8B742418'           # mov esi,[esp+0x18]        ; esi = name
    '6825643300'         # push 0x00643325           ; "%3d\0"
    'FF742420'           # push [esp+0x20]           ; num  [S0+0x18]
    '8D442404'           # lea eax,[esp+4]           ; eax = "%3d"
    '50'                 # push eax                  ; fmt
    'FF74241C'           # push [esp+0x1C]           ; y    [S0+0x0C]
    '683D020000'         # push 0x23D                ; x = 573 = 285+24×12
    'FF74241C'           # push [esp+0x1C]           ; obj  [S0+0x04]
    'B8D8754100'         # mov eax,0x4175D8
    'FFD0'               # call eax                  ; 数字段
    '83C418'             # add esp,0x18              ; 串1+5参数
    'C744241477994E00'   # mov dword [esp+0x14],0x4E9977  ; fmt 槽 = "%s"
    '5E'                 # pop esi
    'B8D8754100'         # mov eax,0x4175D8
    'FFE0'               # jmp eax                   ; 名称段 (尾调用)
)

# 装备列表 (6 参数: obj,x,y,fmt,name,num; 数字段 "%4d" x=360)
EQUIP_CAVE = bytes.fromhex(
    '56'                 # push esi
    '8B742418'           # mov esi,[esp+0x18]        ; esi = name
    '6825643400'         # push 0x00643425           ; "%4d\0"
    'FF742420'           # push [esp+0x20]           ; num  [S0+0x18]
    '8D442404'           # lea eax,[esp+4]           ; eax = "%4d"
    '50'                 # push eax                  ; fmt
    'FF74241C'           # push [esp+0x1C]           ; y    [S0+0x0C]
    '6868010000'         # push 0x168                ; x = 360 = 240+10×12
    'FF74241C'           # push [esp+0x1C]           ; obj  [S0+0x04]
    'B8D8754100'         # mov eax,0x4175D8
    'FFD0'               # call eax                  ; 数字段
    '83C418'             # add esp,0x18              ; 串1+5参数
    'C744241477994E00'   # mov dword [esp+0x14],0x4E9977  ; fmt 槽 = "%s"
    '5E'                 # pop esi
    'B8D8754100'         # mov eax,0x4175D8
    'FFE0'               # jmp eax                   ; 名称段 (尾调用)
)

ENTRY_SHOP_OFFSET = BLOCK_BASE_OFFSET
ENTRY_BAG_OFFSET = BLOCK_BASE_OFFSET + len(SHOP_CAVE)
ENTRY_EQUIP_OFFSET = ENTRY_BAG_OFFSET + len(BAG_CAVE)


def build_cave_block(cave_base: int, n: int = 4) -> bytes:
    """返回完整 cave 块; [0,0x680) 补零以避开 cave_hook 自动布局区。"""
    return b'\x00' * BLOCK_BASE_OFFSET + SHOP_CAVE + BAG_CAVE + EQUIP_CAVE
