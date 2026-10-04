"""TKAct.dat 启动前临时截断，目标进程挂起后恢复完整数据供补丁与游戏读取。"""

import os
import shutil

TKACT_ORIG_SIZE = 509600
TKACT_REC_SIZE = 784
TKACT_TEMP_FILE = "TKAct.dat.expanded"


def prepare_tkact_for_game(log_func=None):
    """检测扩展版 TKAct.dat，暂存完整数据并临时截断游戏文件。"""
    log = log_func or (lambda x: None)

    # 上次异常退出残留时先恢复，避免基于截断文件重复处理。
    if os.path.isfile(TKACT_TEMP_FILE + ".tmp"):
        os.remove(TKACT_TEMP_FILE + ".tmp")
    if os.path.isfile(TKACT_TEMP_FILE):
        restore_tkact_for_game(log_func=log)
    elif os.path.isfile("TKAct.dat.restore.tmp"):
        os.replace("TKAct.dat.restore.tmp", "TKAct.dat")

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
    temp_path = TKACT_TEMP_FILE + ".tmp"
    with open(temp_path, "wb") as f:
        f.write(full)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp_path, TKACT_TEMP_FILE)
    try:
        with open("TKAct.dat", "wb") as f:
            f.write(full[:TKACT_ORIG_SIZE])
            f.flush()
            os.fsync(f.fileno())
    except OSError:
        restore_tkact_for_game(log_func=log)
        raise

    log(f"  TKAct.dat 已临时截断到原版 {TKACT_ORIG_SIZE} 字节 "
        f"(完整数据 {len(full)} 字节已暂存为 {TKACT_TEMP_FILE})")
    return True


def restore_tkact_for_game(log_func=None):
    """从暂存文件恢复扩展版 TKAct.dat，并清理暂存文件。"""
    log = log_func or (lambda x: None)
    if not os.path.isfile(TKACT_TEMP_FILE):
        return False
    with open(TKACT_TEMP_FILE, "rb") as source:
        full = source.read()
    restore_path = "TKAct.dat.restore.tmp"
    with open(restore_path, "wb") as target:
        target.write(full)
        target.flush()
        os.fsync(target.fileno())
    os.replace(restore_path, "TKAct.dat")
    os.remove(TKACT_TEMP_FILE)
    log(f"  已恢复扩展版 TKAct.dat ({len(full)} 字节)")
    return True
