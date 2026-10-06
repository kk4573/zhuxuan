"""竹喧 · 词典查询（有道）+ 本地缓存

实测数据（2026-09-17）：有道网页接口 0.1 秒/词，返回中文释义、英/美音标、考纲标签，
连续查 15 个词无限流；真人发音是标准 MP3（约 10KB/词）。

⚠️ 这是**网页接口不是官方 API**，哪天改版可能失效。所以：
   · 查过的词全部落本地缓存（`dict_cache` 表），二次查询 0 请求
   · 词典不通时，已缓存过的词照常可用，不会卡死
   · 将来接 DeepSeek 兜底时，在这里加一层降级即可
"""
from __future__ import annotations

import json
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request

from . import config
from . import db
from . import ai as ai_mod

JSON_API = "https://dict.youdao.com/jsonapi?q="
VOICE_API = "https://dict.youdao.com/dictvoice?audio={word}&type={t}"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

TIMEOUT = 8.0

# 释义编排规则（kk 定的）
FULL_POS = 2             # 前 2 个词性 …
FULL_MEANINGS = 2        # …各保留 2 个义项
LATER_MEANINGS = 1       # 第 3 个词性起，每个只保留 1 个义项
MAX_POS = 6              # 保险上限，正常不会有这么多词性
MAX_CN_LEN = 120         # 总长上限，超了才截断

POS_RE = re.compile(r"^((?:[a-z]{1,6}\.\s*)+)", re.I)


def _ssl_context() -> ssl.SSLContext:
    """优先用系统证书；万一这台机器上验不过，退回不校验证书（只是查词典，风险可接受）。"""
    try:
        ctx = ssl.create_default_context()
        return ctx
    except Exception:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx


_CTX = _ssl_context()


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT, context=_CTX) as resp:
        return resp.read()


# ---------------------------------------------------------------- 释义处理

def _is_name_entry(s: str) -> bool:
    """词典里的「【名】（Record）（美）勒科尔（人名）」这类条目，背单词用不着。"""
    return any(t in s for t in ("【名】", "【地】", "（人名）", "（地名）", "(人名)", "(地名)"))


def split_meanings(raw: str) -> tuple[str, list[str]]:
    """«n. 苹果；苹果树» → («n.», [«苹果», «苹果树»])"""
    raw = (raw or "").strip()
    m = POS_RE.match(raw)
    pos = m.group(1).strip() if m else ""
    body = raw[m.end():] if m else raw
    return pos, [x.strip() for x in re.split(r"[；;]", body) if x.strip()]


def _word_of(data: dict, entry: dict) -> str:
    """从响应里把「这次查的是哪个词」捞出来（有道的字段形态不固定）。"""
    for cand in (entry.get("return-phrase"), entry.get("word"),
                 data.get("query") if isinstance(data.get("query"), str) else None):
        if isinstance(cand, str) and cand.strip():
            return cand.strip()
    q = data.get("query")
    if isinstance(q, dict):
        for k in ("q", "word", "text"):
            v = q.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
    return ""


def tilde(word: str, cn: str) -> str:
    """释义里出现的**单词本身**用 `~` 代替（牛津词典的写法）。

    例如 abandon 的释义 «放弃，抛弃；abandon oneself to 沉溺于» →
    «放弃，抛弃；~ oneself to 沉溺于»。

    · 只替换**独立的整词**，所以 crystal 的释义里不会把 cry 换掉
    · 大小写不敏感（句首的 Abandon 也换）
    · 短语里的那个词照换（~ oneself to）
    · 常见的派生形（~s / ~ed / ~ing / ~ly …）也一并换成 `~`，
      因为释义里写 "abandoned 被遗弃的" 显然指的就是本词
    """
    if not cn or not word or not isinstance(word, str):
        return cn
    w = word.strip()
    if not w:
        return cn
    # 允许后缀：s / es / ed / d / ing / ly / ment / ness / er / est / ion
    tails = r"(?:s|es|ed|d|ing|ly|ment|ness|er|est|ion)?"
    # 「辅音 + y」结尾的词要额外认一遍变体：cry → cried / cries
    stems = {re.escape(w)}
    if re.search(r"[^aeiouAEIOU]y$", w):
        stems.add(re.escape(w[:-1] + "i"))
    pat = re.compile(r"(?<![A-Za-z])(?:" + "|".join(sorted(stems)) + r")" + tails + r"(?![A-Za-z])",
                     re.I)
    return pat.sub("~", cn)


