"""竹喧 · 数据层：建表 / 备份 / 全部 SQL 都集中在这里"""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from .paths import BASE_DIR, DATA_DIR

# 允许用环境变量 ZHUXUAN_DB 指定数据库文件（自动化测试用，跑测试不会碰真实数据）
DB_PATH = Path(os.environ.get("ZHUXUAN_DB") or (DATA_DIR / "words.db"))
BACKUP_DIR = DATA_DIR / "backups"

SCHEMA = """
CREATE TABLE IF NOT EXISTS words (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    en         TEXT    NOT NULL COLLATE NOCASE UNIQUE,  -- 英文（标准答案）
    cn         TEXT    NOT NULL DEFAULT '',             -- 中文主释义（只保留最常用的一个义项）
    pos        TEXT    NOT NULL DEFAULT '',             -- 词性
    ph         TEXT    NOT NULL DEFAULT '',             -- 音标
    note       TEXT    NOT NULL DEFAULT '',             -- 备注
    mastery    INTEGER NOT NULL DEFAULT 0,              -- 掌握度：>=0，不封顶
    streak     INTEGER NOT NULL DEFAULT 0,              -- 连对次数（用于答对时的递增加成）
    right_cnt  INTEGER NOT NULL DEFAULT 0,
    wrong_cnt  INTEGER NOT NULL DEFAULT 0,
    last_seen  TEXT,
    created_at TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_words_mastery ON words(mastery);

CREATE TABLE IF NOT EXISTS sessions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT    NOT NULL,
    ended_at   TEXT,
    asked      INTEGER NOT NULL DEFAULT 0,   -- 本轮总共作答次数（含重考）
    right_cnt  INTEGER NOT NULL DEFAULT 0,
    wrong_cnt  INTEGER NOT NULL DEFAULT 0,
    skip_cnt   INTEGER NOT NULL DEFAULT 0,
    picked     INTEGER NOT NULL DEFAULT 0    -- 本轮抽了多少个不同的词
);

CREATE TABLE IF NOT EXISTS answers (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    word_id    INTEGER NOT NULL,
    result     TEXT    NOT NULL,             -- right / wrong / skip
    typed      TEXT    NOT NULL DEFAULT '',
    at         TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_answers_at ON answers(at);
CREATE INDEX IF NOT EXISTS idx_answers_word ON answers(word_id);

-- 查过的词在这里留一份，二次查询不再联网，断网也能用
CREATE TABLE IF NOT EXISTS dict_cache (
    word       TEXT PRIMARY KEY COLLATE NOCASE,
    cn         TEXT NOT NULL DEFAULT '',
    pos        TEXT NOT NULL DEFAULT '',
    ph         TEXT NOT NULL DEFAULT '',
    source     TEXT NOT NULL DEFAULT 'youdao',   -- youdao / ai / manual
    fetched_at TEXT NOT NULL
);
"""


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


@contextmanager
def cursor():
    """一次事务：正常结束自动 commit，异常自动 rollback，最后一定关闭。"""
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init() -> None:
    with cursor() as conn:
        conn.executescript(SCHEMA)


def backup(keep: int = 10) -> str | None:
    """把数据库完整备份一份到 data/backups/，只保留最近 keep 份。"""
    if not DB_PATH.exists():
        return None
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = BACKUP_DIR / f"words-{stamp}.db"
    n = 1
    while target.exists():
        target = BACKUP_DIR / f"words-{stamp}-{n}.db"
        n += 1
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("VACUUM INTO ?", (str(target),))
    finally:
        conn.close()
    olds = sorted(BACKUP_DIR.glob("words-*.db"))
    for p in olds[:-keep]:
        try:
            p.unlink()
        except OSError:
            pass
    return str(target)


# ---------------------------------------------------------------- 单词

def list_words(q: str = "", sort: str = "created", page: int = 1, size: int = 100):
    order = {
        "created": "created_at DESC, id DESC",
        "mastery": "mastery ASC, id ASC",
        "mastery_desc": "mastery DESC, id ASC",
        "alpha": "en COLLATE NOCASE ASC",
        "wrong": "wrong_cnt DESC, id ASC",
    }.get(sort, "created_at DESC, id DESC")
    where, args = "", []
    if q.strip():
        where = "WHERE en LIKE ? OR cn LIKE ?"
        like = f"%{q.strip()}%"
        args = [like, like]
    with cursor() as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM words {where}", args).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM words {where} ORDER BY {order} LIMIT ? OFFSET ?",
            args + [size, (page - 1) * size],
        ).fetchall()
    return [dict(r) for r in rows], total


