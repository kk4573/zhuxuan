"""竹喧 · 启动入口与 API

直接运行（正式用法，会自动弹出独立窗口）：
    .venv/Scripts/python.exe app.py

调试模式（改代码自动重载，自己用浏览器开 http://127.0.0.1:8765/）：
    .venv/Scripts/python.exe -m uvicorn app:app --reload --port 8765
"""
from __future__ import annotations

import io
import json
import os
import re
import random
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, Response, UploadFile
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from core import config, db, dictionary, ime, judge, srs, vocab
from core.paths import BASE_DIR, DATA_DIR, RES_DIR

WEB_DIR = RES_DIR / "web"
HOST = "127.0.0.1"
DEFAULT_PORT = 8765
APP_NAME = "竹喧"
APP_VERSION = "1.1.1"          # 发新版时改这里，同时更新仓库里的 version.txt

# 能开 --app 独立窗口的浏览器（Chromium 系都支持这个参数）。
# 按优先级排：Edge 是 Windows 自带的，最先试；其余是用户可能自己装的。
# 注意 Firefox 不支持 --app，所以不在列表里 —— 它会被"默认浏览器"那条兜底接住。
BROWSER_CANDIDATES = (
    ("Edge", (
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    )),
    ("Chrome", (
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    )),
    ("Brave", (
        r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
        r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe",
    )),
    ("Vivaldi", (
        r"C:\Program Files\Vivaldi\Application\vivaldi.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Vivaldi\Application\vivaldi.exe"),
    )),
    ("Opera", (
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Opera\opera.exe"),
        r"C:\Program Files\Opera\opera.exe",
    )),
    ("360 极速浏览器", (
        r"C:\Program Files (x86)\360\360Chrome\Chrome\Application\360chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\360Chrome\Chrome\Application\360chrome.exe"),
    )),
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init()
    db.backup()
    yield


app = FastAPI(title=APP_NAME, lifespan=lifespan)


# ============================================================ 版本 / 更新检查

# 仓库地址（检查更新用）。走 api.github.com —— 实测国内只有这个域名稳定可达，
# github.com 网页和 raw.githubusercontent.com 都会超时。
UPDATE_REPO = "kk4573/zhuxuan"
_UPDATE_CACHE: dict = {"checked": False, "latest": None, "error": None}


def _version_tuple(v: str) -> tuple:
    """把 "1.2.3" 变成 (1, 2, 3)，方便比较大小。非数字的部分忽略。"""
    parts = []
    for seg in str(v or "").strip().split("."):
        num = "".join(ch for ch in seg if ch.isdigit())
        parts.append(int(num) if num else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def _fetch_latest_version() -> str | None:
    """从仓库里取 version.txt。失败返回 None（不抛异常）。"""
    import base64
    url = f"https://api.github.com/repos/{UPDATE_REPO}/contents/version.txt"
    req = urllib.request.Request(url, headers={
        "User-Agent": "zhuxuan-update-check",
        "Accept": "application/vnd.github+json",
    })
    with urllib.request.urlopen(req, timeout=8) as resp:
        data = json.loads(resp.read().decode("utf-8", "ignore"))
    content = data.get("content")
    if not content:
        return None
    text = base64.b64decode(content).decode("utf-8", "ignore").strip()
    return text.split()[0] if text else None


def _check_update_bg() -> None:
    """后台查一次有没有新版本。查不到就安静放过 —— 这只是个便利功能，
    断网、被墙、GitHub 挂了都不该影响正常使用。"""
    try:
        latest = _fetch_latest_version()
        _UPDATE_CACHE["latest"] = latest
    except Exception as exc:
        _UPDATE_CACHE["error"] = str(exc)[:120]
    finally:
        _UPDATE_CACHE["checked"] = True


@app.get("/api/version")
def api_version():
    """当前版本，以及（如果查到了）有没有更新。"""
    latest = _UPDATE_CACHE.get("latest")
    return {
        "current": APP_VERSION,
        "latest": latest,
        "has_update": bool(latest) and _version_tuple(latest) > _version_tuple(APP_VERSION),
        "checked": _UPDATE_CACHE.get("checked", False),
        "error": _UPDATE_CACHE.get("error"),
    }


# ============================================================ 统计

@app.get("/api/stats")
def api_stats():
    return db.stats()


@app.get("/api/stats/daily")
def api_stats_daily(days: int = 30):
    return {"items": db.daily(days)}


# ============================================================ 词库

class WordIn(BaseModel):
    en: str
    cn: str = ""
    pos: str = ""
    ph: str = ""
    note: str = ""
    book_id: int | None = None      # 加到哪个词库（不传就用默认词库）


# ============================================================ 词库（多个）

class BookIn(BaseModel):
    name: str = ""
    builtin: str = ""


@app.get("/api/books")
def api_books():
    """所有词库（默认的排最前），带各自的单词数。"""
    return {"items": db.list_books(), "default_id": (db.default_book() or {}).get("id")}


@app.post("/api/books")
def api_book_add(b: BookIn):
    name = (b.name or "").strip()
    if not name:
        raise HTTPException(400, "词库名称不能为空")
    if len(name) > 24:
        raise HTTPException(400, "词库名称太长了（24 字以内）")
    try:
        bid = db.add_book(name, builtin=b.builtin or "")
    except Exception:
        raise HTTPException(409, f"已经有叫「{name}」的词库了")
    return {"id": bid, "items": db.list_books()}


@app.put("/api/books/{bid}")
def api_book_rename(bid: int, b: BookIn):
    if not db.get_book(bid):
        raise HTTPException(404, "词库不存在")
    name = (b.name or "").strip()
    if not name:
        raise HTTPException(400, "词库名称不能为空")
    try:
        db.rename_book(bid, name)
    except Exception:
        raise HTTPException(409, f"已经有叫「{name}」的词库了")
    return {"ok": True, "items": db.list_books()}


@app.delete("/api/books/{bid}")
def api_book_delete(bid: int):
    """删词库：只删归属关系，**单词本身和其它词库都不受影响**。"""
    if not db.get_book(bid):
        raise HTTPException(404, "词库不存在")
    try:
        n = db.delete_book(bid)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"removed": n, "items": db.list_books()}