def _extract(data: dict, word: str = "",
             pos_limit: int | None = None, meaning_count: int | None = None) -> dict | None:
    """把有道返回的 JSON 整理成 {cn, pos, ph}。词典没这个词时返回 None。

    编排规则（kk 定的）：
      · 人名 / 地名条目丢掉
      · 词性**全都保留**
      · 前 2 个词性各留 2 个义项，第 3 个词性起每个只留 1 个义项
      · 同一个义项（按前 4 个字判断）不在不同词性里重复出现

    结果形如：pos = «n. / v. / adj.»，cn = «记录，记载；经历 / 录制 / 创纪录的»
    （cn 里用 « / » 分隔不同词性，用 «；» 分隔同一词性下的义项，和 pos 一一对应）
    """
    entries = (data.get("ec") or {}).get("word") or []
    if not entries:
        return None
    w = entries[0]
    ph = (w.get("usphone") or w.get("ukphone") or "").strip()

    groups: list[tuple[str, list[str]]] = []
    for blk in (w.get("trs") or []):
        for item in (blk.get("tr") or []):
            for s in ((item.get("l") or {}).get("i") or []):
                s = (s or "").strip()
                if not s or _is_name_entry(s):
                    continue
                pos, meanings = split_meanings(s)
                if meanings:
                    groups.append((pos, meanings))
    if not groups:
        return None

    # 保留几个词性 / 每个词性几个义项 —— 由设置决定（默认 全部 + 前 2 个多留一个）
    if pos_limit is None:
        pos_limit = config.clamp_pos_limit(config.get("pos_limit"))
    if meaning_count is None:
        meaning_count = config.clamp_meaning_count(config.get("meaning_count"))
    keep_pos = MAX_POS if not pos_limit else min(pos_limit, MAX_POS)

    seen: set[str] = set()
    pos_list: list[str] = []
    chunks: list[str] = []
    for i, (pos, meanings) in enumerate(groups[:keep_pos]):
        # 前 2 个词性按设置来；第 3 个起少留一个，免得释义拖太长
        want = meaning_count if i < FULL_POS else max(1, meaning_count - 1)
        picked: list[str] = []
        for m in meanings:
            if m[:4] in seen:          # 别的词性里已经出现过，跳过
                continue
            picked.append(m)
            if len(picked) >= want:
                break
        if not picked:
            continue
        seen.update(m[:4] for m in picked)
        pos_list.append(pos or "—")
        body = "；".join(picked)
        chunks.append(f"{pos} {body}".strip() if pos else body)

    if not chunks:
        return None
    cn = " / ".join(chunks)
    if len(cn) > MAX_CN_LEN:
        cn = cn[:MAX_CN_LEN].rstrip("，,；;、 /") + "…"
    cn = tilde(word or _word_of(data, w), cn)
    return {"cn": cn, "pos": " / ".join(pos_list), "ph": ph}


# ---------------------------------------------------------------- 对外接口

def query_online(word: str) -> dict | None:
    """直接问有道。网络异常会抛出来，交给 lookup 处理。"""
    data = json.loads(_get(JSON_API + urllib.parse.quote(word)).decode("utf-8", "ignore"))
    return _extract(data, word)



# ---------------------------------------------------------------- 查词页：完整信息

# 考纲标签统一成中文（有道的 ec.exam_type 给的是英文代号）
EXAM_CN = {
    "CET4": "四级", "CET6": "六级",
    "考研": "考研", "IELTS": "雅思", "TOEFL": "托福",
    "GRE": "GRE", "GMAT": "GMAT", "SAT": "SAT",
    "高中": "高中", "初中": "初中",
}


def _as_list(x):
    """有道返回里同一个字段有时是对象、有时是数组，统一成数组。"""
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


def _strip(s) -> str:
    return re.sub(r"<[^>]+>", "", s or "").strip()


