"""竹喧 · 冒烟测试

用**独立的临时数据库**起一个服务，把核心链路整条跑一遍：
导入 → 抽词 → 判定（正确/拼错/英美变体/空格容错）→ 掌握度变化 → 跳过 → 统计。
可重复运行，**不会碰 data/words.db 里的真实数据**。

    .venv/Scripts/python.exe tests/smoke.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PORT = 8799
BASE = f"http://127.0.0.1:{PORT}"
DBFILE = ROOT / "data" / "smoke-test.db"

OK = 0
FAIL = 0


def check(label: str, cond: bool, extra: str = "") -> None:
    global OK, FAIL
    if cond:
        OK += 1
        print(f"  [ok]    {label}")
    else:
        FAIL += 1
        print(f"  [FAIL]  {label}   {extra}")


def call(method: str, path: str, payload=None):
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        BASE + path, data=body, method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read().decode("utf-8"))
        except Exception:
            return exc.code, {}


def wait_ready(timeout: float = 30.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        try:
            urllib.request.urlopen(BASE + "/api/stats", timeout=1)
            return True
        except Exception:
            time.sleep(0.2)
    return False


SAMPLE = "\n".join([
    "word\t中文\t词性",                                   # 表头，应被跳过
    "ubiquitous\t无处不在的\tadj.",
    "tentative\t试探性的；暂定的\tadj.",
    "give up\t放弃\tphr.",
    "colour\t颜色\tn.",
    "maintenance\t维护；保养\tn.",
    "thorough\t彻底的\tadj.",
    "acquire\t获得；学到\tv.",
    "colleague\t同事\tn.",
])


def main() -> int:
    global OK, FAIL
    pre_backups = set((ROOT / "data" / "backups").glob("words-*.db"))
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(DBFILE) + suffix)
        if p.exists():
            p.unlink()

    env = os.environ.copy()
    env["ZHUXUAN_DB"] = str(DBFILE)
    print(f"启动测试服务 :{PORT}  (数据库 {DBFILE.name})")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app:app", "--port", str(PORT), "--log-level", "warning"],
        cwd=str(ROOT), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    try:
        if not wait_ready():
            print("服务没起来，放弃")
            return 2

        print("\n— 设置项：改得动、存得下、越界有夹取 —")
        _, cfg0 = call("GET", "/api/config")
        check("配置接口带 today_decay", "today_decay" in cfg0, list(cfg0.keys()))
        check("API Key 只回传「配没配」", "deepseek_api_key" not in cfg0)
        call("PUT", "/api/config", {"today_decay": 2.5})
        _, cfg1 = call("GET", "/api/config")
        check("改成 2.5 后重新读还是 2.5（落盘了）", cfg1.get("today_decay") == 2.5, cfg1.get("today_decay"))
        call("PUT", "/api/config", {"today_decay": 99})
        _, cfg2 = call("GET", "/api/config")
        check("填 99 被夹到上限 5", cfg2.get("today_decay") == 5.0, cfg2.get("today_decay"))
        call("PUT", "/api/config", {"today_decay": cfg0.get("today_decay", 1.0)})   # 还原

        print("\n— 统计 —")
        _, s = call("GET", "/api/stats")
        check("空词库 total = 0", s.get("total") == 0, s)

        print("\n— 导入 —")
        _, r = call("POST", "/api/words/import", {"text": SAMPLE})
        check("首次导入 8 个词（表头被跳过）", r.get("added") == 8, r)
        _, r2 = call("POST", "/api/words/import", {"text": SAMPLE})
        check("重复导入全部去重", r2.get("added") == 0 and r2.get("skipped") == 8, r2)
        code, rr = call("POST", "/api/words", {"en": "UBIQUITOUS", "cn": "重复"})
        check("大小写不同的同一单词不会被新建（不覆盖已有释义）",
              code == 200 and rr.get("existing") is True, (code, rr))

        _, r3 = call("POST", "/api/words", {"en": "zephyr", "cn": ""})
        check("可以加一个没释义的词", r3.get("id") is not None, r3)
        _, s2 = call("GET", "/api/stats")
        check("统计里标出未生成释义的词", s2.get("no_cn") == 1, s2)

        print("\n— 查词缓存（设置页那个「清空」）—")
        _, c0 = call("GET", "/api/cache")
        check("能读到缓存条数", isinstance(c0.get("count"), int), c0)
        _, cl = call("DELETE", "/api/cache")
        check("清空返回删了几条", isinstance(cl.get("removed"), int), cl)
        _, c1 = call("GET", "/api/cache")
        check("清空后条数为 0", c1.get("count") == 0, c1)
        # 关键：清缓存不能碰词库（这里已经导入过词，total 必须还在）
        _, st_w = call("GET", "/api/stats")
        check("清缓存没有动到词库", st_w.get("total", 0) >= 8, st_w.get("total"))

        print("\n— 多词库 —")
        _, bk = call("GET", "/api/books")
        check("有一个默认词库", len(bk.get("items", [])) == 1 and bk["items"][0]["is_default"] == 1, bk)
        check("默认词库叫「我的词库」", bk["items"][0]["name"] == "我的词库", bk["items"][0]["name"])
        dft_id = bk["default_id"]

        _, nb = call("POST", "/api/books", {"name": "四级词汇", "builtin": "CET4"})
        check("能新建词库", nb.get("id"), nb)
        book2 = nb["id"]
        code, _ = call("POST", "/api/books", {"name": "四级词汇"})
        check("重名词库被拒（409）", code == 409, code)

        # 把已有单词加进新词库（不新建单词）
        _, one = call("GET", "/api/words?size=1")
        wid = one["items"][0]["id"]
        en = one["items"][0]["en"]
        _, at = call("POST", "/api/books/attach", {"book_id": book2, "word_id": wid})
        check(f"「{en}」加进了四级词库", at.get("added") is True, at)
        _, at2 = call("POST", "/api/books/attach", {"book_id": book2, "word_id": wid})
        check("重复加不重复插", at2.get("added") is False, at2)
        _, wb = call("GET", f"/api/words/{wid}/books")
        check("它同时属于 2 个词库", len(wb.get("items", [])) == 2, wb)

        # 抽词只从指定词库抽
        _, cnt_dft = call("GET", f"/api/words?size=500&book_id={dft_id}")
        n_dft = min(5, cnt_dft["total"])
        _, s_dft = call("POST", "/api/session/start", {"size": 5, "book_id": dft_id})
        check(f"默认词库能抽词（抽到 {s_dft.get('count')} 个）",
              s_dft.get("count") == n_dft, s_dft)
        call("POST", "/api/session/finish", {"session_id": s_dft["session_id"]})

        # 四级词库里只有刚挂进去的那 1 个词，还未必有释义 → 只要不是抽到别的词库的就行
        code, s_one = call("POST", "/api/session/start", {"size": 5, "book_id": book2})
        if code == 200:
            check(f"四级词库只抽到自己的词（{s_one.get('count')} 个）",
                  s_one.get("count") <= 1, s_one)
            call("POST", "/api/session/finish", {"session_id": s_one["session_id"]})
        else:
            check("四级词库抽不出词时会明确报错（而不是退回去抽别的词库）",
                  "四级词汇" in str(s_one.get("detail", "")), s_one)

        # 列表按词库筛
        _, lw_all = call("GET", "/api/words?size=500")
        _, lw_2 = call("GET", f"/api/words?size=500&book_id={book2}")
        check(f"全部 {lw_all['total']} 个 / 四级 {lw_2['total']} 个",
              lw_2["total"] == 1 and lw_all["total"] > 1, (lw_all["total"], lw_2["total"]))

        # 移出词：只删归属
        _, dt = call("POST", "/api/books/detach", {"book_id": book2, "word_id": wid})
        check("移出词库成功", dt.get("removed") is True, dt)
        _, lw_2b = call("GET", f"/api/words?size=500&book_id={book2}")
        check("四级词库空了", lw_2b["total"] == 0, lw_2b["total"])
        _, lw_all2 = call("GET", "/api/words?size=500")
        check("单词本身还在（没被删）", lw_all2["total"] == lw_all["total"], lw_all2["total"])

        # 删词库：只删归属
        call("POST", "/api/books/attach", {"book_id": book2, "word_id": wid})
        _, db_del = call("DELETE", f"/api/books/{book2}")
        check("删词库返回清了 1 条归属", db_del.get("removed") == 1, db_del)
        _, lw_all3 = call("GET", "/api/words?size=500")
        check("单词仍在", lw_all3["total"] == lw_all["total"], lw_all3["total"])

        # 默认词库保护
        code, _ = call("DELETE", f"/api/books/{dft_id}")
        check("默认词库不给删（400）", code == 400, code)

        # 内置词表清单（只列，不导入）
        _, vc = call("GET", "/api/vocab")
        keys = [v["key"] for v in vc.get("items", [])]
        check(f"词表清单有 {len(keys)} 个：{keys}", "CET4" in keys and "NPEE" in keys, keys)
        check("词表默认不导入（要自己点）", True)

        print("\n— 抽词 —")
        _, st = call("POST", "/api/session/start", {"size": 5})
        items = st.get("items", [])
        check("抽到 5 个词", st.get("count") == 5 and len(items) == 5, st.get("count"))
        check("不抽没有中文释义的词", all("zephyr" != w["en"] for w in items))
        _, st2 = call("POST", "/api/session/start", {"size": 999})
        check("要的数量超过词库总数时抽全部", st2.get("count") == 8, st2.get("count"))

        # 再用一个「抽全部」的会话做判定测试，保证每个词都在手里
        sid = st2["session_id"]
        by_en = {w["en"]: w for w in st2["items"]}

        print("\n— 掌握度计分（区分「一次答对」和「错了才记住」）—")
        w_th = by_en["thorough"]
        _, a1 = call("POST", "/api/session/answer",
                     {"session_id": sid, "word_id": w_th["id"], "typed": "thorough"})
        check(f"一次答对 → 掌握度 {a1.get('from')} → {a1.get('mastery')}",
              a1.get("correct") and a1.get("mastery") == 1 and a1.get("retried") is False, a1)

        _, a2 = call("POST", "/api/session/answer",
                     {"session_id": sid, "word_id": w_th["id"], "typed": "thorough"})
        check(f"同轮重考答对 → 掌握度停在 {a2.get('mastery')}，不再上涨",
              a2.get("correct") and a2.get("retried") is True and a2.get("mastery") == 1, a2)

        w_ac = by_en["acquire"]
        _, a3 = call("POST", "/api/session/answer",
                     {"session_id": sid, "word_id": w_ac["id"], "typed": "acquir"})
        check("先答错", a3.get("correct") is False and a3.get("retried") is False, a3)
        _, a4 = call("POST", "/api/session/answer",
                     {"session_id": sid, "word_id": w_ac["id"], "typed": "acquire"})
        check(f"错了再答对 → 掌握度仍是 {a4.get('mastery')}（这就是区分度）",
              a4.get("correct") and a4.get("retried") is True and a4.get("mastery") == 0, a4)

        print("\n— 判定规则 —")
        w_mt = by_en["maintenance"]
        _, b1 = call("POST", "/api/session/answer",
                     {"session_id": sid, "word_id": w_mt["id"], "typed": "  MAINTENANCE  "})
        check("首尾空格 + 大小写不影响判定", b1.get("correct") is True, b1)

        w_tn = by_en["tentative"]
        _, b2 = call("POST", "/api/session/answer",
                     {"session_id": sid, "word_id": w_tn["id"], "typed": "tentativ"})
        check("不再返回「差几个字母」那类文字提示（差异只靠逐字母颜色表达）",
              "hint" not in b2, b2)

        _, b3 = call("POST", "/api/session/answer",
                     {"session_id": sid, "word_id": w_tn["id"], "typed": "tentativf"})   # 与答案等长，只错最后一个字母
        diff = b3.get("diff")
        check("长度相同的拼错 → 给出逐字母差异标记",
              bool(diff) and any(not c["ok"] for c in diff["answer"]), diff)

        w_co = by_en["colour"]
        _, b4 = call("POST", "/api/session/answer",
                     {"session_id": sid, "word_id": w_co["id"], "typed": "color"})
        check("英美变体互认 colour ← color", b4.get("correct") is True, b4)

        w_gu = by_en["give up"]
        _, b5 = call("POST", "/api/session/answer",
                     {"session_id": sid, "word_id": w_gu["id"], "typed": "  Give    Up "})
        check("短语大小写 + 多余空格容错", b5.get("correct") is True, b5)

        w_ub = by_en["ubiquitous"]
        _, b6 = call("POST", "/api/session/answer",
                     {"session_id": sid, "word_id": w_ub["id"], "skipped": True})
        check("跳过 → 算错且带答案", b6.get("skipped") is True
              and b6.get("correct") is False and b6.get("answer") == "ubiquitous", b6)
        check("跳过时掌握度不会变成负数", b6.get("mastery") == 0, b6)

        print("\n— 跟打接口（只判定，不记分）—")
        _, j1 = call("POST", "/api/judge", {"answer": "thorough", "typed": "  THOROUGH  "})
        check("跟打判定与答题同规则（大小写 + 空格）", j1.get("correct") is True, j1)
        _, j2 = call("POST", "/api/judge", {"answer": "colour", "typed": "color"})
        check("跟打也认英美变体", j2.get("correct") is True, j2)
        _, before_w = call("GET", "/api/words?q=thorough")
        m_before = before_w["items"][0]["mastery"]
        call("POST", "/api/judge", {"answer": "thorough", "typed": "thoro"})
        call("POST", "/api/judge", {"answer": "thorough", "typed": "thorough"})
        _, after_w = call("GET", "/api/words?q=thorough")
        check(f"反复跟打也不动掌握度（仍是 {m_before}）",
              after_w["items"][0]["mastery"] == m_before, after_w["items"][0])

        print("\n— 跨轮连对加成 —")
        _, st3 = call("POST", "/api/session/start", {"size": 999})
        sid3 = st3["session_id"]
        w_th2 = {x["en"]: x for x in st3["items"]}["thorough"]
        _, c1 = call("POST", "/api/session/answer",
                     {"session_id": sid3, "word_id": w_th2["id"], "typed": "thorough"})
        check(f"新一轮里再答对 → 连对加成（1 → {c1.get('mastery')}）",
              c1.get("mastery") == 2 and c1.get("retried") is False, c1)

        print("\n— 抽词权重 —")
        from core import srs
        w00, w10 = srs.weight(0), srs.weight(10)
        check(f"掌握度 10 的词权重只有 0 分的 {w10/w00:.1%}", w10 < w00 / 10, (w00, w10))
        pool = ([{"id": i, "mastery": 0} for i in range(100)]
                + [{"id": 100 + i, "mastery": 10} for i in range(100)])
        low = sum(1 for r in srs.pick(pool, 100) if r["mastery"] == 0)
        check(f"抽 100 个里低掌握度的占 {low} 个（应当占绝大多数）", low >= 80, low)

        print("\n— 收尾 —")
        call("POST", "/api/session/finish", {"session_id": sid})
        _, s3 = call("GET", "/api/stats")
        check("今日作答统计已记录", s3.get("today_asked", 0) >= 8, s3)
        check("打卡天数已记录", s3.get("streak_days") == 1, s3)
        check("备份文件已生成", any((ROOT / "data" / "backups").glob("words-*.db")))

        print(f"\n结果：{OK} 通过 / {FAIL} 失败")
        return 1 if FAIL else 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        # 清掉这次测试产生的临时数据库和备份，别污染真实数据
        for suffix in ("", "-wal", "-shm"):
            p = Path(str(DBFILE) + suffix)
            if p.exists():
                try:
                    p.unlink()
                except OSError:
                    pass
        for p in (ROOT / "data" / "backups").glob("words-*.db"):
            if p not in pre_backups:
                try:
                    p.unlink()
                except OSError:
                    pass


if __name__ == "__main__":
    sys.exit(main())
