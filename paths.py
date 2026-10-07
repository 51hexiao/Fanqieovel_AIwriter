# -*- coding: utf-8 -*-
"""路径解析：普通运行=源码目录；打包成exe后，只读资源在包内，
可写数据（数据库/配置/日志）放在 exe 旁边，整个文件夹可随意搬动。
FANQIE_DATA_DIR 环境变量可把可写数据整体指到别处（测试隔离用，
冒烟测试指向临时目录，绝不碰真实 data.db/config.json）。"""
import os
import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    ASSETS_DIR = Path(sys._MEIPASS)
    DATA_DIR = Path(sys.executable).resolve().parent
else:
    ASSETS_DIR = DATA_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("FANQIE_DATA_DIR") or DATA_DIR)

# 打包成无窗口 exe 后 stdout/stderr 为 None，重定向到日志文件，
# 否则 print/logging 会崩溃
if sys.stdout is None:
    sys.stdout = open(DATA_DIR / "app.log", "a", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = sys.stdout