def _text(x) -> str:
    """把有道各种形态的文本节点取成普通字符串。

    同一个字段（比如短语的 headword）在这接口里有时是 "intact rock"，
    有时是 {"l": {"i": "intact rock"}} —— 取决于词条，必须两种都能吃。
    """
    if x is None:
        return ""
    if isinstance(x, str):
        return _strip(x)
    if isinstance(x, (int, float)):
        return str(x)
    if isinstance(x, list):
        return "".join(_text(i) for i in x).strip()
    if isinstance(x, dict):
        for k in ("l", "i", "tr", "headword", "value", "text"):
            if k in x:
                got = _text(x[k])
                if got:
                    return got
        return ""
    return ""


def _word_list(x) -> list[str]:
    """把同义词那类词表取成字符串列表。

    实际见过两种形态：["whole", "complete"] 和 [{"w": "whole"}, {"w": "complete"}]。
    """
    out = []
    for i in _as_list(x):
        v = _text(i.get("w")) if isinstance(i, dict) else _text(i)
        if v:
            out.append(v)
    return out


def _dig(d, *path):
    """按路径取值，中间任何一层缺失/类型不对都返回 None。"""
    cur = d
    for p in path:
        if isinstance(cur, dict):
            cur = cur.get(p)
        elif isinstance(cur, list) and cur and isinstance(cur[0], dict):
            cur = cur[0].get(p)
        else:
            return None
    return cur


def _exam_tags(data: dict, ec_exam: list) -> list[str]:
    """考纲标签。ec.exam_type 比 expand_ec 里的更全，优先用它。"""
    tags = []
    for x in _as_list(ec_exam):
        if isinstance(x, str) and x.strip():
            tags.append(EXAM_CN.get(x.strip(), x.strip()))
    for c in _as_list(_dig(data, "expand_ec", "word")):
        for tl in _as_list(c.get("transList")):
            for e in _as_list(_dig(tl, "content", "examType")):
                zh = (e or {}).get("zh", "")
                if zh and zh not in tags:
                    tags.append(zh)
    return tags


