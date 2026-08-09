"""TKAct.dat 扩展文件准备与恢复。

原版游戏只接受 509600 字节的 TKAct.dat。为了兼容 Wine/Winlator 这类无法在
启动早期可靠挂起进程的环境，启动前先把扩展版暂存为 TKAct.dat.expanded，
再把游戏目录里的 TKAct.dat 临时截断到原版大小；运行时由 tkact_expand
脚本补丁读取暂存文件并注入新缓冲区。游戏退出后再恢复扩展版文件。
"""

import os
import shutil

TKACT_ORIG_SIZE = 509600
TKACT_REC_SIZE = 784
TKACT_TEMP_FILE = "TKAct.dat.expanded"


def prepare_tkact_for_game(log_func=None):
    """检测扩展版 TKAct.dat，暂存完整数据并临时截断游戏文件。"""
    log = log_func or (lambda x: None)

    # 上次异常退出残留时先恢复，避免基于截断文件重复处理。
    if os.path.isfile(TKACT_TEMP_FILE):
        restore_tkact_for_game(log_func=log)

    if not os.path.isfile("TKAct.dat"):
        return False
    try:
        size = os.path.getsize("TKAct.dat")
    except OSError:
        return False
    if size <= TKACT_ORIG_SIZE:
        return False
    if size % TKACT_REC_SIZE:
        log(f"  [WARN] TKAct.dat 大小 {size} 不是 {TKACT_REC_SIZE} 的整数倍，跳过临时截断")
        return False

    with open("TKAct.dat", "rb") as f:
        full = f.read()
    with open(TKACT_TEMP_FILE, "wb") as f:
        f.write(full)
    with open("TKAct.dat", "wb") as f:
        f.write(full[:TKACT_ORIG_SIZE])

    log(f"  TKAct.dat 已临时截断到原版 {TKACT_ORIG_SIZE} 字节 "
        f"(完整数据 {len(full)} 字节已暂存为 {TKACT_TEMP_FILE})")
    return True


def restore_tkact_for_game(log_func=None):
    """从暂存文件恢复扩展版 TKAct.dat，并清理暂存文件。"""
    log = log_func or (lambda x: None)
    if not os.path.isfile(TKACT_TEMP_FILE):
        return False
    shutil.copy2(TKACT_TEMP_FILE, "TKAct.dat")
    os.remove(TKACT_TEMP_FILE)
    log(f"  已恢复扩展版 TKAct.dat ({os.path.getsize('TKAct.dat')} 字节)")
    return True
