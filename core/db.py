"""竹喧 · 数据层：建表 / 备份 / 全部 SQL 都集中在这里"""
from __future__ import annotations

import os
import json
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
CREATE TABLE IF NOT EXISTS books (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL UNIQUE,
    sort       INTEGER NOT NULL DEFAULT 0,
    is_default INTEGER NOT NULL DEFAULT 0,   -- 只有一个词库会是 1
    builtin    TEXT NOT NULL DEFAULT '',     -- 内置词表标识（CET4 / CET6 / NPEE…），自建为空
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS book_words (
    book_id  INTEGER NOT NULL,
    word_id  INTEGER NOT NULL,
    added_at TEXT NOT NULL,
    PRIMARY KEY (book_id, word_id)
);

CREATE INDEX IF NOT EXISTS idx_book_words_book ON book_words(book_id);
CREATE INDEX IF NOT EXISTS idx_book_words_word ON book_words(word_id);

CREATE TABLE IF NOT EXISTS dict_full (
    word       TEXT PRIMARY KEY COLLATE NOCASE,
    payload    TEXT NOT NULL,                    -- 完整查词结果的 JSON
    fetched_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dict_cache (
    word       TEXT PRIMARY KEY COLLATE NOCASE,
    cn         TEXT NOT NULL DEFAULT '',
    pos        TEXT NOT NULL DEFAULT '',
    ph         TEXT NOT NULL DEFAULT '',
    source     TEXT NOT NULL DEFAULT 'youdao',   -- youdao / ai / manual
    fetched_at TEXT NOT NULL
);

-- 背单词时那句例句。单独存一张表：查询频繁、内容小，
-- 而且 miss 也要记（``sent = ''`` 表示"这个词典里没有例句"），免得每次提交都去问一遍。
CREATE TABLE IF NOT EXISTS sent_cache (
    word       TEXT PRIMARY KEY COLLATE NOCASE,
    sent       TEXT NOT NULL DEFAULT '',         -- 英文例句
    cn         TEXT NOT NULL DEFAULT '',         -- 中文翻译
    src        TEXT NOT NULL DEFAULT '',         -- 出处（如 «柯林斯»）
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


DEFAULT_BOOK_NAME = "我的词库"


def init() -> None:
    with cursor() as conn:
        conn.executescript(SCHEMA)
    migrate_books()


def migrate_books() -> dict:
    """把「所有单词平铺」升级成「多词库」。**可重复运行**，跑第二遍什么都不做。

    做法（全程不改 words 表本身，出问题随时能退回来）：
      1. 建 books / book_words（由 SCHEMA 完成）
      2. 没有默认词库就建一个「我的词库」
      3. 把还没有归属的单词全部挂到默认词库下
    """
    created = attached = 0
    with cursor() as conn:
        row = conn.execute(
            "SELECT id FROM books WHERE is_default = 1 ORDER BY id LIMIT 1"
        ).fetchone()
        if row:
            default_id = row["id"]
        else:
            row = conn.execute("SELECT id FROM books ORDER BY id LIMIT 1").fetchone()
            if row:
                default_id = row["id"]
                conn.execute("UPDATE books SET is_default = 1 WHERE id = ?", (default_id,))
            else:
                cur = conn.execute(
                    "INSERT INTO books (name, sort, is_default, builtin, created_at) "
                    "VALUES (?, 0, 1, '', ?)",
                    (DEFAULT_BOOK_NAME, now()),
                )
                default_id = cur.lastrowid
                created = 1

        # 还没归属的单词 → 挂到默认词库
        orphans = conn.execute(
            "SELECT id FROM words WHERE id NOT IN (SELECT word_id FROM book_words)"
        ).fetchall()
        for o in orphans:
            conn.execute(
                "INSERT OR IGNORE INTO book_words (book_id, word_id, added_at) VALUES (?, ?, ?)",
                (default_id, o["id"], now()),
            )
            attached += 1

        # 顺手清掉历史遗留的孤儿归属（单词早删了、归属还挂着）
        cur = conn.execute(
            "DELETE FROM book_words WHERE word_id NOT IN (SELECT id FROM words)")
        cleaned = cur.rowcount

    return {"default_book_id": default_id, "created_book": created,
            "attached_words": attached, "cleaned_orphans": cleaned}


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


# ---------------------------------------------------------------- 词库

def list_books() -> list[dict]:
    """所有词库，默认词库排最前，其余按 sort、id。"""
    with cursor() as conn:
        rows = conn.execute(
            """SELECT b.id, b.name, b.sort, b.is_default, b.builtin, b.created_at,
                      (SELECT COUNT(*) FROM book_words w WHERE w.book_id = b.id) AS count
                 FROM books b
                ORDER BY b.is_default DESC, b.sort ASC, b.id ASC"""
        ).fetchall()
    return [dict(r) for r in rows]


def get_book(bid: int) -> dict | None:
    with cursor() as conn:
        row = conn.execute("SELECT * FROM books WHERE id = ?", (bid,)).fetchone()
    return dict(row) if row else None


def default_book() -> dict | None:
    with cursor() as conn:
        row = conn.execute(
            "SELECT * FROM books ORDER BY is_default DESC, id ASC LIMIT 1"
        ).fetchone()
    return dict(row) if row else None


def add_book(name: str, builtin: str = "") -> int:
    """新建词库。名字重复会抛 sqlite3.IntegrityError，交给上层转成友好提示。"""
    name = (name or "").strip()
    with cursor() as conn:
        cur = conn.execute(
            "INSERT INTO books (name, sort, is_default, builtin, created_at) VALUES (?, ?, 0, ?, ?)",
            (name, 100, builtin, now()),
        )
    return cur.lastrowid


def rename_book(bid: int, name: str) -> bool:
    with cursor() as conn:
        conn.execute("UPDATE books SET name = ? WHERE id = ?", ((name or "").strip(), bid))
    return True


def delete_book(bid: int) -> int:
    """删词库：**只删归属关系，单词本身和其他词库都不受影响**。

    默认词库不给删（要删得先把别的设为默认），否则单词会无家可归。
    返回删掉的归属条数。
    """
    with cursor() as conn:
        row = conn.execute("SELECT is_default FROM books WHERE id = ?", (bid,)).fetchone()
        if not row:
            return 0
        if row["is_default"]:
            raise ValueError("默认词库不能删除")
        n = conn.execute("SELECT COUNT(*) FROM book_words WHERE book_id = ?", (bid,)).fetchone()[0]
        conn.execute("DELETE FROM book_words WHERE book_id = ?", (bid,))
        conn.execute("DELETE FROM books WHERE id = ?", (bid,))
    return n


def set_default_book(bid: int) -> bool:
    with cursor() as conn:
        conn.execute("UPDATE books SET is_default = 0")
        conn.execute("UPDATE books SET is_default = 1 WHERE id = ?", (bid,))
    return True


def book_of_word(wid: int) -> list[dict]:
    """这个词属于哪几个词库（词库里显示用）。"""
    with cursor() as conn:
        rows = conn.execute(
            "SELECT b.id, b.name FROM books b JOIN book_words w ON w.book_id = b.id "
            "WHERE w.word_id = ? ORDER BY b.is_default DESC, b.id ASC",
            (wid,),
        ).fetchall()
    return [dict(r) for r in rows]


def attach_word(bid: int, wid: int) -> bool:
    """把一个词挂到某个词库下。已经有了就返回 False（不算错）。"""
    with cursor() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO book_words (book_id, word_id, added_at) VALUES (?, ?, ?)",
            (bid, wid, now()),
        )
        return cur.rowcount > 0


def detach_word(bid: int, wid: int) -> bool:
    """把词从某个词库里移出（**不删单词本身**）。"""
    with cursor() as conn:
        cur = conn.execute("DELETE FROM book_words WHERE book_id = ? AND word_id = ?", (bid, wid))
        return cur.rowcount > 0


def import_words(items: list[dict], book_id: int) -> dict:
    """把一批词导入某个词库。

    - **已经在库里的词不重复建**，只加一条归属关系（掌握度、学习记录全部沿用）
    - 新词才真正插入
    - 全程一个事务，几千个词也很快

    返回 {added, attached, total}
    """
    added = attached = 0
    stamp = now()
    with cursor() as conn:
        for it in items:
            en = (it.get("en") or "").strip()
            if not en:
                continue
            row = conn.execute(
                "SELECT id FROM words WHERE en = ? COLLATE NOCASE", (en,)
            ).fetchone()
            if row:
                wid = row["id"]
            else:
                cur = conn.execute(
                    "INSERT INTO words (en, cn, pos, ph, note, created_at) VALUES (?,?,?,?,?,?)",
                    (en, it.get("cn", ""), it.get("pos", ""), it.get("ph", ""), "", stamp),
                )
                wid = cur.lastrowid
                added += 1
            cur = conn.execute(
                "INSERT OR IGNORE INTO book_words (book_id, word_id, added_at) VALUES (?, ?, ?)",
                (book_id, wid, stamp),
            )
            if cur.rowcount:
                attached += 1
    return {"added": added, "attached": attached, "total": len(items)}


def book_word_ids(bid: int) -> set[int]:
    with cursor() as conn:
        rows = conn.execute("SELECT word_id FROM book_words WHERE book_id = ?", (bid,)).fetchall()
    return {r["word_id"] for r in rows}


# ---------------------------------------------------------------- 单词

def list_words(q: str = "", sort: str = "created", page: int = 1, size: int = 100,
               book_id: int | None = None):
    """列出单词。给了 book_id 就只列那个词库里的。"""
    order = {
        "created": "w.created_at DESC, w.id DESC",
        "mastery": "w.mastery ASC, w.id ASC",
        "mastery_desc": "w.mastery DESC, w.id ASC",
        "alpha": "w.en COLLATE NOCASE ASC",
        "wrong": "w.wrong_cnt DESC, w.id ASC",
    }.get(sort, "w.created_at DESC, w.id DESC")

    joins, where, args = "", [], []
    if book_id:
        joins = "JOIN book_words bw ON bw.word_id = w.id AND bw.book_id = ?"
        args.append(book_id)
    if q.strip():
        where.append("(w.en LIKE ? OR w.cn LIKE ?)")
        like = f"%{q.strip()}%"
        args += [like, like]
    clause = ("WHERE " + " AND ".join(where)) if where else ""

    with cursor() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) FROM words w {joins} {clause}", args).fetchone()[0]
        rows = conn.execute(
            f"SELECT w.* FROM words w {joins} {clause} ORDER BY {order} LIMIT ? OFFSET ?",
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


def add_word(en: str, cn: str = "", pos: str = "", ph: str = "", note: str = "",
             book_id: int | None = None) -> int | None:
    """新增单词。已存在（不分大小写）则返回 None，不覆盖已有数据。

    给了 book_id 就顺手挂到那个词库下（新词才有意义；已存在的词要用 attach_word）。
    """
    en = en.strip()
    if not en:
        return None
    with cursor() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO words (en, cn, pos, ph, note, created_at) VALUES (?,?,?,?,?,?)",
            (en, cn.strip(), pos.strip(), ph.strip(), note.strip(), now()),
        )
        new_id = cur.lastrowid if cur.rowcount else None
        if book_id and new_id:
            conn.execute(
                "INSERT OR IGNORE INTO book_words (book_id, word_id, added_at) VALUES (?, ?, ?)",
                (book_id, new_id, now()),
            )
        return new_id


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
    """删单词。**归属关系必须一起删**，否则词库里会留下指向空气的记录，
    词库显示的条数就会和实际词数对不上（曾经就是这个 bug）。"""
    with cursor() as conn:
        conn.execute("DELETE FROM book_words WHERE word_id = ?", (wid,))
        cur = conn.execute("DELETE FROM words WHERE id = ?", (wid,))
    return cur.rowcount > 0


def cleanup_orphans() -> int:
    """清掉历史遗留的孤儿归属（单词已经不在、归属还在）。返回清掉的条数。"""
    with cursor() as conn:
        cur = conn.execute(
            """DELETE FROM book_words
                WHERE word_id NOT IN (SELECT id FROM words)""")
    return cur.rowcount


def pick_pool(book_id: int | None = None) -> list[dict]:
    """抽词池：只取有中文释义的词（没释义就出不了题）。

    顺带带出「今天已经考过几次」——抽词时会用它压低当天重复出现的概率
    （同一天反复背同一个词，记忆还没淡，掌握度却涨得快，没意义）。
    """
    sql = """SELECT w.id, w.en, w.cn, w.pos, w.ph, w.mastery,
                    (SELECT COUNT(*) FROM answers a
                      WHERE a.word_id = w.id AND substr(a.at, 1, 10) = ?) AS today_asked
               FROM words w
               {join}
              WHERE w.cn IS NOT NULL AND TRIM(w.cn) <> ''"""
    args: list = [today()]
    if book_id:
        sql = sql.format(join="JOIN book_words bw ON bw.word_id = w.id AND bw.book_id = ?")
        args.append(book_id)
    else:
        sql = sql.format(join="")
    with cursor() as conn:
        rows = conn.execute(sql, args).fetchall()
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


def dict_full_get(word: str) -> dict | None:
    """取一份缓存的完整查词结果（查词页用）。"""
    with cursor() as conn:
        row = conn.execute(
            "SELECT payload, fetched_at FROM dict_full WHERE word = ? COLLATE NOCASE",
            ((word or "").strip(),),
        ).fetchone()
    if not row:
        return None
    try:
        data = json.loads(row["payload"])
    except Exception:
        return None
    data["_cached_at"] = row["fetched_at"]
    return data


def dict_full_put(word: str, payload: dict) -> None:
    with cursor() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO dict_full (word, payload, fetched_at) VALUES (?, ?, ?)",
            ((word or "").strip(), json.dumps(payload, ensure_ascii=False), now()),
        )


