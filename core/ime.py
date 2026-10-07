"""竹喧 · 输入法控制（Windows）

目标：答题时把输入法切到英文，结束/离开时还原成原来的。

**为什么不用 IMM32**：实测（`tests/probe_ime.py`）Chromium 系（Edge）的窗口
`ImmGetContext` 返回 NULL —— 读不到也改不了输入法的中英文状态。

**实际方案**：切换键盘布局。实测 `WM_INPUTLANGCHANGEREQUEST` 有效，
切换后线程的键盘布局从 `00000804`（中文）变成 `00000409`（英语美国），
并且能准确还原。系统里原本没装英语布局也没关系，`LoadKeyboardLayout` 会临时加载。

⚠️ 副作用：切的是「窗口所在线程」的输入语言，而 Edge 的多个窗口共用主进程 UI 线程，
所以答题时你**其它的 Edge 窗口也会变英文**。离开答题页会自动还原，
不想要就在设置里把「答题时自动切到英文输入法」关掉。
"""
from __future__ import annotations

import ctypes
import os
import time
from ctypes import wintypes

ZH_CN = "00000804"                  # 中文（简体）- 美式键盘
EN_US = "00000409"                  # 英语（美国）
WM_INPUTLANGCHANGEREQUEST = 0x0050
WM_CLOSE = 0x0010
KLF_ACTIVATE = 0x00000001
APP_TITLES = ("竹喧",)

_IS_WIN = os.name == "nt"
user32 = None
if _IS_WIN:
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.EnumWindows.argtypes = [
            ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM), wintypes.LPARAM]
        user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        user32.GetWindowTextLengthW.restype = ctypes.c_int
        user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        user32.GetKeyboardLayout.argtypes = [wintypes.DWORD]
        user32.GetKeyboardLayout.restype = wintypes.HANDLE
        user32.LoadKeyboardLayoutW.argtypes = [wintypes.LPCWSTR, wintypes.UINT]
        user32.LoadKeyboardLayoutW.restype = wintypes.HANDLE
        user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT,
                                        wintypes.WPARAM, wintypes.LPARAM]
        user32.PostMessageW.restype = wintypes.BOOL
    except Exception:
        user32 = None

_saved: dict[int, int] = {}         # 线程 id -> 切换前的 HKL


def klid(hkl: int) -> str:
    """HKL → «00000409» 这种键盘布局 ID"""
    return f"{hkl & 0xFFFF:08X}" if hkl else ""


def _find_windows() -> list[int]:
    result: list[int] = []
    if not user32:
        return result

    def cb(hwnd, _param):
        try:
            if not user32.IsWindowVisible(hwnd):
                return True
            n = user32.GetWindowTextLengthW(hwnd)
            if n <= 0:
                return True
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            if any(t in buf.value for t in APP_TITLES):
                result.append(hwnd)
        except Exception:
            pass
        return True

    user32.EnumWindows(
        ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)(cb), 0)
    return result


def status() -> dict:
    if not user32:
        return {"supported": False, "reason": "只有 Windows 支持"}
    hwnds = _find_windows()
    if not hwnds:
        return {"supported": True, "window": False}
    tid = user32.GetWindowThreadProcessId(hwnds[0], None)
    return {"supported": True, "window": True, "thread": tid,
            "layout": klid(user32.GetKeyboardLayout(tid)),
            "is_english": klid(user32.GetKeyboardLayout(tid)) == EN_US}


def to_english() -> dict:
    """把竹喧窗口所在线程的输入语言切成英语。"""
    if not user32:
        return {"ok": False, "reason": "只有 Windows 支持"}
    hwnds = _find_windows()
    if not hwnds:
        return {"ok": False, "reason": "没找到竹喧窗口"}
    hwnd = hwnds[0]
    tid = user32.GetWindowThreadProcessId(hwnd, None)
    before = user32.GetKeyboardLayout(tid)
    if klid(before) == EN_US:
        return {"ok": True, "already": True, "before": EN_US, "after": EN_US}

    hkl = user32.LoadKeyboardLayoutW(EN_US, KLF_ACTIVATE)
    if not hkl:
        return {"ok": False, "reason": "加载英语键盘布局失败"}

    _saved[tid] = before
    user32.PostMessageW(hwnd, WM_INPUTLANGCHANGEREQUEST, 0, hkl)
    time.sleep(0.06)                     # PostMessage 是异步的，等一下再读回
    after = user32.GetKeyboardLayout(tid)
    ok = klid(after) == EN_US
    return {"ok": ok, "before": klid(before), "after": klid(after),
            "reason": "" if ok else "切换没生效（可能被输入法自身设置拦下了）"}