@app.post("/api/books/{bid}/default")
def api_book_set_default(bid: int):
    if not db.get_book(bid):
        raise HTTPException(404, "词库不存在")
    db.set_default_book(bid)
    return {"ok": True, "items": db.list_books()}


class BookWordIn(BaseModel):
    word_id: int
    book_id: int | None = None


@app.post("/api/books/attach")
def api_book_attach(p: BookWordIn):
    """把已有的单词加进某个词库（**不新建单词**，掌握度沿用）。"""
    target = p.book_id or (db.default_book() or {}).get("id")
    if not target or not db.get_book(target):
        raise HTTPException(404, "词库不存在")
    if not db.get_word(p.word_id):
        raise HTTPException(404, "单词不存在")
    added = db.attach_word(target, p.word_id)
    return {"added": added, "book_id": target, "books": db.book_of_word(p.word_id)}


@app.post("/api/books/detach")
def api_book_detach(p: BookWordIn):
    """把单词从某个词库移出（不删单词）。"""
    if not p.book_id:
        raise HTTPException(400, "要指定词库")
    removed = db.detach_word(p.book_id, p.word_id)
    return {"removed": removed, "books": db.book_of_word(p.word_id)}


@app.get("/api/words/{wid}/books")
def api_word_books(wid: int):
    """这个词属于哪几个词库。"""
    return {"items": db.book_of_word(wid)}


# ============================================================ 内置词表

@app.get("/api/vocab")
def api_vocab():
    """有哪些内置词表可选（四级 / 六级 / 考研 / 托福 / GRE）。"""
    return {"items": vocab.list_all()}


class VocabImportIn(BaseModel):
    key: str
    as_book: bool = True          # True：新建一个同名词库；False：导入到 book_id 指定的词库
    book_id: int | None = None


