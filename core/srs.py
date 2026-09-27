"""竹喧 · 掌握度模型与抽词算法

核心思想：越不熟的词，被抽到的概率越高；越熟的词出现得越少，但永远不会是 0
（保证生僻词、久未复习的词不会被漏掉）。

    权重 = 1 / (1 + 掌握度) ^ WEIGHT_POW

    掌握度  0    1     2     3    5     8     10
    权重   1.00 0.35  0.19  0.13 0.065 0.032 0.022
"""
from __future__ import annotations

import math
import random

# 指数越大，抽词越集中在低掌握度的词上。想调"复习强度"就改这一个数。
WEIGHT_POW = 1.5

MASTERED_LINE = 10          # 显示上算"精通"的门槛（内部数值继续涨，不封顶）


def weight(mastery: int) -> float:
    return 1.0 / (1.0 + max(0, int(mastery))) ** WEIGHT_POW


def pick(pool: list[dict], n: int) -> list[dict]:
    """按权重无放回地抽 n 个词。

    用 Efraimidis-Spirakis 加权抽样：给每个词生成 key = log(u) / w，
    取 key 最大的 n 个。等价于 u^(1/w) 取最大，但对大权重的数值更稳定。
    """
    n = min(max(0, int(n)), len(pool))
    if n == 0:
        return []
    if n == len(pool):
        picked = list(pool)
        random.shuffle(picked)
        return picked
    keyed = []
    for row in pool:
        w = weight(row["mastery"])
        u = random.uniform(1e-12, 1.0)
        keyed.append((math.log(u) / w, row))
    keyed.sort(key=lambda t: t[0], reverse=True)     # 越大越优先
    return [row for _, row in keyed[:n]]


def apply_right(word: dict) -> tuple[int, int, int]:
    """答对：掌握度 +1，连对时递增加成（+1/+2/+3 封顶）。

    返回 (新掌握度, 新连对数, 本次增量)。
    """
    streak = int(word.get("streak") or 0) + 1
    gain = min(streak, 3)
    mastery = max(0, int(word.get("mastery") or 0)) + gain
    return mastery, streak, gain


def apply_wrong(word: dict) -> tuple[int, int, int]:
    """答错或跳过：掌握度 -2（最低 0），连对数清零。

    返回 (新掌握度, 新连对数, 本次增量)。
    """
    mastery = max(0, int(word.get("mastery") or 0) - 2)
    return mastery, 0, mastery - max(0, int(word.get("mastery") or 0))
