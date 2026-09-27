"""竹喧 · 路径解析（兼容「直接跑源码」和「打包成 exe」两种形态）

打包成 exe 后（PyInstaller）：
  · `sys.executable` 是 exe 自己，数据要放在 exe **旁边**（可写、能备份）
  · `sys._MEIPASS` 是运行时解压出来的临时目录，里面放打包进去的静态资源（web/）
直接跑源码时这两个指向同一个目录。
"""
from __future__ import annotations

import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).resolve().parent
    RES_DIR = Path(getattr(sys, "_MEIPASS", BASE_DIR))
else:
    BASE_DIR = Path(__file__).resolve().parent.parent
    RES_DIR = BASE_DIR

DATA_DIR = BASE_DIR / "data"
WEB_DIR = RES_DIR / "web"
