"""竹喧 · 内置词表（四级 / 六级 / 考研 / 托福 / GRE）

词表来自公开的 GitHub 仓库，通过加速镜像下载（本机直连 github 不通）。
下载后缓存在 `data/vocab/` 里，之后再导入就不用重复下载了。

词表文件**自带音标和释义**，所以导入几千个词不需要联网查词典。
"""
from __future__ import annotations

import re
import urllib.parse
import urllib.request
from pathlib import Path

from .paths import DATA_DIR

CACHE_DIR = DATA_DIR / "vocab"

# 词表来源（同一个仓库，通过加速镜像取；三个镜像都能用，按顺序试）
SOURCES = [
    "https://ghfast.top/https://raw.githubusercontent.com/mahavivo/english-wordlists/master/",
    "https://cdn.jsdelivr.net/gh/mahavivo/english-wordlists@master/",
    "https://gh-proxy.com/https://raw.githubusercontent.com/mahavivo/english-wordlists/master/",
]

VOCABULARIES = [
    {"key": "CET4",  "name": "四级词汇", "file": "CET4_edited.txt",        "expect": 4615},
    {"key": "CET6",  "name": "六级词汇", "file": "CET6_edited.txt",        "expect": 2273},
    {"key": "NPEE",  "name": "考研词汇", "file": "NPEE_Wordlist.txt",      "expect": 5398},
    {"key": "TOEFL", "name": "托福词汇", "file": "TOEFL.txt",              "expect": 4516},
    {"key": "GRE",   "name": "GRE 词汇", "file": "GRE_8000_Words.txt",     "expect": 8000},
]

_BY_KEY = {v["key"]: v for v in VOCABULARIES}

# 一行形如：  abandon [əˈbændən] vt.丢弃；放弃，抛弃
# 也有的没有音标：a art.一(个)；每一(个)
_LINE_RE = re.compile(r"^([A-Za-z][A-Za-z'’\-]*(?:\s+[A-Za-z'’\-]+){0,3})\s*(?:\[([^\]]+)\])?\s*(.+)$")

# 释义里的编号（词表用 "v. 1. 抛弃 2. 离弃" 这种写法，统一成 "v. 抛弃；离弃"）
_NUM_RE = re.compile(r"(?:^|[\s;；])[0-9１-９]\s*[.、)）]\s*")

# 词性缩写。需要它是因为有的词条写成「a art.一(个)；每一(个)」——
# 没有了它，正则会把 "a art" 当成一个短语，后面就全错位了。
POS_WORDS = {
    "a", "ad", "adv", "adj", "art", "aux", "conj", "int", "n", "num",
    "prep", "pron", "v", "vi", "vt", "abbr", "ad", "pl", "sing",
}


def info(key: str) -> dict | None:
    v = _BY_KEY.get((key or "").upper())
    if not v:
        return None
    out = dict(v)
    out["cached"] = (CACHE_DIR / v["file"]).exists()
    return out


def list_all() -> list[dict]:
    return [info(v["key"]) for v in VOCABULARIES]


def fetch(key: str, force: bool = False) -> Path:
    """把词表文件弄到本地（有缓存就直接用）。返回本地路径。"""
    v = _BY_KEY.get((key or "").upper())
    if not v:
        raise ValueError(f"没有这个词表：{key}")

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    target = CACHE_DIR / v["file"]
    if target.exists() and not force:
        return target

    last = None
    for base in SOURCES:
        try:
            req = urllib.request.Request(
                base + urllib.parse.quote(v["file"]),
                headers={"User-Agent": "Mozilla/5.0"},
            )
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read()
            if len(data) < 2000:
                raise ValueError("下载到的内容太小，可能不是词表")
            target.write_bytes(data)
            return target
        except Exception as exc:
            last = exc
    raise RuntimeError(f"下载词表失败（三个镜像都试过了）：{last}")


def parse(text: str) -> list[dict]:
    """把词表文本解析成 [{en, ph, cn}]。

    格式不统一，所以尽量宽容：跳过标题行、章节字母行、明显不是词条的行。
    """
    out: list[dict] = []
    seen: set[str] = set()

    for raw in text.split("\n"):
        line = raw.strip().lstrip("\ufeff")
        if not line:
            continue
        # 标题 / 计数 / 章节字母
        if line.startswith("#") or "（共" in line or "(共" in line or re.match(r"^[A-Z]$", line):
            continue
        if "单词表" in line or "词汇表" in line:
            continue

        m = _LINE_RE.match(line)
        if not m:
            continue
        en, ph, cn = m.group(1).strip(), (m.group(2) or "").strip(), m.group(3).strip()

        # 「a art.一(个)」这种：词性缩写被吞进英文里了，切回去
        parts = en.split()
        for i in range(1, len(parts)):
            if parts[i].lower() in POS_WORDS:
                head = " ".join(parts[:i])
                tail = " ".join(parts[i:]) + (f" [{ph}]" if ph else "") + " " + cn
                en, ph, cn = head, "", tail
                break

        # 英文部分必须是纯字母（可带连字符/撇号），否则是噪声
        if not re.fullmatch(r"[A-Za-z][A-Za-z'’\-]*(?:\s+[A-Za-z'’\-]+){0,3}", en):
            continue
        if not cn:
            continue
        key = en.lower()
        if key in seen:
            continue
        seen.add(key)

        out.append({"en": en, "ph": ph, "cn": tidy_cn(cn)})

    return out


def tidy_cn(cn: str) -> str:
    """把词表的释义整理成竹喧现在用的风格。

    词表里常见「v. 1. 抛弃，放弃 2. 离弃(家园)」这种编号写法，
    统一成「v. 抛弃，放弃；离弃(家园)」；顺带把空白和分隔符归一。
    """
    s = cn.replace("\u3000", " ").strip()
    s = re.sub(r"\s+", " ", s)
    s = _NUM_RE.sub("；", s)                 # 去掉义项编号
    s = re.sub(r"[;；]\s*[;；]+", "；", s)     # 连续分号
    s = re.sub(r"\s*[,，]\s*", "，", s)        # 逗号前后不留空格
    s = re.sub(r"\s*[;；]\s*", "；", s)
    s = re.sub(r"^[;；\s]+", "", s)
    s = re.sub(r"[;；\s]+$", "", s)
    # 去掉编号后留下的空义项：「v. ；抛弃」→「v. 抛弃」
    s = re.sub(r"([a-zA-Z]\.)\s*[;；]\s*", r"\1 ", s)
    s = re.sub(r"(^|\s)[;；]\s*", r"\1", s)
    s = re.sub(r"[;；]\s*[;；]", "；", s)
    # 点号前不留空格：「art .一」→「art.一」
    s = re.sub(r"([a-zA-Z])\s+\.", r"\1.", s)
    # 词性后面留一个空格： "vt.放弃" → "vt. 放弃"
    s = re.sub(r"\b([a-zA-Z]{1,5}\.)(?=[^\s])", r"\1 ", s)
    s = re.sub(r"\s{2,}", " ", s)
    return s.strip()