def get_word(wid: int) -> dict | None:
    with cursor() as conn:
        row = conn.execute("SELECT * FROM words WHERE id = ?", (wid,)).fetchone()
    return dict(row) if row else None


def find_word(en: str) -> dict | None:
    with cursor() as conn:
        row = conn.execute("SELECT * FROM words WHERE en = ? COLLATE NOCASE", (en,)).fetchone()
    return dict(row) if row else None


def add_word(en: str, cn: str = "", pos: str = "", ph: str = "", note: str = "") -> int | None:
    """新增单词。已存在（不分大小写）则返回 None，不覆盖已有数据。"""
    en = en.strip()
    if not en:
        return None
    with cursor() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO words (en, cn, pos, ph, note, created_at) VALUES (?,?,?,?,?,?)",
            (en, cn.strip(), pos.strip(), ph.strip(), note.strip(), now()),
        )
        return cur.lastrowid if cur.rowcount else None


def update_word(wid: int, **fields) -> bool:
    allowed = ("en", "cn", "pos", "ph", "note", "mastery")
    sets = [f"{k} = ?" for k in fields if k in allowed]
    vals = [fields[k] for k in fields if k in allowed]
    if not sets:
        return False
    vals.append(wid)
    with cursor() as conn:
        cur = conn.execute(f"UPDATE words SET {', '.join(sets)} WHERE id = ?", vals)
    return cur.rowcount > 0


def record_answer(wid: int, result: str, mastery: int, streak: int) -> None:
    """把一次作答的结果写回单词：掌握度、连对数、对错计数、最近作答时间。"""
    with cursor() as conn:
        if result == "right":
            conn.execute(
                "UPDATE words SET mastery = ?, streak = ?, right_cnt = right_cnt + 1, "
                "last_seen = ? WHERE id = ?",
                (mastery, streak, now(), wid),
            )
        else:
            conn.execute(
                "UPDATE words SET mastery = ?, streak = 0, wrong_cnt = wrong_cnt + 1, "
                "last_seen = ? WHERE id = ?",
                (mastery, now(), wid),
            )


def delete_word(wid: int) -> bool:
    with cursor() as conn:
        cur = conn.execute("DELETE FROM words WHERE id = ?", (wid,))
    return cur.rowcount > 0


def pick_pool() -> list[dict]:
    """抽词池：只取有中文释义的词（没释义就出不了题）。"""
    with cursor() as conn:
        rows = conn.execute(
            "SELECT id, en, cn, pos, ph, mastery FROM words "
            "WHERE cn IS NOT NULL AND TRIM(cn) <> ''"
        ).fetchall()
    return [dict(r) for r in rows]


# 「缺释义、而且还没查过词典」的筛选条件。
# 已经查过但词典里没有的词（dict_cache 里留了 source='miss'）不算在内 ——
# 否则每次点「补全释义」都会把那几个查不到的词重新问一遍，白等时间。
def words_missing_cn() -> int:
    """词库里还没有释义的词有多少个（stats 里给界面显示用）。"""
    with cursor() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM words WHERE cn IS NULL OR TRIM(cn) = ''"
        ).fetchone()[0]


_PENDING_SQL = (
    "FROM words w "
    "LEFT JOIN dict_cache d ON d.word = w.en COLLATE NOCASE "
    "WHERE (w.cn IS NULL OR TRIM(w.cn) = '') "
    "AND (d.source IS NULL OR d.source != 'miss') "
)