@app.post("/api/vocab/import")
def api_vocab_import(p: VocabImportIn):
    """导入内置词表。

    **不会默认导入** —— 要点进来、选一个词表、再确认。
    已经在词库里的词（比如你自己的 abandon）不会重复建，只加一条归属关系。
    """
    info = vocab.info(p.key)
    if not info:
        raise HTTPException(404, f"没有这个词表：{p.key}")

    try:
        path = vocab.fetch(p.key)
    except Exception as exc:
        raise HTTPException(502, f"下载词表失败：{exc}")

    try:
        items = vocab.parse(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception as exc:
        raise HTTPException(500, f"解析词表失败：{exc}")
    if not items:
        raise HTTPException(500, "词表里没解析出任何词条")

    # 目标词库
    if p.as_book:
        name = info["name"]
        existing = next((b for b in db.list_books() if b["name"] == name), None)
        if existing:
            target = existing["id"]
        else:
            target = db.add_book(name, builtin=info["key"])
    else:
        target = p.book_id or (db.default_book() or {}).get("id")
        if not target or not db.get_book(target):
            raise HTTPException(400, "要指定一个词库")

    stats = db.import_words(items, target)
    stats["book_id"] = target
    stats["book_name"] = (db.get_book(target) or {}).get("name", "")
    return stats


@app.get("/api/words")
def api_words(q: str = "", sort: str = "created", page: int = 1, size: int = 200,
              book_id: int | None = None):
    rows, total = db.list_words(q, sort, page, size, book_id=book_id)
    return {"total": total, "page": page, "size": size, "items": rows}


@app.post("/api/words")
def api_add(w: WordIn):
    en = w.en.strip()
    if not en:
        raise HTTPException(400, "英文不能为空")
    target = w.book_id or (db.default_book() or {}).get("id")
    existing = db.find_word(en)
    if existing:
        # 词已经存在：不重复建，只把它加进目标词库（掌握度沿用）
        if target:
            db.attach_word(target, existing["id"])
        return {"id": existing["id"], "existing": True, "book_id": target}
    wid = db.add_word(en, w.cn, w.pos, w.ph, w.note, book_id=target)
    if wid is None:
        raise HTTPException(500, "写入失败")
    return {"id": wid}


@app.put("/api/words/{wid}")
def api_update(wid: int, w: WordIn):
    if not db.get_word(wid):
        raise HTTPException(404, "单词不存在")
    db.update_word(wid, en=w.en.strip(), cn=w.cn, pos=w.pos, ph=w.ph, note=w.note)
    return {"ok": True}


@app.delete("/api/words/{wid}")
def api_delete(wid: int):
    if not db.delete_word(wid):
        raise HTTPException(404, "单词不存在")
    return {"ok": True}


# ============================================================ 导入

HEADER_WORDS = {
    "word", "words", "english", "vocabulary", "单词", "英文", "词汇", "英语", "释义", "中文",
}


def _split_line(line: str) -> tuple[str, str, str] | None:
    line = line.rstrip("\r\n")
    if not line.strip():
        return None
    parts = None
    for sep in ("\t", "|", "，", ",", ";"):
        if sep in line:
            parts = line.split(sep)
            break
    if parts is None:
        parts = [line]
    cells = [p.strip() for p in parts]
    en = cells[0] if cells else ""
    cn = cells[1] if len(cells) > 1 else ""
    pos = cells[2] if len(cells) > 2 else ""
    return en, cn, pos


def _is_header(en: str, cn: str) -> bool:
    """只在前几行判断，避免把真正的单词 word 当成表头。"""
    return en.strip().lower() in HEADER_WORDS


def _do_import(items: list[tuple[str, str, str]], book_id: int | None = None) -> dict:
    """把解析好的词写进库。

    已经在库里的词**不重复建、也不覆盖释义**，只把它挂进目标词库 ——
    这样导入一份词表和手动加词不会打架。
    """
    target = book_id or (db.default_book() or {}).get("id")
    added = skipped = 0
    new_words: list[str] = []
    for en, cn, pos in items:
        en = (en or "").strip()
        if not en:
            continue
        exist = db.find_word(en)
        if exist:
            if target:
                db.attach_word(target, exist["id"])
            skipped += 1
            continue
        wid = db.add_word(en, cn or "", pos or "", book_id=target)
        if wid:
            added += 1
            new_words.append(en)
        else:
            skipped += 1
    return {"added": added, "skipped": skipped, "new_words": new_words, "book_id": target}


class ImportIn(BaseModel):
    text: str
    book_id: int | None = None


@app.post("/api/words/import")
def api_import(payload: ImportIn):
    items = []
    for i, line in enumerate(payload.text.splitlines()):
        parsed = _split_line(line)
        if not parsed:
            continue
        if i < 3 and _is_header(parsed[0], parsed[1]):
            continue
        items.append(parsed)
    if not items:
        raise HTTPException(400, "没解析出任何单词，检查一下粘贴的内容")
    return _do_import(items, payload.book_id)


@app.post("/api/words/import-xlsx")
async def api_import_xlsx(file: UploadFile = File(...), book_id: int | None = Form(None)):
    try:
        import openpyxl
    except ImportError:
        raise HTTPException(500, "缺少 openpyxl，无法读取 Excel（请改用复制粘贴导入）")

    data = await file.read()
    try:
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:
        raise HTTPException(400, f"打不开这个 Excel 文件：{exc}")
    try:
        ws = wb.active
        items = []
        for idx, row in enumerate(ws.iter_rows(values_only=True)):
            cells = ["" if c is None else str(c).strip() for c in row[:3]]
            cells += [""] * (3 - len(cells))
            if not any(cells):
                continue
            if idx < 3 and _is_header(cells[0], cells[1]):
                continue
            items.append((cells[0], cells[1], cells[2]))
    finally:
        wb.close()
    if not items:
        raise HTTPException(400, "这个表格里没读到内容")
    return _do_import(items, book_id)


# ============================================================ 背诵会话

class StartIn(BaseModel):
    book_id: int | None = None      # 从哪个词库抽（不传就用默认词库）
    size: int = 20


@app.post("/api/session/start")
def api_start(p: StartIn):
    book = db.get_book(p.book_id) if p.book_id else db.default_book()
    if not book:
        raise HTTPException(400, "还没有可用的词库")
    pool = db.pick_pool(book["id"])
    if not pool:
        raise HTTPException(400, f"「{book['name']}」里还没有带中文释义的单词")
    if not pool:
        raise HTTPException(400, "词库里还没有带中文释义的单词，先导入单词再生成释义")
    n = max(1, min(int(p.size or 1), len(pool)))
    picked = srs.pick(pool, n, today_decay=config.clamp_decay(config.get("today_decay")))
    random.shuffle(picked)                     # 抽完再打乱出题顺序
    session_id = db.create_session(len(picked))
    return {"session_id": session_id, "count": len(picked), "items": picked}


class AnswerIn(BaseModel):
    session_id: int
    word_id: int
    typed: str = ""
    skipped: bool = False


@app.post("/api/session/answer")
def api_answer(a: AnswerIn):
    word = db.get_word(a.word_id)
    if not word:
        raise HTTPException(404, "单词不存在")

    if a.skipped:
        mastery, streak, delta = srs.apply_wrong(word)
        db.record_answer(a.word_id, "wrong", mastery, streak)
        db.log_answer(a.session_id, a.word_id, "skip", "")
        return {
            "correct": False, "skipped": True, "retried": True,
            "answer": word["en"], "ph": word["ph"],
            "mastery": mastery, "from": word["mastery"], "delta": delta, "diff": None,
        }

    res = judge.judge(a.typed, word["en"])
    retried = db.has_answered(a.session_id, a.word_id)   # 本轮之前答过这个词 = 这次是重考

    if res["correct"]:
        if retried:
            # 重考答对：**不加掌握度**（连对链也清零）。
            # 当场没想起来说明这个词还没真正掌握 —— 只有第一遍就答对才算掌握得好，
            # 否则一轮背下来所有词都涨到 1，掌握度就没有区分度了。
            mastery, streak, delta = word["mastery"], 0, 0
        else:
            mastery, streak, delta = srs.apply_right(word)
        result = "right"
    else:
        mastery, streak, delta = srs.apply_wrong(word)
        result = "wrong"
    db.record_answer(a.word_id, result, mastery, streak)
    db.log_answer(a.session_id, a.word_id, result, a.typed)

    return {
        "correct": res["correct"],
        "skipped": False,
        "retried": retried,
        "answer": word["en"],
        "ph": word["ph"],
        "mastery": mastery,
        "from": word["mastery"],
        "delta": delta,
        "diff": judge.mark_diff(a.typed, word["en"]),
    }


class FinishIn(BaseModel):
    session_id: int


@app.post("/api/session/finish")
def api_finish(p: FinishIn):
    db.finish_session(p.session_id)
    return {"ok": True}


# ============================================================ 词典 / 自动补全

class LookupIn(BaseModel):
    en: str
    force: bool = False          # 忽略本地缓存，强制重新查（用于刷新已有释义）


@app.post("/api/lookup")
def api_lookup(p: LookupIn):
    """查一个词的中文释义 + 音标（先本地缓存，再在线词典）。"""
    return dictionary.lookup(p.en, force=p.force)


class CheckWordIn(BaseModel):
    en: str = ""


@app.get("/api/word/mini")
def api_word_mini(w: str = ""):
    """例句里点某个单词：给它的最主要一条释义（顺带还原原型、带音标）。

    查不到就返回 ok=False，前端不弹框 —— 例句里有 the / of 这种虚词，
    点它们不该弹东西出来。
    """
    return dictionary.mini(w)


@app.get("/api/sentence")
def api_sentence(en: str = ""):
    """背单词提交后那张例句。先查本机缓存，没有再联网取一条。"""
    return dictionary.first_sentence(en)


@app.post("/api/check-word")
def api_check_word(p: CheckWordIn):
    """答题打错时，看看他打进去的那个是不是**一个真实存在的单词**。

    是的话，界面上会把它连同释义一起显示，并提供「一键加入词库」。
    只查不改：**不动掌握度、不写词库**。
    """
    en = (p.en or "").strip()
    # 只接受像英文单词 / 短语的输入（避免把乱敲的符号拿去查词典）
    if not en or len(en) > 60 or not re.match(r"^[A-Za-z][A-Za-z'’\- ]*$", en):
        return {"found": False}

    hit = dictionary.lookup(en)
    if not hit.get("ok"):
        return {"found": False}                      # 词典里也没这个词 → 不显示

    existing = db.find_word(en)
    return {
        "found": True,
        "en": en,
        "cn": hit.get("cn", ""),
        "pos": hit.get("pos", ""),
        "ph": hit.get("ph", ""),
        "source": hit.get("source", ""),
        "in_library": bool(existing),                # 已经在词库里就不给「加入」按钮
        "word_id": existing["id"] if existing else None,
    }


class FullLookupIn(BaseModel):
    en: str = ""
    force: bool = False        # 绕过缓存重新联网查


@app.post("/api/lookup/full")
def api_lookup_full(p: FullLookupIn):
    """查词页：一个词的完整信息。

    音标、释义、考纲标签、双语例句、短语搭配、同义词、词形变化，
    以及「更多」里的柯林斯星级释义 / 英英 / 词源 / 报刊例句 / 影视例句 / 网络释义。
    顺带告诉前端这个词在不在词库里、掌握度多少。
    """
    r = dictionary.lookup_full(p.en, force=p.force)
    if r.get("ok"):
        ex = db.find_word(r["en"])
        r["in_library"] = bool(ex)
        r["word_id"] = ex["id"] if ex else None
        r["mastery"] = ex["mastery"] if ex else None
    return r


class JudgeIn(BaseModel):
    answer: str
    typed: str


@app.post("/api/judge")
def api_judge(p: JudgeIn):
    """只判定对错，**不记分、不动掌握度** —— 给答错后的「跟着打一遍」用。

    这样判定规则仍然只有后端这一份（大小写、空格、英美变体都一致）。
    """
    return judge.judge(p.typed, p.answer)


class AutoAddIn(BaseModel):
    text: str = ""
    lookup: bool = True          # 中文留空时自动查词典
    book_id: int | None = None


@app.post("/api/words/auto-add")
def api_auto_add(p: AutoAddIn):
    """批量添加：一行一个英文就够了，中文自动查。

    每行也允许带中文（Tab / 逗号分隔），带了就用你给的、不查词典。
    """
    target = p.book_id or (db.default_book() or {}).get("id")
    added = skipped = 0
    failed: list[str] = []
    for idx, line in enumerate(p.text.splitlines()):
        parsed = _split_line(line)
        if not parsed:
            continue
        en, cn, pos = parsed
        if not en or (idx < 3 and _is_header(en, cn)):
            continue
        if db.find_word(en):
            skipped += 1
            continue
        ph = ""
        if not cn.strip() and p.lookup:
            info = dictionary.lookup(en)
            if info.get("ok"):
                cn = info.get("cn", "")
                pos = pos or info.get("pos", "")
                ph = info.get("ph", "")
            else:
                failed.append(en)
            time.sleep(0.05)          # 对词典礼貌一点，避免被限流
        if db.add_word(en, cn, pos, ph, book_id=target):
            added += 1
        else:
            skipped += 1
    return {"added": added, "skipped": skipped, "failed": failed,
            "no_cn": db.count_pending_cn(), "book_id": target}


class RefreshIn(BaseModel):
    page: int = 1
    size: int = 30
    book_id: int | None = None


@app.post("/api/words/refresh-cn")
def api_refresh_cn(p: RefreshIn):
    """按**当前的释义详细程度设置**重新生成一批释义（跳过缓存、强制重查）。

    释义是在导入/查词那一刻算好存进 words 表的，所以改了设置以后，
    已有单词的释义不会自己变 —— 得这样跑一遍。前端翻页循环调用，边跑边显示进度。
    """
    rows, total = db.list_words(page=p.page, size=p.size, book_id=p.book_id)
    done = 0
    failed: list[str] = []
    for w in rows:
        info = dictionary.lookup(w["en"], force=True)      # force：不吃旧缓存
        if info.get("ok") and info.get("cn"):
            db.update_word(w["id"], cn=info["cn"],
                           pos=(info.get("pos") or w["pos"]),
                           ph=(info.get("ph") or w["ph"]))
            done += 1
        else:
            failed.append(w["en"])
        time.sleep(0.05)
    return {"done": done, "failed": failed, "total": total, "size": p.size}


@app.post("/api/words/enrich")
def api_enrich(limit: int = 30):
    """给词库里缺中文释义的词补全。每次做一批，前端循环调用并显示进度。

    只处理「还没查过词典」的词；已经查过、词典里确实没有的会跳过，不反复重试。
    """
    rows = db.words_pending_cn(limit)
    filled = 0
    failed: list[str] = []
    for w in rows:
        info = dictionary.lookup(w["en"])
        if info.get("ok") and info.get("cn"):
            db.update_word(w["id"], cn=info["cn"],
                           pos=(info.get("pos") or w["pos"]),
                           ph=(info.get("ph") or w["ph"]))
            filled += 1
        else:
            failed.append(w["en"])
        time.sleep(0.05)
    return {"filled": filled, "failed": failed,
            "remain": db.count_pending_cn(), "done": len(rows)}


@app.get("/api/audio/{word}")
def api_audio(word: str, accent: str = "us"):
    """单词真人发音（MP3）。取不到就返回 404，前端自动回退到本机合成音。"""
    data = dictionary.fetch_audio(word, accent)
    if not data:
        raise HTTPException(404, "没有可用的音频")
    return Response(content=data, media_type="audio/mpeg",
                    headers={"Cache-Control": "public, max-age=604800"})


# ============================================================ 设置 / 输入法

@app.get("/api/config")
def api_config():
    """当前设置。密钥只回传「配没配」，内容不外传。"""
    return config.public_view()


class ConfigIn(BaseModel):
    force_english_ime: bool | None = None
    deepseek_api_key: str | None = None
    deepseek_model: str | None = None
    audio_accent: str | None = None
    today_decay: float | None = None      # 当天重复抑制强度（0~5）
    pos_limit: int | None = None          # 释义保留几个词性（0 = 全部）
    meaning_count: int | None = None      # 每个词性保留几个义项（1~3）


@app.put("/api/config")
def api_config_put(p: ConfigIn):
    before = config.public_view()
    out = config.save(p.model_dump())
    # 释义详细程度变了 → 缓存里的释义还是旧编排，清掉让它按新设置重新生成
    if (before.get("pos_limit") != out.get("pos_limit")
            or before.get("meaning_count") != out.get("meaning_count")):
        db.dict_clear_all()
        out["cn_style_changed"] = True
    return out


class ImeIn(BaseModel):
    on: bool


@app.post("/api/ime")
def api_ime(p: ImeIn):
    """答题开始 / 结束时切输入法。设置里关掉时什么都不做。"""
    if not config.get("force_english_ime"):
        return {"ok": False, "skipped": True, "reason": "设置里关掉了自动切换"}
    return ime.to_english() if p.on else ime.restore()


@app.get("/api/ime")
def api_ime_status():
    return {**ime.status(), "enabled": bool(config.get("force_english_ime"))}


@app.get("/api/cache")
def api_cache_info():
    """查词缓存有多少条（设置页显示用）。"""
    return {"count": db.dict_full_count()}


@app.delete("/api/cache")
def api_cache_clear():
    """清空查词缓存。只删 dict_full 这张表 —— 词库和学习记录不受影响。"""
    return {"removed": db.dict_full_clear()}


@app.post("/api/quit")
def api_quit():
    """退出竹喧：关窗口 + 停服务。

    内嵌窗口要程序化关掉它（destroy），否则窗口留着、服务也退不干净。
    """
    def _die() -> None:
        time.sleep(0.8)                      # 先把响应发回去
        if not _close_embedded_window():
            ime.close_app_windows()          # 浏览器窗口的情况：发 WM_CLOSE
        time.sleep(0.4)                      # 给窗口一点时间处理关闭
        os._exit(0)

    threading.Thread(target=_die, daemon=True).start()
    return {"ok": True}


# ============================================================ 静态页面

if WEB_DIR.exists():
    app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")


# ============================================================ 启动

def _port_free(port: int) -> bool:
    with socket.socket() as s:
        try:
            s.bind((HOST, port))
            return True
        except OSError:
            return False


def _pick_port(start: int = DEFAULT_PORT, tries: int = 30) -> int:
    for p in range(start, start + tries):
        if _port_free(p):
            return p
    raise RuntimeError("找不到可用端口")


def _find_browser() -> tuple[str, str] | None:
    """找一个能开独立窗口的浏览器，返回 (可执行文件路径, 名字)。

    顺序：① 已知安装位置（Edge 优先）→ ② 注册表里系统登记的浏览器。
    都不行就返回 None，由调用方退回到"用系统默认浏览器打开"。
    """
    # ① 已知路径
    for name, paths in BROWSER_CANDIDATES:
        for p in paths:
            if p and os.path.exists(p):
                return p, name

    # ② 注册表：系统登记过的浏览器（StartMenuInternet 是 Windows 的标准登记处）
    try:
        import winreg
        for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            key_path = r"SOFTWARE\Clients\StartMenuInternet"
            try:
                with winreg.OpenKey(root, key_path) as k:
                    n = winreg.QueryInfoKey(k)[0]
                    for i in range(n):
                        try:
                            sub = winreg.EnumKey(k, i)
                            with winreg.OpenKey(k, sub + r"\shell\open\command") as ck:
                                cmd = winreg.QueryValue(ck, None)
                            exe = cmd.strip().strip('"').split('"')[0] if cmd.startswith('"') \
                                else cmd.strip().split(" ")[0]
                            exe = os.path.expandvars(exe)
                            if exe and os.path.exists(exe) and exe.lower().endswith(".exe"):
                                return exe, sub
                        except OSError:
                            continue
            except OSError:
                continue
    except Exception:
        pass

    return None


def _wait_ready(url: str, timeout: float = 20.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=1)
            return True
        except Exception:
            time.sleep(0.15)
    return False


def _window_size() -> tuple[int, int]:
    """按屏幕大小挑一个合适的窗口尺寸。

    原来写死 1040×780 —— 小屏上可能比屏幕还大（最大化按钮都被顶出屏幕），
    大屏上又显得局促。这里取屏幕的七八成，再夹到合理区间。
    """
    try:
        import ctypes
        u = ctypes.windll.user32
        sw = u.GetSystemMetrics(0)          # 屏幕宽（逻辑像素）
        sh = u.GetSystemMetrics(1)          # 屏幕高
        if sw < 400 or sh < 400:            # 取不到就退回默认
            raise ValueError
    except Exception:
        return 1040, 780
    # 宽取 78%、高取 84%，并夹住上下限；再留点边，别贴着屏幕边缘
    w = max(900, min(1420, int(sw * 0.78)))
    h = max(620, min(980, int(sh * 0.84)))
    return w, h


# 当前内嵌窗口的引用（退出时要程序化关掉它）
_WEBVIEW_WINDOW = None


def _webview_available() -> bool:
    """内嵌窗口（WebView2）能不能用。"""
    try:
        import webview  # noqa: F401
    except Exception:
        return False
    # pywebview 在 Windows 上走 WebView2；运行时缺失要到真正启动时才报错，
    # 这里只能判断"库在不在"，失败由 _open_window_embedded 兜住。
    return True


def _open_window_embedded(url: str) -> bool:
    """把界面嵌进程序自己的窗口（WebView2）。成功返回 True。

    为什么用内嵌而不是开浏览器窗口（原来的做法）：
      · 内嵌用的 WebView2 是 Windows 的**系统组件**（Win10 1803+/Win11 自带），
        用户不用去装任何浏览器；
      · 窗口是**我们自己进程**创建的，标题栏颜色能用 DWM 直接改成深色；
        （以前改不了 —— 窗口属于浏览器进程，它初始化完会把颜色刷回去。）
    """
    global _WEBVIEW_WINDOW

    try:
        import webview
    except Exception:
        return False

    w, h = _window_size()

    def _on_shown() -> None:
        """窗口刚显示时，把标题栏刷成深色。

        注意：必须**只在 UI 线程**里调，绝不能从后台线程去碰窗口对象 ——
        曾经写过一个"每 2 秒跨线程遍历 Application.OpenForms"的版本，
        结果把界面彻底卡死（白屏、标题栏显示"无响应"）。
        """
        time.sleep(1.2)      # 等窗口真正画出来，否则拿不到句柄
        try:
            for hwnd in ime.app_window_handles():
                ime.darken_titlebar(hwnd)
        except Exception:
            pass

    try:
        window = webview.create_window(
            APP_NAME, url,
            width=w, height=h,
            min_size=(880, 620),
        )
        _WEBVIEW_WINDOW = window
        try:
            window.events.shown += lambda: threading.Thread(
                target=_on_shown, daemon=True).start()
        except Exception:
            threading.Thread(target=_on_shown, daemon=True).start()

        print("用内嵌窗口打开（WebView2）")
        webview.start(debug=False)      # 阻塞，直到窗口被关闭
        return True
    except Exception as exc:
        print(f"内嵌窗口不可用（{exc}），改用浏览器")
        _WEBVIEW_WINDOW = None
        return False


def _close_embedded_window() -> bool:
    """把内嵌窗口关掉（退出按钮用）。"""
    global _WEBVIEW_WINDOW
    if _WEBVIEW_WINDOW is None:
        return False
    try:
        _WEBVIEW_WINDOW.destroy()
        return True
    except Exception:
        return False


def _no_browser_hint(url: str) -> None:
    """一个浏览器都找不到时的兜底提示。

    用 Win32 的 MessageBox —— 它由系统绘制，不需要任何浏览器参与，
    所以"连浏览器都没有"的情况下它照样能弹出来把话说明白。
    """
    msg = (
        f"竹喧需要一个浏览器来显示界面，但这台电脑上没找到。\n\n"
        f"请安装 Microsoft Edge 或 Google Chrome（都免费），装好后重新打开竹喧。\n\n"
        f"（服务其实已经在运行，你也可以手动在浏览器里打开：\n{url}）"
    )
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, msg, "竹喧 · 找不到浏览器", 0x40)  # 信息图标
    except Exception:
        print(msg)


