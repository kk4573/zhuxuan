"""竹喧 · 抽词算法测试

验证两件事：
  1. 掌握度加权本身没坏（越熟越少出现）
  2. 新增的「当天已考惩罚」真的在起作用（同一天考过的词明显更难再被抽到）

    .venv/Scripts/python.exe tests/check_pick.py
"""
from __future__ import annotations

import random
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import srs  # noqa: E402

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


print("— 权重公式 —")
check("掌握度 0、当天没考过 → 1.000", abs(srs.weight(0, 0) - 1.0) < 1e-9, srs.weight(0, 0))
check("掌握度 1 → 约 0.354", abs(srs.weight(1, 0) - 0.3536) < 0.001, srs.weight(1, 0))
check("掌握度 3 → 约 0.125", abs(srs.weight(3, 0) - 0.125) < 0.001, srs.weight(3, 0))
check("当天考过 1 次 → 打对折", abs(srs.weight(0, 1) - 0.5) < 1e-9, srs.weight(0, 1))
check("当天考过 3 次 → 降到 1/4", abs(srs.weight(0, 3) - 0.25) < 1e-9, srs.weight(0, 3))
check("考得越多权重越低",
      srs.weight(0, 0) > srs.weight(0, 1) > srs.weight(0, 2) > srs.weight(0, 5))

print("\n— 实际抽词：同一天考过的词，被抽中的次数应当明显减少 —")
random.seed(20260927)
pool = [
    {"id": 1, "mastery": 2, "today_asked": 0, "tag": "今天没考过"},
    {"id": 2, "mastery": 2, "today_asked": 1, "tag": "今天考过 1 次"},
    {"id": 3, "mastery": 2, "today_asked": 3, "tag": "今天考过 3 次"},
]
cnt = Counter()
ROUNDS = 3000
for _ in range(ROUNDS):
    for row in srs.pick(pool, 1):
        cnt[row["tag"]] += 1
print("    抽中分布：", dict(cnt))
n0, n1, n3 = cnt["今天没考过"], cnt["今天考过 1 次"], cnt["今天考过 3 次"]
check("没考过的抽中最多", n0 > n1 > n3, dict(cnt))
check(f"考过 1 次的大约减半（{n1} vs {n0}）", 0.38 < n1 / n0 < 0.62, n1 / n0)
check(f"考过 3 次的大约降到 1/4（{n3} vs {n0}）", 0.18 < n3 / n0 < 0.33, n3 / n0)

print("\n— 关掉这个机制（TODAY_DECAY = 0）应当回到旧行为 —")
old_decay = srs.TODAY_DECAY
try:
    srs.TODAY_DECAY = 0.0
    cnt2 = Counter()
    for _ in range(ROUNDS):
        for row in srs.pick(pool, 1):
            cnt2[row["tag"]] += 1
    a, b, c = cnt2["今天没考过"], cnt2["今天考过 1 次"], cnt2["今天考过 3 次"]
    print("    抽中分布：", dict(cnt2))
    check("三者权重相同，分布应该接近（各约 1/3）",
          abs(a - b) / ROUNDS < 0.06 and abs(b - c) / ROUNDS < 0.06, dict(cnt2))
finally:
    srs.TODAY_DECAY = old_decay

print("\n— 掌握度加权仍然有效（回到最初的设计意图）—")
pool2 = [
    {"id": 4, "mastery": 0, "today_asked": 0, "tag": "生词(0)"},
    {"id": 5, "mastery": 3, "today_asked": 0, "tag": "半熟(3)"},
    {"id": 6, "mastery": 9, "today_asked": 0, "tag": "快精通(9)"},
]
cnt3 = Counter()
for _ in range(ROUNDS):
    for row in srs.pick(pool2, 1):
        cnt3[row["tag"]] += 1
print("    抽中分布：", dict(cnt3))
check("生词出现最多，快精通的很少",
      cnt3["生词(0)"] > cnt3["半熟(3)"] > cnt3["快精通(9)"], dict(cnt3))
check("但快精通的也不会完全不出现（不会漏掉）", cnt3["快精通(9)"] > 0, cnt3["快精通(9)"])

print("\n— 边界 —")
check("pool 为空时返回空", srs.pick([], 5) == [])
check("要的比池子大时返回全部", len(srs.pick(pool, 99)) == len(pool))
check("确认取词不去重问题：n=1 只返回 1 个", len(srs.pick(pool, 1)) == 1)

print(f"\n结果：{OK} 通过 / {FAIL} 失败")
sys.exit(1 if FAIL else 0)
