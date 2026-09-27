"""竹喧 · Windows 输入法切换能力实测

Chromium 系（Edge / Electron）**不暴露老的 IMM32 输入法上下文**（ImmGetContext 返回 NULL），
所以「把输入法设成英文模式」那条路走不通，只能走「切换键盘布局」（WM_INPUTLANGCHANGEREQUEST）。

这个脚本用一个**自建的小窗口**实测这条消息到底管不管用 —— 不碰你正在用的任何程序。
（窗口会一闪而过，约 1 秒。）

    .venv/Scripts/python.exe tests/probe_ime.py
"""
from __future__ import annotations

import ctypes
import time
import tkinter as tk
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
imm32 = ctypes.WinDLL("imm32", use_last_error=True)

WM_INPUTLANGCHANGEREQUEST = 0x0050
KLF_ACTIVATE = 0x00000001
ZH_CN = "00000804"      # 中文（简体）- 美式键盘
EN_US = "00000409"      # 英语（美国）

user32.LoadKeyboardLayoutW.argtypes = [wintypes.LPCWSTR, wintypes.UINT]
user32.LoadKeyboardLayoutW.restype = wintypes.HANDLE
user32.GetKeyboardLayout.argtypes = [wintypes.DWORD]
user32.GetKeyboardLayout.restype = wintypes.HANDLE
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostMessageW.restype = wintypes.BOOL
user32.ActivateKeyboardLayout.argtypes = [wintypes.HANDLE, wintypes.UINT]
user32.ActivateKeyboardLayout.restype = wintypes.HANDLE

imm32.ImmGetContext.argtypes = [wintypes.HWND]
imm32.ImmGetContext.restype = wintypes.HANDLE
imm32.ImmReleaseContext.argtypes = [wintypes.HWND, wintypes.HANDLE]


def klid_of(hkl: int) -> str:
    """把 HKL 转成 00000409 这种键盘布局 ID"""
    return f"{hkl & 0xFFFF:08X}" if hkl else "00000000"


def main() -> int:
    ok = 0
    fail = 0

    print("== 1. Edge / Chromium 是否暴露 IMM32 上下文 ==")
    print("   （已知结果是 NULL —— 所以只能走键盘布局切换）")

    print("\n== 2. 自建窗口实测键盘布局切换 ==")
    root = tk.Tk()
    root.title("竹喧 · 输入法探测")
    root.geometry("360x90+40+40")
    tk.Label(root, text="测试窗口（马上自动关闭）", font=("Microsoft YaHei", 11)).pack(expand=True)
    root.update()
    time.sleep(0.3)
    root.update()

    hwnd = root.winfo_id()
    tid = user32.GetWindowThreadProcessId(hwnd, None)
    print(f"   测试窗口 hwnd={hwnd:#x}  线程={tid}")

    before = user32.GetKeyboardLayout(tid)
    print(f"   切换前线程键盘布局：{klid_of(before)}")

    en = user32.LoadKeyboardLayoutW(EN_US, KLF_ACTIVATE)
    print(f"   加载英语（美国）布局：{'成功' if en else '失败'}  HKL={en:#x}")

    if en:
        user32.PostMessageW(hwnd, WM_INPUTLANGCHANGEREQUEST, 0, en)
        for _ in range(10):
            root.update()
            time.sleep(0.08)
        after = user32.GetKeyboardLayout(tid)
        print(f"   切换后线程键盘布局：{klid_of(after)}")
        if klid_of(after) == EN_US:
            ok += 1
            print("   ✓ 切换成功 —— WM_INPUTLANGCHANGEREQUEST 管用")
        else:
            fail += 1
            print("   ✗ 没切过去，PostMessage 这条路不通")

        # 还原
        if before:
            user32.PostMessageW(hwnd, WM_INPUTLANGCHANGEREQUEST, 0, before)
            for _ in range(8):
                root.update()
                time.sleep(0.06)
            back = user32.GetKeyboardLayout(tid)
            print(f"   还原后线程键盘布局：{klid_of(back)}  "
                  f"{'✓ 还原成功' if klid_of(back) == klid_of(before) else '✗ 还原失败'}")

    print("\n== 3. ActivateKeyboardLayout（同线程直接切，备选方案） ==")
    if en:
        old = user32.ActivateKeyboardLayout(en, 0)
        now = user32.GetKeyboardLayout(tid)
        print(f"   ActivateKeyboardLayout → {klid_of(now)}  "
              f"{'✓ 可用' if klid_of(now) == EN_US else '✗ 无效'}")
        if old:
            user32.ActivateKeyboardLayout(old, 0)

    root.destroy()

    print(f"\n结论：{'键盘布局切换方案可用，可以据此实现' if ok else '这条路不通，得改用别的办法（例如提示用户手动切）'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
