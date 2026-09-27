"""竹喧 · 把词库里所有单词按**最新的释义编排规则**重刷一遍

⚠️ 会**覆盖**词库里现有的中文释义（包括你手动改过的）。
   只在改了 `core/dictionary.py` 的释义规则之后跑它，平时别跑。

    .venv/Scripts/python.exe tests/refresh_words.py [--dry]

    --dry  只打印会变成什么样，不写入
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8765"
DRY = "--dry" in sys.argv


def call(method: str, path: str, payload=None):
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(BASE + path, data=body, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def main() -> int:
    try:
        data = call("GET", "/api/words?size=5000")
    except Exception as exc:
        print(f"连不上竹喧服务（{BASE}）：{exc}")
        return 2

    items = data.get("items", [])
    print(f"词库共 {len(items)} 个词" + ("　—— 预演模式，不写入\n" if DRY else "\n"))

    changed = same = failed = 0
    for w in items:
        try:
            r = call("POST", "/api/lookup", {"en": w["en"], "force": True})   # 忽略缓存重查
        except urllib.error.HTTPError as exc:
            print(f"  ✗ {w['en']:18} HTTP {exc.code}")
            failed += 1
            continue

        if not r.get("ok"):
            print(f"  ✗ {w['en']:18} {r.get('reason')}")
            failed += 1
            continue

        if r["cn"] == w["cn"] and r["pos"] == w["pos"] and r["ph"] == w["ph"]:
            same += 1
            continue

        print(f"  ✓ {w['en']:18} [{w['pos']}] {w['cn'][:30]}")
        print(f"    {'':18} [{r['pos']}] {r['cn']}")
        if not DRY:
            call("PUT", f"/api/words/{w['id']}", {
                "en": w["en"], "cn": r["cn"], "pos": r["pos"],
                "ph": r["ph"], "note": w.get("note", ""),
            })
        changed += 1
        time.sleep(0.05)

    print(f"\n{'会改动' if DRY else '已改动'} {changed} 个，无变化 {same} 个，失败 {failed} 个")
    return 0


if __name__ == "__main__":
    sys.exit(main())
