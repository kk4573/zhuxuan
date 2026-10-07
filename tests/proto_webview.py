# -*- coding: utf-8 -*-
"""临时原型：把竹喧的界面嵌进程序自己的窗口（用 WebView2），而不是开一个浏览器窗口。

用途：给用户看效果，判断要不要把底层从"调浏览器"改成"内嵌网页组件"。
跑法：
    1. 先确保服务在跑（双击竹喧.exe 或 python app.py）
    2. .venv/Scripts/python.exe tests/proto_webview.py
"""
import ctypes
import sys
import time
import urllib.request

import webview

URL = "http://127.0.0.1:8765/"
W, H = 1331, 896


def wait_ready(timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        try:
            urllib.request.urlopen(URL + "api/stats", timeout=2)
            return True
        except Exception:
            time.sleep(0.4)
    return False


def darken_titlebar(hwnd):
    """把标题栏刷成深色。

    注意：这次和之前失败的那次不一样 —— 窗口是**我们自己的进程**创建的，
    不会被 Edge 初始化时刷回去。所以这条路现在能走通。
    """
    value = ctypes.c_int(1)
    ok = False
    for attr in (19, 20):        # DWMWA_USE_IMMERSIVE_DARK_MODE 的两个编号，都试
        rc = ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, attr, ctypes.byref(value), ctypes.sizeof(value))
        ok = ok or rc == 0
    return ok


def main():
    if not wait_ready():
        print(f"服务没起来，先双击竹喧.exe，或跑 python app.py。地址：{URL}")
        return 1

    window = webview.create_window(
        "竹喧",
        URL,
        width=W, height=H,
        min_size=(900, 640),
        # 关掉右键菜单和开发者工具，免得看起来像浏览器
        easy_drag=False,
    )

    def on_shown():
        time.sleep(0.8)
        try:
            hwnd = ctypes.windll.user32.FindWindowW(None, "竹喧")
            if hwnd:
                darken_titlebar(hwnd)
                print(f"已把标题栏刷成深色（hwnd={hwnd}）")
            else:
                print("没找到窗口句柄，标题栏保持系统默认")
        except Exception as e:
            print("刷标题栏失败:", e)

    import threading
    # pywebview 6.x 用 window.events 注册事件（老写法 on_shown= 传参已经不管用了）
    try:
        window.events.shown += lambda: threading.Thread(target=on_shown, daemon=True).start()
    except Exception as e:
        print("注册 shown 事件失败:", e)
        threading.Thread(target=on_shown, daemon=True).start()

    webview.start(debug=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
