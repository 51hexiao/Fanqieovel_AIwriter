# -*- coding: utf-8 -*-
"""桌面版入口：原生窗口（pywebview）+ 内置服务器。
开发运行：python desktop.py
打包exe：见 build_desktop.bat
"""
import threading
import time

import paths  # noqa: F401  必须最先导入：修正打包模式下的输出流
import uvicorn
import webview

from app import app

URL = "http://127.0.0.1:8787"


def start_server():
    uvicorn.run(app, host="127.0.0.1", port=8787, log_level="warning")


def main():
    import httpx
    try:
        httpx.get(URL + "/api/config", timeout=1)
    except Exception:
        threading.Thread(target=start_server, daemon=True).start()
        for _ in range(50):
            try:
                httpx.get(URL + "/api/config", timeout=1)
                break
            except Exception:
                time.sleep(0.2)
    try:
        webview.create_window("番茄短故事工作台", URL, width=1240, height=860)
        webview.start()
    except Exception as e:
        print("原生窗口启动失败，改用默认浏览器打开：", e)
        import webbrowser
        webbrowser.open(URL)
        threading.Event().wait()  # 保持进程存活


if __name__ == "__main__":
    main()
