"""竹喧 · 修正旧 bug 造成的虚高掌握度

**背景**：修复前「同一轮里重考答对」也会加掌握度，导致一轮背下来所有词都变成 1，
掌握度失去区分度。这个脚本按真实表现把多加的分扣回去：

    对每个词：掌握度 -= （历史上「重考才答对」的次数），最低 0；连对数一并清零

⚠️ **只跑一次**。修复后的逻辑「重考答对」不再加分，再跑就会误扣。
   执行前会自动把数据库备份到 data/backups/。

    .venv/Scripts/python.exe tests/fix_mastery.py            # 预演，只看不改
    .venv/Scripts/python.exe tests/fix_mastery.py --apply    # 真正执行
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DB = ROOT / "data" / "words.db"
BACKUP_DIR = ROOT / "data" / "backups"
APPLY = "--apply" in sys.argv

# 「重考才答对」= 同一轮（同 session）里，这次答对之前这个词已经被答过一次以上
QUERY = """
SELECT w.id, w.en, w.mastery, w.streak,
  (SELECT COUNT(*) FROM answers a
    WHERE a.word_id = w.id AND a.result = 'right'
      AND EXISTS (SELECT 1 FROM answers b
                  WHERE b.session_id = a.session_id
                    AND b.word_id = a.word_id AND b.id < a.id)
  ) AS retry_right
FROM words w
ORDER BY retry_right DESC, w.mastery DESC, w.en
"""


def main() -> int:
    if not DB.exists():
        print(f"找不到数据库：{DB}")
        return 2

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    before = conn.execute("SELECT COUNT(*) n, SUM(mastery) s FROM words").fetchone()
    print(f"修正前：{before['n']} 个词，掌握度总和 {before['s']}")

    targets = [dict(r) for r in conn.execute(QUERY).fetchall() if r["retry_right"] > 0]
    print(f"受影响的词：{len(targets)} 个\n")

    if not targets:
        print("没有需要修正的词。")
        conn.close()
        return 0

    print(f"{'单词':<22}{'掌握度':>8}{'连对':>6}{'重考答对':>10}{'修正后':>8}")
    print("-" * 58)
    total_before = total_after = 0
    for r in targets:
        new_m = max(0, r["mastery"] - r["retry_right"])
        total_before += r["mastery"]
        total_after += new_m
        print(f"{r['en']:<22}{r['mastery']:>8}{r['streak']:>6}"
              f"{r['retry_right']:>10}{new_m:>8}")

    print("-" * 58)
    print(f"{'合计':<22}{total_before:>8}{'':>6}{'':>10}{total_after:>8}")

    if not APPLY:
        print("\n这是预演，什么都没改。要真正执行：加 --apply")
        conn.close()
        return 0

    # 先备份
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = BACKUP_DIR / f"words-修正掌握度前-{stamp}.db"
    try:
        conn.execute("VACUUM INTO ?", (str(target),))
        print(f"\n已备份：{target.name}")
    except Exception as exc:
        print(f"\n备份失败（{exc}），为安全起见中止。")
        conn.close()
        return 1

    for r in targets:
        new_m = max(0, r["mastery"] - r["retry_right"])
        conn.execute("UPDATE words SET mastery = ?, streak = 0 WHERE id = ?", (new_m, r["id"]))
    conn.commit()

    after = conn.execute("SELECT COUNT(*) n, SUM(mastery) s FROM words").fetchone()
    print(f"已修正 {len(targets)} 个词")
    print(f"修正后：{after['n']} 个词，掌握度总和 {after['s']}")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