def words_pending_cn(limit: int = 200) -> list[dict]:
    """缺释义、**而且还没查过词典**的词。

    已经查过但词典里没有的词不在这里 —— 免得每次点「补全释义」都把那几个查不到的
    重新问一遍，白等时间。
    """
    with cursor() as conn:
        rows = conn.execute(
            "SELECT w.id, w.en, w.pos, w.ph " + _PENDING_SQL + "ORDER BY w.id LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def count_pending_cn() -> int:
    with cursor() as conn:
        return conn.execute("SELECT COUNT(*) " + _PENDING_SQL).fetchone()[0]


# ---------------------------------------------------------------- 词典缓存

def dict_get(word: str) -> dict | None:
    with cursor() as conn:
        row = conn.execute(
            "SELECT cn, pos, ph, source FROM dict_cache WHERE word = ? COLLATE NOCASE",
            (word.strip(),),
        ).fetchone()
    return dict(row) if row else None


def dict_put(word: str, cn: str, pos: str, ph: str, source: str = "youdao") -> None:
    with cursor() as conn:
        conn.execute(
            "INSERT INTO dict_cache (word, cn, pos, ph, source, fetched_at) VALUES (?,?,?,?,?,?) "
            "ON CONFLICT(word) DO UPDATE SET cn=excluded.cn, pos=excluded.pos, ph=excluded.ph, "
            "source=excluded.source, fetched_at=excluded.fetched_at",
            (word.strip(), cn, pos, ph, source, now()),
        )


# ---------------------------------------------------------------- 会话

def create_session(picked: int) -> int:
    with cursor() as conn:
        cur = conn.execute(
            "INSERT INTO sessions (started_at, picked) VALUES (?, ?)", (now(), picked)
        )
        return cur.lastrowid


def log_answer(session_id: int, word_id: int, result: str, typed: str = "") -> None:
    with cursor() as conn:
        conn.execute(
            "INSERT INTO answers (session_id, word_id, result, typed, at) VALUES (?,?,?,?,?)",
            (session_id, word_id, result, typed[:200], now()),
        )
        col = {"right": "right_cnt", "wrong": "wrong_cnt", "skip": "skip_cnt"}[result]
        conn.execute(
            f"UPDATE sessions SET asked = asked + 1, {col} = {col} + 1 WHERE id = ?",
            (session_id,),
        )


def has_answered(session_id: int, word_id: int) -> bool:
    """这个词在本轮里之前答过没有 —— 用来判断「这次是不是重考」。"""
    with cursor() as conn:
        row = conn.execute(
            "SELECT 1 FROM answers WHERE session_id = ? AND word_id = ? LIMIT 1",
            (session_id, word_id),
        ).fetchone()
    return row is not None


def finish_session(session_id: int) -> None:
    with cursor() as conn:
        conn.execute("UPDATE sessions SET ended_at = ? WHERE id = ?", (now(), session_id))


# ---------------------------------------------------------------- 统计

def stats() -> dict:
    with cursor() as conn:
        row = conn.execute(
            """SELECT COUNT(*) AS total,
                      SUM(CASE WHEN mastery = 0 THEN 1 ELSE 0 END) AS fresh,
                      SUM(CASE WHEN mastery BETWEEN 1 AND 9 THEN 1 ELSE 0 END) AS learning,
                      SUM(CASE WHEN mastery >= 10 THEN 1 ELSE 0 END) AS mastered,
                      AVG(mastery) AS avg_mastery
               FROM words"""
        ).fetchone()
        t = conn.execute(
            """SELECT COUNT(*) AS n,
                      SUM(CASE WHEN result = 'right' THEN 1 ELSE 0 END) AS r,
                      SUM(CASE WHEN result = 'right' THEN 0 ELSE 1 END) AS w
               FROM answers WHERE substr(at, 1, 10) = ?""",
            (today(),),
        ).fetchone()
        days = conn.execute(
            "SELECT COUNT(DISTINCT substr(at, 1, 10)) FROM answers "
            "WHERE result = 'right' AND substr(at, 1, 10) >= ?",
            (streak_start(),),
        ).fetchone()[0]
    return {
        "total": row["total"] or 0,
        "fresh": row["fresh"] or 0,
        "learning": row["learning"] or 0,
        "mastered": row["mastered"] or 0,
        "avg_mastery": round(row["avg_mastery"] or 0, 1),
        "no_cn": words_missing_cn(),
        "no_cn_pending": count_pending_cn(),
        "today_asked": t["n"] or 0,
        "today_right": t["r"] or 0,
        "today_wrong": t["w"] or 0,
        "streak_days": days,
    }


def daily(days: int = 30) -> list[dict]:
    with cursor() as conn:
        rows = conn.execute(
            """SELECT substr(at, 1, 10) AS day,
                      COUNT(*) AS asked,
                      SUM(CASE WHEN result = 'right' THEN 1 ELSE 0 END) AS right_cnt
               FROM answers
               GROUP BY day ORDER BY day DESC LIMIT ?""",
            (days,),
        ).fetchall()
    return [dict(r) for r in rows]


def streak_start(lookback: int = 400) -> str:
    """连续打卡的起点日期：从今天往前找第一个没有答对的日期。"""
    from datetime import timedelta

    with cursor() as conn:
        rows = conn.execute(
            "SELECT DISTINCT substr(at, 1, 10) AS day FROM answers "
            "WHERE at >= ? ORDER BY day DESC",
            ((datetime.now() - timedelta(days=lookback)).strftime("%Y-%m-%d %H:%M:%S"),),
        ).fetchall()
    days = {r["day"] for r in rows}
    d = datetime.now()
    if d.strftime("%Y-%m-%d") not in days:      # 今天还没背，从昨天开始算
        d -= timedelta(days=1)
    start = d
    while d.strftime("%Y-%m-%d") in days:
        start = d
        d -= timedelta(days=1)
    return start.strftime("%Y-%m-%d")          # 只返回日期，方便和 substr(at,1,10) 比较
