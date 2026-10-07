# -*- coding: utf-8 -*-
"""临时原型：用 wxPython 的原生控件复刻竹喧的「背诵」准备页。

用途：让用户直观对比"原生控件界面"和"网页界面"的观感差别，再决定要不要走这条路。
跑法：.venv/Scripts/python.exe tests/proto_wxpython.py

这个原型**只画界面、不接后端**，目的是看观感，不是看功能。
"""
import wx

# 竹喧现在用的配色（深色主题）
BG = wx.Colour(15, 17, 23)        # 主背景 #0f1117
CARD = wx.Colour(26, 30, 38)      # 卡片
FG = wx.Colour(228, 231, 236)     # 主文字
DIM = wx.Colour(138, 146, 160)    # 次要文字
ACCENT = wx.Colour(58, 122, 216)  # 主色（那个蓝色按钮）

# ⚠️ wx 的字符串/字体对象必须在 wx.App() 创建之后才能构造（PyNoAppError），
# 所以这些放到 init_fonts() 里，由 main() 在 App 建好后调用。
FIG = FIG_B = BIG = None


def init_fonts():
    global FIG, FIG_B, BIG
    FIG = wx.Font(11, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL)
    FIG_B = wx.Font(12, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD)
    BIG = wx.Font(15, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD)


class Proto(wx.Frame):
    def __init__(self):
        super().__init__(None, title="竹喧（原生控件版原型）", size=(1060, 720))
        self.SetBackgroundColour(BG)

        # ① 尽量开启系统深色模式（wx 4.2+ 的接口；老版本会安静失败）
        try:
            self.MSWEnableDarkMode(True)
        except Exception:
            pass

        root = wx.BoxSizer(wx.VERTICAL)
        root.Add(self._topbar(), 0, wx.EXPAND)
        root.Add(self._body(), 1, wx.EXPAND)
        root.Add(self._hud(), 0, wx.EXPAND)
        self.SetSizer(root)
        self.Centre()

    # ---------------- 顶栏 ----------------
    def _topbar(self):
        p = wx.Panel(self)
        p.SetBackgroundColour(wx.Colour(20, 23, 30))
        s = wx.BoxSizer(wx.HORIZONTAL)

        logo = wx.StaticText(p, label="竹喧")
        logo.SetForegroundColour(FG)
        logo.SetFont(BIG)
        s.Add(logo, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 18)

        s.AddSpacer(24)
        # 标签：wx 没有"文字标签"，只能用按钮（这是关键差异之一：原生按钮有边框和底色）
        tabs = [("背诵", True), ("词库", False), ("查词", False)]
        for name, active in tabs:
            b = wx.Button(p, label=name, size=(78, 34), style=wx.BORDER_NONE)
            b.SetBackgroundColour(ACCENT if active else wx.Colour(20, 23, 30))
            b.SetForegroundColour(wx.Colour(255, 255, 255) if active else DIM)
            s.Add(b, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)

        s.AddStretchSpacer()

        cnt = wx.StaticText(p, label="词库 2332")
        cnt.SetForegroundColour(FG)
        cnt.SetFont(FIG)
        s.Add(cnt, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 16)

        for icon in ("⚙", "⏻"):
            b = wx.Button(p, label=icon, size=(36, 32), style=wx.BORDER_NONE)
            b.SetBackgroundColour(wx.Colour(20, 23, 30))
            b.SetForegroundColour(DIM)
            s.Add(b, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)

        p.SetSizer(s)
        return p

    # ---------------- 中间主体 ----------------
    def _body(self):
        p = wx.Panel(self)
        p.SetBackgroundColour(BG)
        outer = wx.BoxSizer(wx.VERTICAL)

        # 词库
        outer.AddSpacer(60)
        h1 = wx.StaticText(p, label="词库")
        h1.SetForegroundColour(DIM)
        h1.SetFont(FIG)
        outer.Add(h1, 0, wx.ALIGN_CENTER_HORIZONTAL)

        outer.AddSpacer(10)
        book = wx.Choice(p, choices=["我的词库 (215)", "六级 (2220)"], size=(300, 40))
        book.SetSelection(0)
        outer.Add(book, 0, wx.ALIGN_CENTER_HORIZONTAL)

        # 数量
        outer.AddSpacer(30)
        h2 = wx.StaticText(p, label="数量")
        h2.SetForegroundColour(DIM)
        h2.SetFont(FIG)
        outer.Add(h2, 0, wx.ALIGN_CENTER_HORIZONTAL)

        outer.AddSpacer(10)
        row = wx.BoxSizer(wx.HORIZONTAL)
        for lbl, w in (("−10", 56), ("−5", 52), ("−", 40)):
            b = wx.Button(p, label=lbl, size=(w, 38))
            b.SetForegroundColour(wx.Colour(30, 30, 30))
            row.Add(b, 0, wx.RIGHT, 6)
        num = wx.SpinCtrl(p, min=1, max=999, initial=20, size=(110, 38))
        row.Add(num, 0, wx.RIGHT, 6)
        for lbl, w in (("+", 40), ("+5", 52), ("+10", 56)):
            b = wx.Button(p, label=lbl, size=(w, 38))
            b.SetForegroundColour(wx.Colour(30, 30, 30))
            row.Add(b, 0, wx.RIGHT, 6)
        outer.Add(row, 0, wx.ALIGN_CENTER_HORIZONTAL)

        # 开始
        outer.AddSpacer(40)
        start = wx.Button(p, label="开 始", size=(220, 52))
        start.SetBackgroundColour(ACCENT)
        start.SetForegroundColour(wx.Colour(255, 255, 255))
        start.SetFont(wx.Font(13, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        outer.Add(start, 0, wx.ALIGN_CENTER_HORIZONTAL)

        outer.AddSpacer(26)
        hint = wx.StaticText(p, label="词库共 2332 个单词　·　已精通 1　·　学习中 198　·　未练习 2133")
        hint.SetForegroundColour(DIM)
        hint.SetFont(FIG)
        outer.Add(hint, 0, wx.ALIGN_CENTER_HORIZONTAL)

        p.SetSizer(outer)
        return p

    def _hud(self):
        p = wx.Panel(self)
        p.SetBackgroundColour(wx.Colour(20, 23, 30))
        s = wx.BoxSizer(wx.HORIZONTAL)
        t = wx.StaticText(p, label="  这是原生控件版的两个关键问题："
                                  "① 深色主题下按钮/下拉仍是系统浅色（Windows 的限制）；"
                                  "② 界面元素全部要手写，等于把现在的 8 个 js 文件重写一遍。")
        t.SetForegroundColour(DIM)
        t.SetFont(wx.Font(9, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        s.Add(t, 1, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 10)
        p.SetSizer(s)
        return p


def main():
    app = wx.App()
    # 请求系统按深色画原生控件。第一次我写成了 wx.App.Appearance(isDark=True)，
    # 那是错的 —— Appearance 是个枚举，正确用法是 .Dark / .Light / .System。
    try:
        res = app.SetAppearance(wx.App.Appearance.Dark)
        print("SetAppearance(Dark) ->", res)
    except Exception as e:
        print("SetAppearance(Dark) 失败:", e)
        try:
            res2 = app.SetAppearance(wx.App.DarkMode_Always)
            print("改用 DarkMode_Always ->", res2)
        except Exception as e2:
            print("DarkMode_Always 也失败:", e2)
    init_fonts()
    f = Proto()
    f.Show()
    app.MainLoop()


if __name__ == "__main__":
    main()