def _open_window(url: str) -> None:
    """开一个独立窗口显示界面。

    优先把界面**内嵌进程序自己的窗口**（WebView2）—— 最像原生程序，
    而且不要求对方装浏览器。

    内嵌不可用时退回浏览器方案：Chromium 系浏览器的 `--app`（无地址栏的独立窗口）
    → 系统默认浏览器 → 都没有就弹窗提示。
    """
    if _webview_available() and _open_window_embedded(url):
        return
    _open_window_browser(url)


def _open_window_browser(url: str) -> None:
    """兜底：用浏览器开窗口（内嵌不可用时走这条）。

    优先用 Chromium 系浏览器（Edge / Chrome / Brave…）的 `--app` 模式：
    那样出来的是**没有地址栏、没有标签页**的独立窗口，用起来跟原生程序一样。
    Firefox 不支持 `--app`，所以不在候选里。
    """
    found = _find_browser()
    if not found:
        # 一个 Chromium 系都没找到 —— 退回系统默认浏览器。
        # 界面还是能出来（只是会带地址栏），比"什么都不发生"好得多。
        try:
            opened = webbrowser.open(url)
        except Exception:
            opened = False
        if not opened:
            # 连默认浏览器都没有：用系统弹窗把话说明白（MessageBox 不依赖浏览器）
            _no_browser_hint(url)
        return

    exe, browser_name = found
    print(f"用 {browser_name} 打开窗口")

    # 关掉自动填充模块（输入框一聚焦就弹「保存的信息」下拉，很碍事）。
    # 这些都是 Chromium 的 feature 开关，不认识的会被静默忽略、不会出问题。
    no_autofill = ",".join([
        "Autofill",                              # 整个模块（若该版本有此开关）
        "AutofillServerCommunication",           # 不再向服务器要填充预测
        "AutofillEnableAccountWalletStorage",
        "AutofillEnableProfileDeduplication",
        "AutofillEnablePaymentsMetadata",
        "AutofillEnableSaveCardLoadingAndUpdating",
        "AutofillEnableVirtualCardMetadata",
        "PasswordManagerOnboarding",
    ])
    subprocess.Popen([
        exe, f"--app={url}",
        "--window-size=%d,%d" % _window_size(),
        # 让 Chromium 按深色主题渲染自己的外壳（窗口标题栏、滚动条…）。
        # 竹喧是深色界面，而系统是浅色主题时，那条白标题栏特别扎眼（用户反馈的）。
        # 试过用 DwmSetWindowAttribute 改标题栏颜色：窗口刚开时有效，浏览器初始化完
        # 又会刷回浅色，稳不住。这个开关是让它**从一开始就按深色画**，实测标题栏变纯黑，
        # 页面本身不受影响（不会被反色）。
        "--force-dark-mode",
        # 别把本机的登录态带进来。不加这个，新配置目录首次打开会弹
        # 「正在同步你的浏览数据 · xxx@qq.com 已在此设备上登录」——
        # 既挡住整个界面，又把机主的邮箱暴露给任何看到屏幕的人。
        # （msImplicitSignin 那几个是 Edge 专属，Chrome 会忽略，无害。）
        "--disable-features=msImplicitSignin,msEdgeIdentitySync,EdgeSigninPromo",
        "--disable-sync",
        "--no-service-autorun",
        "--no-first-run",
        "--no-default-browser-check",
        f"--disable-features={no_autofill}",
        "--disable-save-password-bubble",
        # 用竹喧自己的配置目录：一是不会把你日常浏览器里那些
        # 「保存的信息」带进来（输入框一聚焦就弹下拉，很烦），
        # 二是应用和你的日常浏览互不打扰。
        f"--user-data-dir={DATA_DIR / 'browser-profile'}",
    ], cwd=str(DATA_DIR))


