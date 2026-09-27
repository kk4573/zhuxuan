"""竹喧 · 放一批演示单词进去（第一次打开就有东西可看）

    .venv/Scripts/python.exe tests/seed_demo.py

单词已经存在会自动跳过，可以重复跑。
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8765"

WORDS = "\n".join([
    "ubiquitous\t无处不在的；普遍存在的\tadj.",
    "tentative\t试探性的；暂定的\tadj.",
    "thorough\t彻底的；周密的\tadj.",
    "acquire\t获得；学到\tv.",
    "colleague\t同事\tn.",
    "maintenance\t维护；保养\tn.",
    "give up\t放弃；认输\tphr.",
    "colour\t颜色\tn.",
    "curious\t好奇的\tadj.",
    "anxious\t焦虑的；担心的\tadj.",
    "recommend\t推荐；建议\tv.",
    "persuade\t说服；劝服\tv.",
])


def main() -> None:
    body = json.dumps({"text": WORDS}).encode("utf-8")
    req = urllib.request.Request(
        BASE + "/api/words/import", data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            r = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        print("失败：", exc.read().decode("utf-8"))
        return
    print(f"新增 {r['added']} 个，跳过已存在的 {r['skipped']} 个")


if __name__ == "__main__":
    main()