def parse_full(word: str, data: dict, base: dict) -> dict:
    """把有道原始 JSON 整理成查词页需要的一整份信息。

    `base` 是 _extract() 已经算好的 {cn, pos, ph}（沿用词库那套释义编排规则，
    保证查词页看到的释义和背单词时一致）。
    """
    out = {
        "ok": True,
        "en": word,
        "source": "有道词典",
        "cn": base.get("cn", ""),
        "pos": base.get("pos", ""),
        "ph": base.get("ph", ""),
        "exam": _exam_tags(data, _dig(data, "ec", "exam_type")),
    }

    simp = _as_list(_dig(data, "simple", "word"))
    if simp:
        out["ph_us"] = (simp[0].get("usphone") or "").strip()
        out["ph_uk"] = (simp[0].get("ukphone") or "").strip()
    if not out.get("ph_us"):
        out["ph_us"] = _dig(data, "ec", "word", "usphone") or out["ph"]

    # 双语例句
    out["sents"] = [
        {"en": _text(s.get("sentence")), "cn": _text(s.get("sentence-translation")),
         "src": _text(s.get("source"))}
        for s in _as_list(_dig(data, "blng_sents_part", "sentence-pair"))[:4]
        if _text(s.get("sentence"))
    ]

    # 短语搭配（两种形态都要吃）
    phrs = []
    for p in _as_list(_dig(data, "phrs", "phrs"))[:12]:
        if not isinstance(p, dict):
            continue
        phr = p.get("phr") if isinstance(p.get("phr"), dict) else p
        en = _text(phr.get("headword"))
        trs = _as_list(phr.get("trs"))
        cn = _text(trs[0].get("tr")) if trs else ""
        if not cn:
            cn = _text(phr.get("translation"))
        if en:
            phrs.append({"en": en, "cn": cn})
    out["phrs"] = phrs

    # 同义词
    synos = []
    for s in _as_list(_dig(data, "syno", "synos")):
        node = s.get("syno") if isinstance(s.get("syno"), dict) else s
        words = _word_list(node.get("ws"))
        if not words:
            continue
        synos.append({"pos": _text(node.get("pos")),
                      "cn": _text(node.get("tran")) or _text(node.get("trans")),
                      "words": words})
    out["synos"] = synos

    # 词形变化：优先用 ec.word[].wfs（准，还带「复数 / 过去式」这种中文标注）；
    # 没有就退回 rel_word，但要**过滤掉不相干的词** —— 它会把 deserve 家族的
    # deserved / deserving 混进 desert 里来。
    forms = []
    for x in _as_list(_dig(data, "ec", "word", "wfs")):
        wf = x.get("wf") if isinstance(x.get("wf"), dict) else x
        name, val = _text(wf.get("name")), _text(wf.get("value"))
        if name and val:
            forms.append({"pos": name, "en": val, "cn": ""})
    if not forms:
        stem = word.lower()
        keep = stem[:max(3, len(stem) - 2)]        # 容一点词尾变化，但不放无关词进来
        for r in _as_list(_dig(data, "rel_word", "rels")):
            rel = r.get("rel") or {}
            for w in _as_list(rel.get("words")):
                en = _text(w.get("word"))
                if en and en.lower().startswith(keep):
                    forms.append({"pos": _text(rel.get("pos")), "en": en,
                                  "cn": _text(w.get("tran"))})
    out["forms"] = forms

    # ---------------- 「更多」里的东西 ----------------
    more = {}

    # 柯林斯星级释义
    col = []
    for ce in _as_list(_dig(data, "collins", "collins_entries")):
        star = str(_dig(ce, "star") or "")
        for ent in _as_list(_dig(ce, "entries", "entry")):
            for te in _as_list(ent.get("tran_entry")):
                pe = te.get("pos_entry") or {}
                item = {"pos": pe.get("pos", ""), "pos_cn": pe.get("pos_tips", ""),
                        "tran": _text(te.get("tran"))}
                ss = _as_list(_dig(te, "exam_sents", "sent"))
                if ss:
                    item["sent"] = {"en": _text(ss[0].get("eng_sent")),
                                    "cn": _text(ss[0].get("chn_sent"))}
                if star:
                    item["star"] = star
                if item["tran"]:
                    col.append(item)
    if col:
        more["collins"] = col[:6]

    # 英英释义（WordNet）
    ee = []
    for t in _as_list(_dig(data, "ee", "word", "trs")):
        for tr in _as_list(t.get("tr")):
            ee.append({"pos": t.get("pos", ""), "tran": _text(tr.get("tran")),
                       "examples": [_strip(x) for x in _as_list(tr.get("examples"))][:2],
                       "similar": [x for x in _as_list(tr.get("similar-words"))][:5]})
    if ee:
        more["ee"] = ee[:4]

    # 词源
    etym = []
    for key in ("zh", "en"):
        for e in _as_list(_dig(data, "etym", key)):
            v = _text(e.get("value"))
            if v:
                etym.append({"src": e.get("source", ""), "text": v})
    if etym:
        more["etym"] = etym[:5]

    # 权威例句（报刊，多为纯英文）
    auth = [{"en": _text(s.get("foreign")), "src": _text(s.get("source"))}
            for s in _as_list(_dig(data, "auth_sents_part", "sent"))[:4]
            if _text(s.get("foreign"))]
    if auth:
        more["auth"] = auth

    # 影视例句
    media = [{"en": _text(s.get("sentence")), "cn": _text(s.get("sentence-translation")),
              "src": _text(s.get("source"))}
             for s in _as_list(_dig(data, "media_sents_part", "sent"))[:3]
             if _text(s.get("sentence"))]
    if media:
        more["media"] = media

    # 网络释义
    web = []
    for t in _as_list(_dig(data, "web_trans", "web-translation")):
        for tr in _as_list(t.get("trans"))[:1]:
            v = _text(tr.get("value"))
            if v:
                web.append({"cn": v, "support": tr.get("support", 0)})
    if web:
        more["web"] = web[:6]

    out["more"] = more
    return out


