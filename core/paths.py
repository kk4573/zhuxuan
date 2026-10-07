"""竹喧 · 路径解析（兼容「直接跑源码」和「打包成 exe」两种形态）

打包成 exe 后（PyInstaller）：
  · `sys.executable` 是 exe 自己，数据**优先**放在 exe 旁边（可写、能备份、好带走）
  · `sys._MEIPASS` 是运行时解压出来的临时目录，里面放打包进去的静态资源（web/）
直接跑源码时这两个指向同一个目录。

⚠️ 放在 exe 旁边有个前提：**那个目录得能写**。要是有人把 exe 丢进
`C:\Program Files` 或者别的需要管理员权限的地方，写不进去就整个程序起不来。
所以先探测能不能写，不能写就退回 `%LOCALAPPDATA%\竹喧`（永远可写）。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_DIR_NAME = "竹喧"


def _can_write(d: Path) -> bool:
    """真的建一下、写一下、删一下 —— 只看权限位不准（受只读属性/策略/受控文件夹影响）。"""
    try:
        d.mkdir(parents=True, exist_ok=True)
        probe = d / ".write_test"
        probe.write_text("x", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


if getattr(sys, "frozen", False):
    _exe_dir = Path(sys.executable).resolve().parent
    if _can_write(_exe_dir / "data"):
        BASE_DIR = _exe_dir
    else:
        # exe 所在目录写不了（Program Files 之类）→ 退回用户目录
        _local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        BASE_DIR = Path(_local) / APP_DIR_NAME
        _can_write(BASE_DIR)
    RES_DIR = Path(getattr(sys, "_MEIPASS", BASE_DIR))
else:
    BASE_DIR = Path(__file__).resolve().parent.parent
    RES_DIR = BASE_DIR

DATA_DIR = BASE_DIR / "data"
WEB_DIR = RES_DIR / "web"
