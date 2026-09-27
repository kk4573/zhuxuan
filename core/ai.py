"""竹喧 · AI 释义兜底（DeepSeek）

有道词典里没有的词（新词、缩写、专有名词、生造词）交给它生成释义。
输出格式和词典保持一致（`n. 释义；释义 / v. 释义`），这样前端和判定都不需要特殊处理。

**只在 `config.json` 里配了 `deepseek_api_key` 时才启用**；没配就静默跳过，不报错、不联网。
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

from . import config

TIMEOUT = 30.0

SYSTEM_PROMPT = (
    "你是一部英汉词典。用户给你一个英文单词或短语，你直接输出它的中文释义。格式要求：\n"
    "1. 每个词性写成一段，段与段之间用半角斜杠加空格「 / 」分隔，每段以词性缩写开头"
    "（n. / v. / adj. / adv. / prep. / phr. 等）\n"
    "2. 同一个词性下最多 2 个义项，义项之间用中文分号「；」分隔\n"
    "3. 中文释义要精简，每个义项不超过 12 个字\n"
    "4. 全部加起来不超过 60 个字\n"
    "5. 只输出释义本身：不要解释、不要编号、不要 markdown、不要引号、不要音标、不要换行\n"
    "示例输出：n. 沙漠，荒漠；荒凉的地方 / v. 离弃，舍弃 / adj. 无人居住的"
)


def enabled() -> bool:
    return bool((config.get("deepseek_api_key") or "").strip())


def _clean(text: str) -> str:
    """把模型可能多给的东西剥掉：代码块、引号、换行、多余空白。"""
    text = (text or "").strip()
    text = re.sub(r"^```[a-zA-Z]*\s*|```$", "", text).strip()
    text = text.split("\n")[0].strip()
    text = text.strip("\"'“”‘’ ")
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s*/\s*", " / ", text)
    return text


def _extract_pos(text: str) -> str:
    """从 «n. 沙漠 / v. 离弃» 里把词性汇总成 «n. / v.»"""
    found = re.findall(r"(?:^|/\s*)([a-z]{1,6}\.)\s", text + " ", re.I)
    seen, out = set(), []
    for p in found:
        p = p.strip()
        if p.lower() not in seen:
            seen.add(p.lower())
            out.append(p)
    return " / ".join(out)


def generate(word: str) -> dict | None:
    """让 AI 生成释义。

    返回：
      · {cn, pos}     成功
      · None          没配 key（调用方不要写 miss，等配了 key 还能重试）
      · {"error": …}  配了 key 但调用失败
    """
    cfg = config.load()
    key = (cfg.get("deepseek_api_key") or "").strip()
    if not key:
        return None

    base = (cfg.get("deepseek_base_url") or "https://api.deepseek.com").rstrip("/")
    model = cfg.get("deepseek_model") or "deepseek-chat"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": word},
        ],
        "temperature": 0.2,
        "max_tokens": 160,
        "stream": False,
    }
    req = urllib.request.Request(
        base + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8", "ignore"))
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "ignore")[:200]
        except Exception:
            pass
        return {"error": f"HTTP {exc.code} {detail}"}
    except Exception as exc:
        return {"error": str(exc)}

    try:
        text = _clean(data["choices"][0]["message"]["content"])
    except Exception:
        return {"error": "AI 返回的内容解析不了"}

    if not text or len(text) > 200:
        return {"error": "AI 返回的释义格式不对劲"}

    return {"cn": text, "pos": _extract_pos(text)}