def lookup_full(word: str, force: bool = False) -> dict:
    """查词页用：音标 / 释义 / 例句 / 短语 / 同义词 / 柯林斯 / 词源 等一整份信息。

    - 先看本地缓存（dict_full 表），命中就秒回、断网也能看
    - 没缓存就去有道取，取到后**顺手写入词库的释义缓存**（dict_cache），
      这样查过的词也等于把词库那份释义备好了
    - 查不到就返回 {ok: False, reason}
    """
    word = (word or "").strip()
    if not word:
        return {"ok": False, "reason": "没有输入单词"}

    if not force:
        hit = db.dict_full_get(word)
        if hit:
            hit["source"] = "本地缓存"
            return hit

    try:
        raw = json.loads(_get(JSON_API + urllib.parse.quote(word)).decode("utf-8", "ignore"))
    except Exception as exc:
        return {"ok": False, "reason": f"词典连接失败：{exc}"}

    base = _extract(raw, word)
    if not base or not base.get("cn"):
        ai = ai_mod.generate(word)
        if ai and ai.get("cn"):
            return {"ok": True, "en": word, "source": "AI 生成",
                    "cn": ai["cn"], "pos": ai.get("pos", ""), "ph": "",
                    "ph_us": "", "ph_uk": "", "exam": [],
                    "sents": [], "phrs": [], "synos": [], "forms": [], "more": {}}
        return {"ok": False, "reason": "词典和 AI 都查不到这个词"}

    out = parse_full(word, raw, base)
    db.dict_full_put(word, out)                       # 完整结果缓存
    db.dict_put(word, out["cn"], out["pos"], out["ph"], "youdao")   # 顺带喂给词库那份
    return out

# 常见不规则变形 → 原形。规则还原（加 s / ed / ing）能覆盖大多数，
# 但 was / went / children 这类必须查表；这里只收**最常见**的，
# 没收录的走规则还原，再不行就退回原词 —— 宁可不还原，也别还原错。
_IRREGULAR = {
    # be / have / do / go
    "am": "be", "is": "be", "are": "be", "was": "be", "were": "be", "been": "be",
    "has": "have", "had": "have", "does": "do", "did": "do", "done": "do",
    "goes": "go", "went": "go", "gone": "go",
    # 高频动词
    "said": "say", "made": "make", "took": "take", "taken": "take", "got": "get",
    "gotten": "get", "came": "come", "saw": "see", "seen": "see", "knew": "know",
    "known": "know", "gave": "give", "given": "give", "found": "find",
    "thought": "think", "told": "tell", "became": "become", "become": "become",
    "left": "leave", "felt": "feel", "brought": "bring", "began": "begin",
    "begun": "begin", "kept": "keep", "held": "hold", "wrote": "write",
    "written": "write", "stood": "stand", "heard": "hear", "meant": "mean",
    "met": "meet", "ran": "run", "paid": "pay", "sat": "sit", "spoke": "speak",
    "spoken": "speak", "led": "lead", "grew": "grow", "grown": "grow",
    "lost": "lose", "fell": "fall", "fallen": "fall", "sent": "send",
    "built": "build", "understood": "understand", "drew": "draw", "drawn": "draw",
    "broke": "break", "broken": "break", "spent": "spend", "rose": "rise",
    "risen": "rise", "drove": "drive", "driven": "drive", "bought": "buy",
    "wore": "wear", "worn": "wear", "chose": "choose", "chosen": "choose",
    "ate": "eat", "eaten": "eat", "sold": "sell", "sang": "sing", "sung": "sing",
    "swam": "swim", "swum": "swim", "threw": "throw", "thrown": "throw",
    "caught": "catch", "taught": "teach", "fought": "fight", "sought": "seek",
    "lay": "lie", "laid": "lay", "shook": "shake", "shaken": "shake",
    # 不规则复数
    "children": "child", "men": "man", "women": "woman", "feet": "foot",
    "teeth": "tooth", "mice": "mouse", "geese": "goose", "people": "person",
    "lives": "life", "knives": "knife", "wives": "wife", "wolves": "wolf",
    "leaves": "leaf", "thieves": "thief", "shelves": "shelf", "halves": "half",
    "loaves": "loaf", "selves": "self",
    # 不规则比较级 / 最高级
    "better": "good", "best": "good", "worse": "bad", "worst": "bad",
    "more": "many", "most": "many", "less": "little", "least": "little",
    "further": "far", "furthest": "far", "farther": "far", "farthest": "far",
}


def looks_like_lemma(word: str) -> bool:
    """这个词本身是不是原形？

    判据来自有道自己：**原形**会带一整套词形变化（复数 / 第三人称单数 / 现在分词 /
    过去式 / 过去分词），而**变形词和罕见词这一栏都是空的**。实测：

        record     → 复数 records、过去式 recorded …   → 是原形
        abandoned  → （空）                            → 是变形，该还原
        nosed      → （空）                            → 是变形
        recor      → （空）                            → 罕见词，不是 record 的原形

    有了这个判据，`record` 就不会被误拆成 `recor` 了。
    """
    w = (word or "").strip()
    if not w:
        return False
    # -ing 结尾的词，词典往往也单独收录成名词（making 制作 / building 建筑物 /
    # running 跑步），词形变化因此非空、会被判成"原形"。但**例句里它们多半是进行时**，
    # 还原成动词更贴原意（making → make）。所以这一类不走"原形"这条路。
    low = w.lower()
    if low.endswith("ing") and len(low) > 5:
        return False
    return bool(word_forms(w))