def _migrate_profile_dir() -> None:
    """老版本的配置目录叫 edge-profile，现在可能是别的浏览器，改叫 browser-profile。

    这里做一次性改名，免得升级后丢浏览器的缓存（更重要的是别让人以为数据没了）。
    """
    old = DATA_DIR / "edge-profile"
    new = DATA_DIR / "browser-profile"
    try:
        if old.exists() and not new.exists():
            old.rename(new)
    except OSError:
        pass          # 改名失败也不影响使用，大不了重建一个


def _running_instance() -> str | None:
    """看看是不是已经有一个竹喧在后台跑着了。

    这样反复双击图标只会打开窗口，不会堆一堆后台进程（关掉窗口后服务还活着，
    下次双击直接复用，不用重新加载）。
    """
    for port in range(DEFAULT_PORT, DEFAULT_PORT + 8):
        if _port_free(port):
            continue
        url = f"http://{HOST}:{port}/"
        try:
            with urllib.request.urlopen(url + "api/stats", timeout=1.5) as resp:
                data = json.loads(resp.read().decode("utf-8", "ignore"))
            if isinstance(data, dict) and "streak_days" in data and "no_cn" in data:
                return url
        except Exception:
            continue
    return None


def _ensure_streams() -> None:
    """给 sys.stdout / sys.stderr 兜底。

    用 PyInstaller 的 --windowed 打包后**没有控制台**，这两个流是 None；
    而 uvicorn 初始化日志格式化器时会执行 `sys.stdout.isatty()`，
    直接抛 AttributeError → 整个程序起不来（双击图标时才会暴露，
    从终端启动因为有控制台反而正常 —— 这就是之前漏掉它的原因）。

    顺手把日志落到 data/app.log，以后排查有据可查。
    """
    out_ok = getattr(sys, "stdout", None) is not None
    err_ok = getattr(sys, "stderr", None) is not None
    if out_ok and err_ok:
        return

    stream = None
    try:
        log_dir = BASE_DIR / "data"
        log_dir.mkdir(parents=True, exist_ok=True)
        stream = open(log_dir / "app.log", "a", encoding="utf-8", buffering=1)
    except OSError:
        try:
            stream = open(os.devnull, "w", encoding="utf-8")
        except OSError:
            return

    if not out_ok:
        sys.stdout = stream
    if not err_ok:
        sys.stderr = stream


