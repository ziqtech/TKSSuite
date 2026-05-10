#!/usr/bin/env python3
"""act_editor v2.3 冒烟测试 (SWS.GRP 音效版)
==================================================
验证:
  1. 文件可导入, 音效 API 存在
  2. _SWSGrp 可加载 SWS.GRP + SWS.IDX
  3. sws_grp.get_wav / wav_info / extract_to_temp 工作
  4. 条目级 bbox 计算
  5. 尾部 tail 音效触发表能定位到 SWS.GRP 段
"""
import os
import sys
import tkinter as tk

THIS = os.path.dirname(os.path.abspath(__file__))
if THIS not in sys.path:
    sys.path.insert(0, THIS)

import act_editor as A  # noqa: E402

TKS_DIR = r"逆向工作区"


def check(cond, msg):
    tag = "[OK]" if cond else "[FAIL]"
    print(f"{tag} {msg}")
    if not cond:
        raise SystemExit(1)


def main():
    print("=" * 60)
    print("act_editor v2.3 smoke test (SWS.GRP)")
    print("=" * 60)

    # 1. 模块级 API
    check(hasattr(A, '_SWSGrp'), '_SWSGrp 类存在')
    check(hasattr(A, '_mci_play_async'), '_mci_play_async 存在')
    check(hasattr(A, '_cleanup_sws_tempfiles'), '_cleanup_sws_tempfiles 存在')

    # 2. 独立加载 SWS.GRP + SWS.IDX
    sws = A._SWSGrp(
        os.path.join(TKS_DIR, 'SWS.GRP'),
        os.path.join(TKS_DIR, 'SWS.IDX'))
    n = sws.load_index()
    check(n > 0, f'SWS.IDX 加载, 段数 = {n}')
    check(n >= 500, f'段数 >= 500 (实测应为 506, 此处 {n})')

    # 3. 读取若干段验证
    hits = 0
    for sid in (0, 1, 40, 63, 72, 95):
        info = sws.wav_info(sid)
        if info:
            ch, sr, bits, dur = info
            print(f"    sid={sid:03d}: {ch}ch {sr}Hz {bits}bit {dur:.2f}s")
            hits += 1
        else:
            print(f"    sid={sid:03d}: (非 WAV 段或读取失败)")
    check(hits >= 3, '至少有 3 个采样 sid 可解析 WAV 元信息')

    # 4. 提取到临时文件
    p = sws.extract_to_temp(40)
    check(p is not None and os.path.exists(p),
          f'sid=40 提取到临时 WAV: {p}')
    sz = os.path.getsize(p)
    print(f"    临时文件大小: {sz} bytes")
    check(sz > 44, '临时 WAV 至少有 WAV 头 (>44B)')

    # 5. 启动 GUI (headless - withdraw)
    root = tk.Tk()
    root.withdraw()
    ed = A.ActEditor(root)

    # 6. 模拟 _load_tks_dir 效果 (绕过交互式对话框)
    ed.act_path = os.path.join(TKS_DIR, 'TKAct.dat')
    ed.aa_path = os.path.join(TKS_DIR, 'Aa.JVG')
    ed.af_path = os.path.join(TKS_DIR, 'Af.JVG')
    ed.sound_dir = os.path.join(TKS_DIR, 'Sound')
    ed.sws_grp = sws
    check(ed.sws_grp is not None, 'editor.sws_grp 已绑定')

    # 7. 加载 TKAct.dat
    ed._reload()
    check(len(ed.entries) == A.ACT_ENTRY_COUNT,
          f'解析 entries 数量: {len(ed.entries)}')

    # 8. JVG + bbox
    ed._preview_load_jvg()
    target = None
    for e in ed.entries:
        if A.entry_active_layers(e):
            target = e
            break
    if target is not None:
        bbox = ed._compute_entry_bbox(target)
        print(f"    entry #{target['index']} bbox = {bbox}")
        check(bbox is not None, 'bbox 计算成功')
        check(bbox[0] <= 0 <= bbox[2] and bbox[1] <= 0 <= bbox[3],
              'bbox 包含原点 (0,0)')

    # 9. 尾部 sound_id 命中统计
    n_entry_with_sfx = 0
    n_resolved = 0
    sample = []
    for e in ed.entries:
        tail = e.get('tail') or []
        for i in range(16):
            sid = tail[i * 2] if i * 2 < len(tail) else 0
            trig = tail[i * 2 + 1] if i * 2 + 1 < len(tail) else 0
            if sid == 0:
                continue
            n_entry_with_sfx += 1
            path = ed._resolve_sound_path(sid)
            if path:
                n_resolved += 1
                if len(sample) < 5:
                    info = sws.wav_info(sid)
                    info_s = (f"{info[0]}ch {info[1]}Hz {info[3]:.2f}s"
                              if info else "?")
                    sample.append((e['index'], i, sid, trig, info_s))
            break  # 每 entry 只计一次

    print(f"    带音效的 entry: {n_entry_with_sfx} / {len(ed.entries)}")
    print(f"    能解析到音效文件: {n_resolved} / {n_entry_with_sfx}")
    for s in sample:
        print(f"      entry #{s[0]:03d} 对{s[1]} sid={s[2]:04d} "
              f"trig@tick={s[3]}  ({s[4]})")
    check(n_resolved > 0, '至少一条音效能从 SWS.GRP 解析出来')
    # 预期 resolved 覆盖率应很高 (SWS.GRP 有 506 段, 绝大多数 sid 都在范围内)
    check(n_resolved >= n_entry_with_sfx * 0.9,
          f'SWS.GRP 覆盖率 >= 90% ({n_resolved}/{n_entry_with_sfx})')

    # 10. 清理
    root.destroy()
    A._cleanup_sws_tempfiles()
    print()
    print("=" * 60)
    print("all checks passed")
    print("=" * 60)


if __name__ == '__main__':
    main()