def word_forms(word: str) -> list[str]:
    """这个词的词形变化（复数 / 第三人称单数 / 现在分词 / 过去式 / 过去分词）。

    **词典只对原形给这一栏**，变形词和罕见词都是空的 —— 两个用途：
      · 判断一个词是不是原形（见 looks_like_lemma）
      · 反向验证候选：候选 A 的词形变化里包含例句里那个词 → A 就是原形
    结果进 wfs_cache，免得每次还原都重问一遍。
    """
    w = (word or "").strip()
    if not w:
        return []
    hit = db.wfs_get(w)
    if hit is not None:
        return hit
    try:
        data = json.loads(_get(JSON_API + urllib.parse.quote(w)).decode("utf-8", "ignore"))
    except Exception:
        return []                       # 网络不通时不写缓存，下次再试
    forms: list[str] = []
    for x in _as_list(_dig(data, "ec", "word", "wfs")):
        wf = x.get("wf") if isinstance(x.get("wf"), dict) else x
        v = _text(wf.get("value"))
        if v and v.lower() not in forms:
            forms.append(v.lower())
    db.wfs_put(w, forms)
    return forms


def lemma_candidates(word: str) -> list[str]:
    """列出可能的原形，**按「改动越小越可信」排序**。

    为什么要多个候选：`nosed` 既像 `nose + d`，也像 `nos + ed`。
    只取一个规则的话必然有一类词会错。这里把两种都列出来，
    让 mini() 逐个去词典验证（`nose` 排在前面，所以会被选中）。

    只处理单复数 / 时态语态 / 比较级，**不做词性还原**。
    """
    low = (word or "").strip().lower()
    if not low or len(low) < 3:
        return []
    if low in _IRREGULAR:
        return [_IRREGULAR[low]]

    out: list[str] = []

    def add(x: str) -> None:
        if x and x != low and len(x) >= 2 and x not in out:
            out.append(x)

    # ---------- 只去掉 1 个字符（最保守）----------
    # 注意 -ed 的两种拆法要排对：
    #   nose + d  → nosed    （e 结尾的动词加 d）
    #   pass + ed → passed   （ss/sh/ch/x/z 结尾的动词加 ed）
    # 拼写上 nosed / passed 结构一样，只能靠"倒数第三个字母是不是 ss/sh/ch/x/z"来分。
    if low.endswith("ed") and len(low) > 3:
        if low[:-2].endswith(("ss", "sh", "ch", "x", "z")):
            add(low[:-2])                          # passed → pass
            add(low[:-1])                          # passe（少见，备用）
        else:
            add(low[:-1])                          # nosed → nose
    elif low.endswith("d") and len(low) > 3:
        add(low[:-1])
    if low.endswith("s") and not low.endswith(("ss", "us", "is", "ous")) and len(low) > 3:
        add(low[:-1])                              # odours → odour

    # ---------- 去掉 2~3 个字符 ----------
    if low.endswith("ies") and len(low) > 4:
        add(low[:-3] + "y")                        # studies → study
    if low.endswith("ves") and len(low) > 4:
        add(low[:-3] + "f")                        # knives → knife（不规则的上面表里已收）
    if low.endswith(("ches", "shes", "xes", "zes", "sses")) and len(low) > 4:
        add(low[:-2])                              # watches → watch
    if low.endswith("ied") and len(low) > 4:
        add(low[:-3] + "y")                        # cried → cry
    if low.endswith("ed") and len(low) > 3:
        stem = low[:-2]
        if len(stem) >= 3 and stem[-1] == stem[-2] and stem[-1] not in "aeiouy":
            add(stem[:-1])                         # stopped → stop
        add(stem)                                  # abandoned → abandon
    if low.endswith("ing") and len(low) > 4:
        stem = low[:-3]
        # lying → lie / dying → die / tying → tie：原形是 -ie 结尾的，
        # 加 ing 时把 ie 写成了 y，还原要把它换回来。
        if stem.endswith("y") and len(stem) >= 2:
            add(stem[:-1] + "ie")
        if len(stem) >= 3 and stem[-1] == stem[-2] and stem[-1] not in "aeiouy":
            add(stem[:-1])                         # stopping → stop
        # making → make（词尾是 k，补个 e 就是原形）；
        # 但 trying → try，不能补成 trye（那是个爱尔兰人名"特里"）
        if not stem.endswith(("y", "w", "x")):
            add(stem + "e")
        add(stem)                                  # lurking → lurk
    # ---------- 比较级 / 最高级 ----------
    for tail, cut in (("iest", 4), ("est", 3), ("ier", 3), ("er", 2)):
        if low.endswith(tail) and len(low) > cut + 1:
            stem = low[:-cut] + ("y" if tail.startswith("i") else "")
            if len(stem) >= 3 and stem[-1] == stem[-2] and stem[-1] not in "aeiouy":
                stem = stem[:-1]                   # biggest → big
            add(stem)

    return out


