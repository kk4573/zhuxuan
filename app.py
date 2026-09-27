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
from fastapi import FastAPI, File, HTTPException, Response, UploadFile
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from core import config, db, dictionary, ime, judge, srs
from core.paths import BASE_DIR, DATA_DIR, RES_DIR

WEB_DIR = RES_DIR / "web"
HOST = "127.0.0.1"
DEFAULT_PORT = 8765
APP_NAME = "竹喧"

EDGE_PATHS = (
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init()
    db.backup()
    yield


app = FastAPI(title=APP_NAME, lifespan=lifespan)


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


@app.get("/api/words")
def api_words(q: str = "", sort: str = "created", page: int = 1, size: int = 200):
    rows, total = db.list_words(q, sort, page, size)
    return {"total": total, "page": page, "size": size, "items": rows}


@app.post("/api/words")
def api_add(w: WordIn):
    en = w.en.strip()
    if not en:
        raise HTTPException(400, "英文不能为空")
    if db.find_word(en):
        raise HTTPException(409, f"「{en}」已经在词库里了")
    wid = db.add_word(en, w.cn, w.pos, w.ph, w.note)
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


def _do_import(items: list[tuple[str, str, str]]) -> dict:
    added = skipped = 0
    new_words: list[str] = []
    for en, cn, pos in items:
        en = (en or "").strip()
        if not en:
            continue
        if db.find_word(en):
            skipped += 1
            continue
        if db.add_word(en, cn or "", pos or ""):
            added += 1
            new_words.append(en)
        else:
            skipped += 1
    return {"added": added, "skipped": skipped, "new_words": new_words}


class ImportIn(BaseModel):
    text: str


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
    return _do_import(items)


@app.post("/api/words/import-xlsx")
async def api_import_xlsx(file: UploadFile = File(...)):
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
    return _do_import(items)


# ============================================================ 背诵会话

class StartIn(BaseModel):
    size: int = 20


@app.post("/api/session/start")
def api_start(p: StartIn):
    pool = db.pick_pool()
    if not pool:
        raise HTTPException(400, "词库里还没有带中文释义的单词，先导入单词再生成释义")
    n = max(1, min(int(p.size or 1), len(pool)))
    picked = srs.pick(pool, n)
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


@app.post("/api/words/auto-add")
def api_auto_add(p: AutoAddIn):
    """批量添加：一行一个英文就够了，中文自动查。

    每行也允许带中文（Tab / 逗号分隔），带了就用你给的、不查词典。
    """
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
        if db.add_word(en, cn, pos, ph):
            added += 1
        else:
            skipped += 1
    return {"added": added, "skipped": skipped, "failed": failed,
            "no_cn": db.count_pending_cn()}


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


@app.put("/api/config")
def api_config_put(p: ConfigIn):
    return config.save(p.model_dump())


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


@app.post("/api/quit")
def api_quit():
    """退出竹喧：先关掉应用窗口，再结束后台服务（省得用户再点一次 ×）。"""
    def _die() -> None:
        time.sleep(0.8)                 # 先把响应发回去
        ime.close_app_windows()         # 顺手把窗口也关了
        time.sleep(0.5)                 # 给 Edge 一点时间处理关闭消息
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


def _find_edge() -> str | None:
    for p in EDGE_PATHS:
        if os.path.exists(p):
            return p
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


def _open_window(url: str) -> None:
    edge = _find_edge()
    if edge:
        # 关掉 Edge 的自动填充模块（输入框一聚焦就弹「保存的信息」下拉，很碍事）。
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
            edge, f"--app={url}",
            "--window-size=1040,780",
            "--no-first-run",
            "--no-default-browser-check",
            f"--disable-features={no_autofill}",
            "--disable-save-password-bubble",
            # 用竹喧自己的浏览器配置目录：一是不会把你日常 Edge 里那些
            # 「保存的信息」带进来（输入框一聚焦就弹下拉，很烦），
            # 二是应用和你的日常浏览互不打扰。
            f"--user-data-dir={DATA_DIR / 'edge-profile'}",
        ], cwd=str(DATA_DIR))
    else:
        webbrowser.open(url)


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

    existing = _running_instance()
    if existing:
        print(f"{APP_NAME} 已经在运行，直接开窗口：{existing}")
        _open_window(existing)
        return

    port = _pick_port()
    url = f"http://{HOST}:{port}/"

    def _launcher() -> None:
        if _wait_ready(url + "api/stats"):
            _open_window(url)
        else:
            print(f"服务启动超时，请手动打开 {url}")

    threading.Thread(target=_launcher, daemon=True).start()
    print(f"{APP_NAME} 启动中 … {url}")
    uvicorn.run(app, host=HOST, port=port, log_level="warning")


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
