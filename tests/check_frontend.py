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
DYNAMIC_IDS = {"againBtn", "toLibBtn", "otherAddBtn"}
# 通过字符串参数引用、不走 $('#x') 的 id
STRING_REF_IDS = {"editMsg", "importMsg", "settingsMsg"}

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
                "importText", "xlsxInput", "wordBody", "autoTrack", "imeWarn", "listFoot", "listHead", "searchClear", "goTop", "otherWord",
                "editOk", "editEn", "search", "sort", "sizeInput", "endBtn",
                "confirmModal", "confirmOk", "confirmCancel", "enrichBtn",
                "prevBtn", "prevModal", "prevBody", "prevOlder", "prevClose", "prevCursor",
                "retypeWrap", "retypeInput", "retypeMsg",
                "settingsBtn", "settingsModal", "settingsOk", "settingsCancel",
                "setIme", "setKey", "setAccent", "setDecay", "cfgPath"):
        check(f"关键元素 #{sel} 存在", sel in html_ids)

    print(f"\n结果：{OK} 通过 / {FAIL} 失败")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