def lemma(word: str) -> str:
    """最可信的那个原形（`lemma_candidates` 的第一个）。看不出是变形就返回空串。"""
    c = lemma_candidates(word)
    return c[0] if c else ""


def mini(word: str) -> dict:
    """例句里点某个单词时用：给它的**最主要那一条**释义，外加原形和音标。

    查询顺序：先按原样查（有道对变形词往往也能直接给），查不到再还原原型查。
    两次都查不到就返回 ok=False，前端不弹框。

    返回 {ok, en(原形/词条), form(例句里那个词形), cn, pos, ph, in_library}
    """
    raw = (word or "").strip().strip(".,;:!?\"'‘’“”()[]{}")
    if not raw or not re.search(r"[A-Za-z]", raw):
        return {"ok": False}

    def one(cand: str) -> dict | None:
        info = lookup(cand)                       # 自带 dict_cache 缓存
        cn = (info.get("cn") or "").strip()
        if not info.get("ok") or not cn:
            return None
        # 两种"不像正常释义"的候选都跳过：
        #   · 只给缩写的：making 去掉 ing 得到 mak → 「abbr. 多次激活密钥」
        #   · 只给变形说明的：studied 去掉 ed 得到 studie → 「（study 的旧式）」
        # 跳过它们，候选链就会自动往下走到真正的原形（make / study）。
        if re.match(r"^(abbr|缩写|缩略|简写)", cn, re.I):
            return None
        if re.search(r"的(旧式|复数形式|过去式|过去分词|现在分词|比较级|最高级"
                     r"|第三人称单数|变体|异体|复数)", cn):
            return None
        # 只要第一条：cn 形如 "n. 甲；乙 / v. 丙"，取到第一个 "/" 或第一个 "；" 为止
        first = re.split(r"\s*/\s*", cn)[0]
        first = re.split(r"[；;]", first)[0].strip().rstrip("，,、")
        return {"ok": True, "en": cand, "form": raw, "cn": first,
                "pos": info.get("pos", ""), "ph": info.get("ph", "")}

    plain = one(raw)

    # ① 它自己就是原形（有道给了词形变化）→ 直接用，别乱拆。
    #    否则 record 会被拆成 recor（"生理记录仪"，是型号名）。
    if plain and looks_like_lemma(raw):
        plain["in_library"] = db.find_word(plain["en"]) is not None
        return plain

    # ② 是变形（abandoned / children / nosed / was…）→ 还原。
    #
    #    候选有好几个（nosed 既像 nose+d 也像 nos+ed），怎么挑？
    #    **反向验证**：查每个候选的词形变化，里面**包含例句里这个词**的那个就是原形。
    #      nose 的变化 = noses/nosing/nosed  → 有 nosed → nose 就是它 ✔
    #      nos  的变化 = （空）              → 排除
    #    这比"按规则猜"可靠得多，而且判据来自词典本身。
    cands = lemma_candidates(raw)
    for base in cands:
        forms = word_forms(base)
        if raw.lower() in forms:
            hit = one(base)
            if hit:
                hit["in_library"] = db.find_word(base) is not None
                hit["verified_by"] = "word-forms"      # 标记一下，方便排查
                return hit

    # 反向验证没命中（比如不规则动词，词典有时不给变化栏）→ 退回按可信度顺序试
    for base in cands:
        hit = one(base)
        if hit:
            hit["in_library"] = db.find_word(base) is not None
            return hit

    # ③ 候选都不行，退回原样（能让用户看到点东西，总比什么都不弹强）
    if plain:
        plain["in_library"] = db.find_word(plain["en"]) is not None
        return plain

    return {"ok": False, "form": raw}


