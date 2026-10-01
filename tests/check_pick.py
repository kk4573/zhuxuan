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

print("\n— 可从设置里调：today_decay 传不同值应当有不同强度 —")
check("设 0 → 等于关掉抑制", abs(srs.weight(0, 1, 0.0) - 1.0) < 1e-9, srs.weight(0, 1, 0.0))
check("设 0.5 → 考过 1 次降到 2/3", abs(srs.weight(0, 1, 0.5) - 1 / 1.5) < 1e-9, srs.weight(0, 1, 0.5))
check("设 1（默认）→ 打对折", abs(srs.weight(0, 1, 1.0) - 0.5) < 1e-9, srs.weight(0, 1, 1.0))
check("设 2 → 降到 1/3", abs(srs.weight(0, 1, 2.0) - 1 / 3) < 1e-9, srs.weight(0, 1, 2.0))
check("设 5 → 降到 1/6", abs(srs.weight(0, 1, 5.0) - 1 / 6) < 1e-9, srs.weight(0, 1, 5.0))
check("负数按 0 处理（不会反过来放大）", abs(srs.weight(0, 3, -5) - 1.0) < 1e-9, srs.weight(0, 3, -5))
check("不传参数 = 用模块默认值", srs.weight(0, 1) == srs.weight(0, 1, srs.TODAY_DECAY))

print("\n— 设置里调到 0 时，抽词分布回到不抑制 —")
pool_z = [
    {"id": 7, "mastery": 2, "today_asked": 0, "tag": "A"},
    {"id": 8, "mastery": 2, "today_asked": 3, "tag": "B"},
]
cnt_z = Counter()
for _ in range(ROUNDS):
    for row in srs.pick(pool_z, 1, today_decay=0.0):
        cnt_z[row["tag"]] += 1
print("    关掉抑制：", dict(cnt_z))
check("关掉后 A / B 接近各半",
      abs(cnt_z["A"] - cnt_z["B"]) / ROUNDS < 0.06, dict(cnt_z))

cnt_s = Counter()
for _ in range(ROUNDS):
    for row in srs.pick(pool_z, 1, today_decay=1.0):
        cnt_s[row["tag"]] += 1
print("    默认抑制：", dict(cnt_s))
check("开启后 B（今天考过 3 次）明显少于 A", cnt_s["B"] < cnt_s["A"] * 0.6, dict(cnt_s))

print("\n— 配置项的取值夹取 —")
sys.path.insert(0, str(ROOT))
from core import config as cfg  # noqa: E402
check("正常值原样保留", cfg.clamp_decay(1.5) == 1.5, cfg.clamp_decay(1.5))
check("超上限夹到 5", cfg.clamp_decay(99) == 5.0, cfg.clamp_decay(99))
check("负数夹到 0", cfg.clamp_decay(-3) == 0.0, cfg.clamp_decay(-3))
check("垃圾值退回默认 1", cfg.clamp_decay("abc") == 1.0, cfg.clamp_decay("abc"))
check("空值退回默认 1", cfg.clamp_decay(None) == 1.0, cfg.clamp_decay(None))
check("默认配置里有这一项", "today_decay" in cfg.DEFAULTS)
check("不会外传密钥（顺带确认）", "deepseek_api_key" not in cfg.public_view(),
      list(cfg.public_view().keys()))
check("前端能读到这个值", "today_decay" in cfg.public_view())

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
