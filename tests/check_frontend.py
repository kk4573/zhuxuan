"""竹喧 · 前端静态自检

检查那些「只有运行时才会炸」的低级错误：
  · web/js/*.js 里引用的元素 id，HTML 里是否真的存在（拼错一个字母，点击就报 null）
  · HTML 里的 id 是否都被用上（顺手找出笔误残留）
  · web/js/*.js 调用的 API 路径，后端是否真的实现了（抓路径拼写错误）
  · HTML 引用的静态资源文件是否都在

    .venv/Scripts/python.exe tests/check_frontend.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"

# JS 运行时才生成的元素（弹层里点出来的按钮），HTML 里本来就没有
DYNAMIC_IDS = {"againBtn", "toLibBtn", "otherAddBtn", "lookSpk", "lookAddBtn", "lookRefresh", "qSent"}
# 通过字符串参数引用、不走 $('#x') 的 id
STRING_REF_IDS = {"editMsg", "importMsg", "settingsMsg", "bookMsg", "newBookMsg"}

OK = 0
FAIL = 0


def check(label: str, cond: bool, extra="") -> None:
    global OK, FAIL
    if cond:
        OK += 1
        print(f"  [ok]    {label}")
    else:
        FAIL += 1
        print(f"  [FAIL]  {label}   {extra}")


def norm_path(p: str) -> str:
    """把路由和前端调用都归一化成可比较的形式。"""
    p = p.split("?")[0].split("#")[0].rstrip("/")
    p = re.sub(r"\{[^}]+\}", "", p)          # /api/words/{wid} → /api/words/
    return p.rstrip("/")


def main() -> int:
    html = (WEB / "index.html").read_text(encoding="utf-8")
    js_files = sorted((WEB / "js").glob("*.js"))
    js = "\n".join(f.read_text(encoding="utf-8") for f in js_files)
    py = (ROOT / "app.py").read_text(encoding="utf-8")

    html_ids = set(re.findall(r'id="([^"]+)"', html))
    js_ids = set(re.findall(r"""\$\('#([A-Za-z0-9_-]+)'\)""", js))

    missing = sorted(js_ids - html_ids - DYNAMIC_IDS)
    check("JS 引用的 id 在 HTML 里都存在", not missing, missing)

    unused = sorted(html_ids - js_ids - DYNAMIC_IDS - STRING_REF_IDS)
    check("HTML 里的 id 都被用上了（无笔误残留）", not unused, unused)

    # 每个标签(data-view)都要有对应的页面容器，否则点进去是一片空白
    views = set(re.findall(r'data-view="([^"]+)"', html))
    sections = set(re.findall(r'id="view-([^"]+)"', html))
    check(f"每个标签都有对应页面（{'/'.join(sorted(views))}）",
          views <= sections, sorted(views - sections))
    check("每个页面都有标签可以进入",
          sections <= views, sorted(sections - views))

    # 静态资源（注意 /js/base.js 这种以 / 开头的是站点根路径，不是绝对文件路径）
    for src in re.findall(r'(?:src|href)="([^"]+)"', html):
        if src.startswith(("http", "//", "#", "data:")):
            continue
        check(f"静态资源存在：{src}", (WEB / src.lstrip("/")).exists())

    # js/ 下的每个文件都要被 HTML 引用，否则就是搬完忘了接线
    referenced = set(re.findall(r'src="/js/([^"]+)"', html))
    on_disk = {f.name for f in js_files}
    check("js/ 下没有「写了却没被加载」的文件",
          not (on_disk - referenced), sorted(on_disk - referenced))
    check("HTML 引用到的 js 文件都在磁盘上",
          not (referenced - on_disk), sorted(referenced - on_disk))

    # 前端调用的 API vs 后端实现
    routes = set()
    for m in re.finditer(r'@app\.(get|post|put|delete)\("([^"]+)"', py):
        routes.add((m.group(1).upper(), norm_path(m.group(2))))
    calls = set()
    for m in re.finditer(r"""api\(\s*'(GET|POST|PUT|DELETE)'\s*,\s*'([^']+)'""", js):
        calls.add((m.group(1), norm_path(m.group(2))))
    for m in re.finditer(r"""fetch\('([^']+)'""", js):
        calls.add(("POST", norm_path(m.group(1))))

    check(f"前端共调用 {len(calls)} 个接口", len(calls) > 0)
    unknown = sorted(calls - routes)
    check("前端调用的接口后端都实现了", not unknown, unknown)

    # 关键交互元素
    for sel in ("qInput", "qCn", "qFb", "qSpk", "startBtn", "importOk",
                "importText", "importFile", "wordBody", "autoTrack", "imeWarn", "listFoot", "listHead", "searchClear", "goTop", "otherWord",
                "editOk", "editEn", "search", "sort", "sizeInput", "endBtn",
                "confirmModal", "confirmOk", "confirmCancel", "enrichBtn",
                "prevBtn", "prevModal", "prevBody", "prevOlder", "prevClose", "prevCursor",
                "retypeWrap", "retypeInput", "retypeMsg",
                "settingsBtn", "settingsModal", "settingsOk", "settingsCancel",
                "setIme", "setKey", "setAccent", "setDecay", "cfgPath",
                "lookInput", "lookBtn", "lookClear", "lookResult", "lookHint",
                "clearCache", "cacheCount",
                "studyBook", "libBook", "lookBook", "importBook", "addBook",
                "newBookBtn", "newBookModal", "newBookName", "newBookOk",
                "newBookCancel", "bookModal", "bookList", "bookClose", "vocabSel", "vocabImport", "bookManageBtn"):
        check(f"关键元素 #{sel} 存在", sel in html_ids)


    # ---- CSS：同一个选择器被定义多次，后一条会悄悄覆盖前一条的冲突属性 ----
    # （kk 报的「开关盖住文字」就是这么来的：.switch 写了两次，第二条把 display:flex 覆盖了）
    css = (WEB / "style.css").read_text(encoding="utf-8")
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)          # 去注释，免得注释里的例子被算进去
    rules: dict[str, list[list[str]]] = {}
    for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        sel = " ".join(sel.split())
        for part in sel.split(","):
            part = part.strip()
            if not part or part.startswith("@"):          # @media 之类的跳过
                continue
            props = [d.split(":")[0].strip().lower() for d in body.split(";") if ":" in d]
            rules.setdefault(part, []).append(props)
    dupes = []
    for sel, groups in rules.items():
        if len(groups) < 2:
            continue
        clash = set(groups[0]) & set(groups[1])
        # display / position / width 这类关键属性撞车才是真问题
        if clash & {"display", "position", "width", "height", "flex"}:
            dupes.append(f"{sel} → 冲突属性 {sorted(clash)}")
    check("CSS 里没有会互相覆盖的关键选择器", not dupes, dupes[:4])


    # ---- 弹层必须限高且能滚 ----
    # 内容一多就顶出屏幕、上下两头都看不见（kk 报过），所以这里盯着两条：
    # ① .modalbox 有 max-height ② 有 overflow-y:auto
    css_all = (WEB / "style.css").read_text(encoding="utf-8")
    css_all = re.sub(r"/\*.*?\*/", "", css_all, flags=re.S)
    box_rules = re.findall(r"\.modalbox[^{,]*\{([^}]*)\}", css_all)
    box_css = " ".join(box_rules).replace(" ", "")
    check("弹层限高：.modalbox 有 max-height", "max-height:" in box_css)
    check("弹层可滚：.modalbox 有 overflow-y", "overflow-y:auto" in box_css)
    check("底部按钮吸底：.modalact 有 sticky", re.search(
        r"\.modalbox\s+\.modalact[^{]*\{[^}]*position:sticky", css_all) is not None)
    check("滚动条看得见：定义了 ::-webkit-scrollbar", "::-webkit-scrollbar" in css_all)

    # ---- 窗口尺寸不能再写死 ----
    app_src = (ROOT / "app.py").read_text(encoding="utf-8")
    check("窗口尺寸按屏幕算，没写死", "--window-size=%d,%d" in app_src and "_window_size" in app_src)
    print(f"\n结果：{OK} 通过 / {FAIL} 失败")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