def first_sentence(word: str) -> dict:
    """取这个单词的一句例句（背单词提交后显示用）。

    · 先查 `sent_cache`，命中就秒回、断网也能看
    · 没缓存才联网，拿到第一条就存起来
    · **没有例句也记一笔**（存空串），否则每提交一次都要去问一遍词典

    返回 {ok, sent, cn, src}；ok 为 False 表示这个词确实没有例句。
    """
    word = (word or "").strip()
    if not word:
        return {"ok": False}

    hit = db.sent_get(word)
    if hit:
        return {"ok": bool(hit["sent"]), "sent": hit["sent"],
                "cn": hit["cn"], "src": hit["src"], "cached": True}

    try:
        data = json.loads(_get(JSON_API + urllib.parse.quote(word)).decode("utf-8", "ignore"))
    except Exception:
        return {"ok": False, "reason": "取例句失败"}

    for pair in _as_list(_dig(data, "blng_sents_part", "sentence-pair")):
        sent = _text(pair.get("sentence"))
        if not sent:
            continue
        cn = _text(pair.get("sentence-translation"))
        src = _text(pair.get("source"))
        db.sent_put(word, sent, cn, src)
        return {"ok": True, "sent": sent, "cn": cn, "src": src}

    db.sent_put(word, "", "", "")          # 记下「确认没有例句」
    return {"ok": False}


def lookup(word: str, use_cache: bool = True, force: bool = False) -> dict:
    """查词：先本地缓存，再在线词典。

    返回 {ok, cn, pos, ph, source}；失败时 {ok: False, reason}。
    查不到的词会在缓存里留下一条 `miss` 记录，避免每次补全都去重问一遍。
    """
    word = (word or "").strip()
    if not word:
        return {"ok": False, "reason": "没有输入单词"}

    if use_cache and not force:
        hit = db.dict_get(word)
        if hit and hit.get("cn"):
            return {"ok": True, "source": "本地缓存",
                    "cn": hit["cn"], "pos": hit["pos"], "ph": hit["ph"]}
        if hit and hit.get("source") == "miss":
            return {"ok": False, "reason": "词典里查不到这个词", "cached_miss": True}

    try:
        info = query_online(word)
    except Exception as exc:
        return {"ok": False, "reason": f"词典连接失败：{exc}"}

    if not info or not info.get("cn"):
        # 词典里没有 → 交给 AI 兜底（配了 key 才走；没配就留个念想，不写 miss）
        ai = ai_mod.generate(word)
        if ai and ai.get("cn"):
            db.dict_put(word, ai["cn"], ai.get("pos", ""), "", "ai")
            return {"ok": True, "source": "AI 生成",
                    "cn": ai["cn"], "pos": ai.get("pos", ""), "ph": ""}
        if ai is None:
            return {"ok": False,
                    "reason": "词典里查不到这个词（还没配置 AI 兜底，可在设置里填 API Key）"}
        db.dict_put(word, "", "", "", "miss")      # 记住「词典和 AI 都没有」，别再反复问
        return {"ok": False, "reason": "词典和 AI 都查不到这个词"}

    db.dict_put(word, info["cn"], info["pos"], info["ph"], "youdao")
    return {"ok": True, "source": "有道词典", **info}


def fetch_audio(word: str, accent: str = "us") -> bytes | None:
    """取真人发音 MP3；取不到返回 None（前端会回退到本机合成音）。"""
    word = (word or "").strip()
    if not word:
        return None
    t = "1" if accent == "uk" else "2"
    try:
        data = _get(VOICE_API.format(word=urllib.parse.quote(word), t=t))
    except Exception:
        return None
    if len(data) < 512:
        return None
    # 校验确实是音频（ID3 头 或 MPEG 帧同步）
    if data[:3] == b"ID3" or data[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"):
        return data
    return None