def main() -> None:
    _ensure_streams()          # 必须在任何 print / uvicorn 之前
    _migrate_profile_dir()     # 老版本的 edge-profile 改名成 browser-profile

    existing = _running_instance()
    if existing:
        print(f"{APP_NAME} 已经在运行，直接开窗口：{existing}")
        _open_window(existing)
        return

    port = _pick_port()
    url = f"http://{HOST}:{port}/"

    # 服务放**子线程**，窗口放**主线程**。
    # 为什么这么分：内嵌窗口（WebView2）的 GUI 循环必须在主线程跑；
    # 以前是 uvicorn 占着主线程、窗口在子线程里开 —— 那样内嵌窗口起不来。
    def _serve() -> None:
        uvicorn.run(app, host=HOST, port=port, log_level="warning")

    threading.Thread(target=_serve, daemon=True).start()
    print(f"{APP_NAME} 启动中 … {url}")

    if not _wait_ready(url + "api/stats"):
        print(f"服务启动超时，请手动打开 {url}")
        return

    # 后台查一下有没有新版本（查不到就算了，绝不影响启动）
    threading.Thread(target=_check_update_bg, daemon=True).start()

    # 内嵌窗口会在这里阻塞到用户关窗；关掉后主线程结束，守护线程的服务随之退出
    _open_window(url)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # 打包成 exe 后没有控制台，出错只能靠这个文件
        import traceback
        try:
            (BASE_DIR / "启动错误.log").write_text(traceback.format_exc(), encoding="utf-8")
        except OSError:
            pass
        raise
