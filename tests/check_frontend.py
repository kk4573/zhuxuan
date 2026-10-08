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
                "studyBook", "libBook", "setAddBook", "importBook", "addBook",
                "newBookBtn", "newBookModal", "newBookName", "newBookOk",
                "newBookCancel", "bookModal", "bookList", "bookClose", "vocabSel", "vocabImport", "bookManageBtn",
             "lookBack"):
        check(f"关键元素 #{sel} 存在", sel in html_ids)


    # ---- CSS：同一个选择器被定义多次，后一条会悄悄覆盖前一条的冲突属性 ----
    # （用户反馈的「开关盖住文字」就是这么来的：.switch 写了两次，第二条把 display:flex 覆盖了）
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
    # 内容一多就顶出屏幕、上下两头都看不见（用户反馈过），所以这里盯着两条：
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

    # ---- 绝对定位的元素，父容器必须有定位 ----
    # 查词卡片的喇叭按钮用的是 position:absolute，挂在 <h2> 里；
    # 而 h2 没写 position:relative 时，它会跳过 h2 去找视口，直接飞出卡片（用户反馈过）。
    css3 = re.sub(r"/\*.*?\*/", "", (WEB / "style.css").read_text(encoding="utf-8"), flags=re.S)
    h2_rule = re.search(r"\.looktitle\s+h2\s*\{([^}]*)\}", css3)
    check(".looktitle h2 有定位（里面的喇叭才不会飞出去）",
          h2_rule is not None and "position:relative" in h2_rule.group(1).replace(" ", ""))

    spk_in_h2 = re.search(r"\.looktitle\s+h2\s+\.spk\s*\{([^}]*)\}", css3)
    check("查词卡片的喇叭用的是常规布局（不是 absolute）",
          spk_in_h2 is not None and "position:static" in spk_in_h2.group(1).replace(" ", ""))

    # 答题页那个喇叭仍然是绝对定位，但它的容器 .field 有定位 —— 两边都别改坏
    field_rule = re.search(r"\.field\{([^}]*)\}", css3)
    check("答题页 .field 仍然有定位（那边的喇叭也靠它）",
          field_rule is not None and "position:relative" in field_rule.group(1).replace(" ", ""))

    # ---- 检查更新 ----
    # 仓库里放 version.txt，程序启动时静默查一次；有新版就在顶栏下面提示一条。
    # 关键：查失败必须安静放过（断网/被墙都不能影响使用）。
    app_src_v = (ROOT / "app.py").read_text(encoding="utf-8")
    check("有版本号常量", "APP_VERSION" in app_src_v)
    check("有 /api/version 接口", '"/api/version"' in app_src_v)
    check("更新检查走 api.github.com（实测唯一稳定可达的域名）",
          "api.github.com" in app_src_v)
    check("更新检查放在后台线程（不拖慢启动）", "_check_update_bg" in app_src_v)

    base_v = (WEB / "js" / "base.js").read_text(encoding="utf-8")
    main_v = (WEB / "js" / "main.js").read_text(encoding="utf-8")
    check("前端有 checkUpdate()", "function checkUpdate" in base_v or "function checkUpdate" in main_v)
    check("checkUpdate 在启动时被调用", "checkUpdate" in main_v)
    check("查更新失败不打扰用户（整段在 try 里）",
          "catch" in base_v[base_v.find("function checkUpdate"):base_v.find("function checkUpdate") + 1500])
    index_v = (WEB / "index.html").read_text(encoding="utf-8")
    check("有更新提示条元素", 'id="updateBar"' in index_v)

    # ---- 下拉框样式不能丢 ----
    # 踩过：`#libBook,#lookBook{...}` 是共用规则，删 lookBook 时把整条删了，
    # 词库页那个下拉直接变成没样式的白方块。这里盯着：HTML 里的 select 都要有样式。
    html_src = (WEB / "index.html").read_text(encoding="utf-8")
    css_src = (WEB / "style.css").read_text(encoding="utf-8")

    def select_is_styled(tag, pos):
        """这个 <select> 有没有样式？三种方式都算：
           ① 自己的 id 选择器  ② 自己的 class  ③ 父级 class + select（如 .bookpick select）
        """
        sid = re.search(r'id="([^"]+)"', tag)
        if sid and re.search(r"#" + re.escape(sid.group(1)) + r"[\s,{:]", css_src):
            return True
        scls = re.search(r'class="([^"]+)"', tag)
        if scls:
            for cls in scls.group(1).split():
                if re.search(r"\." + re.escape(cls) + r"[\s,{:]", css_src):
                    return True
        # 父级：往这个标签前面找最近的一个 class="…"
        before = html_src[max(0, pos - 400):pos]
        parents = re.findall(r'class="([^"]+)"', before)
        if parents:
            for cls in parents[-1].split():
                if re.search(r"\." + re.escape(cls) + r"\s+select", css_src):
                    return True
        return False

    # 逐个盯着：任何 select 变成"没样式的白方块"都会被抓住
    for m in re.finditer(r"<select[^>]*>", html_src):
        tag = m.group(0)
        sid = re.search(r'id="([^"]+)"', tag)
        name = sid.group(1) if sid else tag[:40]
        check(f"select#{name} 有样式", select_is_styled(tag, m.start()), tag[:90])

    # ---- 查词页那个词库下拉挪到设置里了 ----
    # 它原来放在搜索栏旁边，看着像"搜索范围"，其实只管"加入词库时加到哪"，
    # 而那个按钮大多数时候根本不出现，所以那条下拉长期是摆设。现在统一进设置。
    index_src = (WEB / "index.html").read_text(encoding="utf-8")
    check("查词页不再有词库下拉", 'id="lookBook"' not in index_src)
    check("设置里有「加入词库时默认加到」", 'id="setAddBook"' in index_src)
    look_src2 = (WEB / "js" / "look.js").read_text(encoding="utf-8")
    check("查词页加词走默认词库", "defaultBookId()" in look_src2)
    settings_src = (WEB / "js" / "settings.js").read_text(encoding="utf-8")
    check("settings.js 里处理了那个下拉", "#setAddBook" in settings_src)
    check("设置里那个下拉会改默认词库", "/default" in settings_src)

    # ---- 加词 / 导入之后，界面上所有跟词量有关的地方都得刷 ----
    # 踩过两次：①"从例句加入词库后计数不变"（pop.js 只调了 loadWords）；
    #           ②"导入六级词表后顶栏和词库页还是空的"（books.js 漏了 loadStats 和 loadWords）。
    # 根因是每个入口各写各的刷新，总会漏。现在统一走 refreshAfterWordChange()。
    base_src = (WEB / "js" / "base.js").read_text(encoding="utf-8")
    check("有统一刷新入口 refreshAfterWordChange", "function refreshAfterWordChange" in base_src)

    for fn in ("pop.js", "look.js", "study.js", "lib.js"):
        src = (WEB / "js" / fn).read_text(encoding="utf-8")
        if "api('POST', '/api/words'" in src or "/api/words', {" in src:
            # 认两种：走统一入口，或者三样都刷到（少一样就会"要手动刷新才看得到"）
            unified = "refreshAfterWordChange" in src
            manual = all(k in src for k in ("loadStats", "loadWords", "refreshBookSelects"))
            check(f"{fn} 加词后会刷新界面", unified or manual,
                  "走统一入口" if unified else ("三样都刷" if manual else "漏了刷新"))

    # 导入词表这条路径也必须刷（用户反馈的就是这里）
    books_src = (WEB / "js" / "books.js").read_text(encoding="utf-8")
    imp = books_src[books_src.find("/api/vocab/import"):]
    check("导入词表后会刷新界面",
          "refreshAfterWordChange" in imp[:800] or
          all(k in imp[:800] for k in ("loadStats", "loadWords")),
          imp[:200])

    # ---- 查词页的返回按钮 ----
    # 返回目标是"上一个看过的东西"，不一定是个页面：
    # 在查词页里又点了一个词，返回该回到**上一个词**，而不是词库页。
    look = (WEB / "js" / "look.js").read_text(encoding="utf-8")
    check("有统一的跳转入口 openLook", "async function openLook(" in look)
    check("返回键逻辑在 look.js 里", "function renderLookBack(" in look)
    check("按钮文案就是「← 返回」（不写死「返回词库」）",
          "textContent = '← 返回'" in look and "返回词库" not in look)
    check("返回目标支持「上一个词」", "type: 'word'" in look)
    check("返回用栈实现（嵌套跳转能一路退回去）", "lookStack.push(" in look)
    check("返回目标支持「上一个页面」", "type: 'view'" in look)

    # 自己在查词页查的词不该冒出返回键
    b2 = (WEB / "js" / "base.js").read_text(encoding="utf-8")
    check("顶栏切到别的页面时会清空返回栈", "S.lookStack = []" in b2)
    check("S 里声明了 lookStack", "lookStack:" in b2)

    # ---- hidden 属性必须压得住 CSS 的 display ----
    # hidden 靠 display:none 起作用，优先级很低；类里写了 display:inline-flex 就会盖掉它。
    # 用户反馈过"自己查词也显示返回键、点了没反应"，根因就是这个。加一条兜底规则。
    css4 = re.sub(r"/\*.*?\*/", "", (WEB / "style.css").read_text(encoding="utf-8"), flags=re.S)
    # 注意正则要卡开头：CSS 里本来就有一条 .phase[hidden]{display:none}，
    # 不卡开头的话会匹配到它，断言就永远成立了（假绿过）。
    check("CSS 里有 [hidden] 兜底规则",
          re.search(r"(?:^|\n)\s*\[hidden\]\s*\{\s*display\s*:\s*none", css4) is not None,
          "缺了它，任何带 display 的类都能把 hidden 盖掉")

    # 所有用 hidden 切换显示的元素都不该在 CSS 里被 display 覆盖到（兜底规则除外）
    html4 = (WEB / "index.html").read_text(encoding="utf-8")
    hidden_ids = set(re.findall(r'id="(\w+)"[^>]*\shidden', html4))
    risky = []
    for hid in hidden_ids:
        for m in re.finditer(r"([^{}]*#" + hid + r"[^{}]*)\{([^}]*)\}", css4):
            body = m.group(2)
            if re.search(r"display\s*:\s*(?!none)", body):
                risky.append(f"#{hid} ← {m.group(1).strip()[:40]}")
    check("用 hidden 的元素没被 display 覆盖", not risky, risky[:4])
    print(f"\n结果：{OK} 通过 / {FAIL} 失败")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
