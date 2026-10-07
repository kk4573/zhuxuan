"""竹喧 · 答案判定

规则（和 确认过的）：
  1. 忽略大小写、首尾空格、短语中间的多余空格
  2. 英式和美式拼写互认（color / colour 都算对）
  3. 只有真拼错才算错，但会给"只差 N 个字母"这类提示
  4. 不做首字母提示

⚠️ 英美变体**只查别名表，绝不用规则批量转换**。
   因为规则转换会产生假阳性，实测过的坑：
       /our$/ → /or$/   会把  four → for      （用户打 for 会被判对）
       /ise$/ → /ize$/  会把  promise → promize
   所以宁可表短一点、准一点，遇到没收录的词再往表里加。
"""
from __future__ import annotations

import re

# 英式 → 美式（值必须是"规范形式"，不能同时又是别的键，否则会形成链式转换）
ALIAS = {
    # -our / -or
    "colour": "color", "colours": "colors", "coloured": "colored",
    "behaviour": "behavior", "behaviours": "behaviors",
    "favour": "favor", "favourite": "favorite", "favourites": "favorites",
    "favourable": "favorable", "honour": "honor", "honourable": "honorable",
    "humour": "humor", "humorous": "humorous",
    "labour": "labor", "neighbour": "neighbor", "neighbours": "neighbors",
    "neighbourhood": "neighborhood", "rumour": "rumor", "flavour": "flavor",
    "harbour": "harbor", "vapour": "vapor", "armour": "armor",
    "savour": "savor", "endeavour": "endeavor", "rigour": "rigor",
    "splendour": "splendor", "tumour": "tumor", "vigour": "vigor",
    "clamour": "clamor", "odour": "odor", "parlour": "parlor",
    "saviour": "savior", "behavioural": "behavioral",
    # -re / -er
    "centre": "center", "centres": "centers", "central": "central",
    "theatre": "theater", "metre": "meter", "metres": "meters",
    "litre": "liter", "litres": "liters", "fibre": "fiber",
    "sombre": "somber", "spectre": "specter", "calibre": "caliber",
    "lustre": "luster", "mitre": "miter", "sabre": "saber",
    # -ise / -ize
    "realise": "realize", "realised": "realized", "organise": "organize",
    "organised": "organized", "organisation": "organization",
    "recognise": "recognize", "recognised": "recognized",
    "analyse": "analyze", "analysed": "analyzed", "criticise": "criticize",
    "criticised": "criticized", "apologise": "apologize",
    "memorise": "memorize", "specialise": "specialize",
    "summarise": "summarize", "emphasise": "emphasize",
    "minimise": "minimize", "maximise": "maximize", "utilise": "utilize",
    "civilise": "civilize", "characterise": "characterize",
    "familiarise": "familiarize", "generalise": "generalize",
    "modernise": "modernize", "normalise": "normalize", "penalise": "penalize",
    "prioritise": "prioritize", "publicise": "publicize",
    "standardise": "standardize", "symbolise": "symbolize",
    "sympathise": "sympathize", "visualise": "visualize",
    # -ce / -se
    "practise": "practice", "licence": "license", "defence": "defense",
    "offence": "offense", "pretence": "pretense",
    # 双写 l
    "travelled": "traveled", "travelling": "traveling", "traveller": "traveler",
    "cancelled": "canceled", "cancelling": "canceling",
    "modelled": "modeled", "modelling": "modeling",
    "labelled": "labeled", "labelling": "labeling",
    "signalled": "signaled", "signalling": "signaling",
    "fuelled": "fueled", "fuelling": "fueling", "marvellous": "marvelous",
    "jewellery": "jewelry", "counsellor": "counselor",
    "counselling": "counseling", "enrolment": "enrollment",
    "fulfil": "fulfill", "instalment": "installment", "skilful": "skillful",
    "wilful": "willful",
    # 其他
    "grey": "gray", "programme": "program", "catalogue": "catalog",
    "dialogue": "dialog", "cheque": "check", "kerb": "curb",
    "plough": "plow", "mould": "mold", "smoulder": "smolder",
    "tyre": "tire", "aluminium": "aluminum", "aeroplane": "airplane",
    "storey": "story", "enquiry": "inquiry", "cosy": "cozy",
    "moustache": "mustache", "omelette": "omelet", "manoeuvre": "maneuver",
    "sceptic": "skeptic", "sceptical": "skeptical", "disc": "disk",
    "aesthetic": "esthetic", "gaol": "jail", "draught": "draft",
    "tonne": "ton", "speciality": "specialty", "sulphur": "sulfur",
    "haemoglobin": "hemoglobin", "leukaemia": "leukemia",
}


def canon(s: str) -> str:
    """把一个词规范化成可以比较的形式。"""
    s = (s or "").strip().lower()
    s = s.replace("\u2019", "'").replace("\u2018", "'")      # 弯引号 → 直引号
    s = re.sub(r"\s+", " ", s)                                # 内部连续空格归一
    s = re.sub(r"^[^a-z0-9]+", "", s)                         # 去首部非字母数字
    s = re.sub(r"[^a-z0-9]+$", "", s)                         # 去尾部非字母数字
    if s in ALIAS:
        return ALIAS[s]
    return s


def levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def judge(typed: str, answer: str) -> dict:
    """判定一次作答。返回 {correct, distance}

    只给结论，不给「差几个字母」那类文字提示 —— 那个在输入完全不相干时
    会给出误导性的结论（实际使用中发现的）。差异靠前端的逐字母颜色标记表达。
    """
    t, a = canon(typed), canon(answer)
    correct = bool(a) and t == a
    return {"correct": correct, "distance": levenshtein(t, a)}


def mark_diff(typed: str, answer: str) -> dict | None:
    """逐字母对齐标记（只在两者长度相同时给），前端据此高亮差异。

    返回 {"typed": [{"c": "a", "ok": true}, ...], "answer": [...]}，长度不同则返回 None。
    """
    t, a = (typed or "").strip(), (answer or "").strip()
    if not a or len(t) != len(a):
        return None
    mt, ma = [], []
    for x, y in zip(t, a):
        ok = x.lower() == y.lower()
        mt.append({"c": x, "ok": ok})
        ma.append({"c": y, "ok": ok})
    return {"typed": mt, "answer": ma}
