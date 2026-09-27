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