def dict_clear_all() -> dict:
    """把两份词典缓存都清掉（改了释义详细程度时用）。不动词库和学习记录。"""
    with cursor() as conn:
        a = conn.execute("DELETE FROM dict_cache").rowcount
        b = conn.execute("DELETE FROM dict_full").rowcount
    return {"dict_cache": a, "dict_full": b}


def sent_get(word: str) -> dict | None:
    """取缓存的例句。有记录就返回（`sent` 为空字符串表示"确认过没有例句"）。"""
    with cursor() as conn:
        row = conn.execute(
            "SELECT * FROM sent_cache WHERE word = ? COLLATE NOCASE", (word,)).fetchone()
    if not row:
        return None
    return {"sent": row["sent"], "cn": row["cn"], "src": row["src"], "cached": True}


def sent_put(word: str, sent: str, cn: str = "", src: str = "") -> None:
    with cursor() as conn:
        conn.execute(
            """INSERT INTO sent_cache (word, sent, cn, src, fetched_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(word) DO UPDATE SET
                 sent = excluded.sent, cn = excluded.cn,
                 src = excluded.src, fetched_at = excluded.fetched_at""",
            (word, sent, cn, src, now()))


def dict_full_count() -> int:
    with cursor() as conn:
        return conn.execute("SELECT COUNT(*) FROM dict_full").fetchone()[0]


def dict_full_clear() -> int:
    """清空查词缓存。**只动 dict_full**，词库、答题记录、释义缓存一概不碰。"""
    with cursor() as conn:
        n = conn.execute("SELECT COUNT(*) FROM dict_full").fetchone()[0]
        conn.execute("DELETE FROM dict_full")
    return n


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
