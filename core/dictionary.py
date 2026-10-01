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


def _extract(data: dict) -> dict | None:
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

    seen: set[str] = set()
    pos_list: list[str] = []
    chunks: list[str] = []
    for i, (pos, meanings) in enumerate(groups[:MAX_POS]):
        want = FULL_MEANINGS if i < FULL_POS else LATER_MEANINGS
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
    return {"cn": cn, "pos": " / ".join(pos_list), "ph": ph}


# ---------------------------------------------------------------- 对外接口

def query_online(word: str) -> dict | None:
    """直接问有道。网络异常会抛出来，交给 lookup 处理。"""
    data = json.loads(_get(JSON_API + urllib.parse.quote(word)).decode("utf-8", "ignore"))
    return _extract(data)



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

    base = _extract(raw)
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