def app_window_handles() -> list[int]:
    """找出竹喧应用窗口的句柄。

    标题用 `in` 而不是 `==` —— Edge 有时会在后面缀上别的东西。
    和 close_app_windows() 用同一套判断，别各写各的（这里踩过：用了不存在的
    APP_TITLE 常量，NameError 被上层 except 吞掉，窗口一个都找不到还查不出原因）。
    """
    out: list[int] = []
    user32 = ctypes.windll.user32
    EnumProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    def _cb(hwnd, _):
        n = user32.GetWindowTextLengthW(hwnd)
        if n and user32.IsWindowVisible(hwnd):
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            if any(t in buf.value for t in APP_TITLES):
                out.append(hwnd)
        return True

    user32.EnumWindows(EnumProc(_cb), 0)
    return out


def darken_titlebar(hwnd: int) -> bool:
    """把窗口标题栏刷成深色。

    竹喧是深色界面，但窗口标题栏由系统画：你的系统是浅色主题，标题栏就是一条白杠，
    和界面很不搭（用户反馈的）。Edge 的 --app 窗口没法去掉标题栏（去掉就不能拖动和关闭了），
    但可以让它变深。

    ⚠️ 实测（本机 Windows 11 26200）：**必须用属性号 19**，只设 20 一点反应都没有
    （虽然两个都返回 0"成功"）。两个都设上，兼容新旧版本。
    """
    try:
        value = ctypes.c_int(1)
        ok = False
        for attr in (19, 20):                      # DWMWA_USE_IMMERSIVE_DARK_MODE 的两个编号
            rc = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, attr, ctypes.byref(value), ctypes.sizeof(value))
            ok = ok or rc == 0
        # 让窗口重画一次，否则要等下次交互才看得到效果
        user32 = ctypes.windll.user32
        user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0027)   # SWP_NOMOVE|NOSIZE|NOZORDER|NOACTIVATE|FRAMECHANGED
        return ok
    except Exception:
        return False                    # 老系统没有 dwmapi 也不该影响启动


def close_app_windows() -> int:
    """关掉所有「竹喧」窗口。

    退出时用 —— 用户点了退出键，就顺手把窗口也关了，省得再点一次 ×。
    走 `WM_CLOSE`，效果等同于用户自己点了窗口的关闭按钮，Edge 会正常收尾。
    """
    if not user32:
        return 0
    closed = 0
    for hwnd in _find_windows():
        try:
            user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
            closed += 1
        except Exception:
            pass
    return closed


def restore() -> dict:
    """切回原来的输入语言。"""
    if not user32:
        return {"ok": False, "reason": "只有 Windows 支持"}
    hwnds = _find_windows()
    if not hwnds:
        _saved.clear()
        return {"ok": False, "reason": "没找到竹喧窗口"}
    hwnd = hwnds[0]
    tid = user32.GetWindowThreadProcessId(hwnd, None)

    back = _saved.pop(tid, None)
    if not back:
        back = user32.LoadKeyboardLayoutW(ZH_CN, KLF_ACTIVATE)   # 没记录就切回中文
    if not back:
        return {"ok": False, "reason": "无法恢复键盘布局"}

    user32.PostMessageW(hwnd, WM_INPUTLANGCHANGEREQUEST, 0, back)
    time.sleep(0.06)
    after = user32.GetKeyboardLayout(tid)
    return {"ok": klid(after) == klid(back), "after": klid(after)}
