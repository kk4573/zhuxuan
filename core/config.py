"""竹喧 · 应用配置（config.json，放在应用目录下）

纯文本 JSON，随时可以手动改。
`deepseek_api_key` 只存在这个文件里，**不会回传给前端**（前端只能看到「配没配」）。
"""
from __future__ import annotations

import json

from .paths import BASE_DIR

CONFIG_PATH = BASE_DIR / "config.json"

DEFAULTS = {
    "force_english_ime": True,          # 答题时把输入法切到英文，离开时还原
    "deepseek_api_key": "",             # 词典查不到的词交给它兜底（留空=不用）
    "deepseek_base_url": "https://api.deepseek.com",
    "deepseek_model": "deepseek-chat",
    "audio_accent": "us",               # 发音口音：us / uk
    # 当天已考过的词降权系数：权重 ÷ (1 + 当天已考次数 × today_decay)
    # 0 = 不抑制；1 = 考过一次权重减半；越大抑制越强
    "today_decay": 1.0,
    # 释义要多详细：保留几个词性（0 = 全留）、每个词性保留几个义项
    "pos_limit": 0,
    "meaning_count": 2,
}

DECAY_MIN, DECAY_MAX = 0.0, 5.0
POS_LIMIT_MAX = 6                # 和 dictionary.MAX_POS 一致（保险上限）
MEANING_MIN, MEANING_MAX = 1, 3

_cache: dict | None = None


def clamp_decay(value) -> float:
    """把「当天重复抑制强度」夹到合理范围，坏值退回默认。"""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return float(DEFAULTS["today_decay"])
    return min(DECAY_MAX, max(DECAY_MIN, round(v, 2)))


def clamp_pos_limit(value) -> int:
    """保留几个词性。0（或坏的输入）= 全留。"""
    try:
        v = int(value)
    except (TypeError, ValueError):
        return int(DEFAULTS["pos_limit"])
    if v <= 0:
        return 0
    return min(POS_LIMIT_MAX, v)


def clamp_meaning_count(value) -> int:
    """每个词性保留几个义项，1~3。"""
    try:
        v = int(value)
    except (TypeError, ValueError):
        return int(DEFAULTS["meaning_count"])
    return min(MEANING_MAX, max(MEANING_MIN, v))


def load(force: bool = False) -> dict:
    global _cache
    if _cache is not None and not force:
        return _cache
    data = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        try:
            raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                data.update({k: v for k, v in raw.items() if k in DEFAULTS})
        except Exception:
            pass                    # 配置坏了就用默认值，不要让应用起不来
    _cache = data
    return data


def get(key: str, default=None):
    return load().get(key, DEFAULTS.get(key, default))


def save(patch: dict) -> dict:
    global _cache
    data = load()
    data.update({k: v for k, v in patch.items() if k in DEFAULTS and v is not None})
    try:
        CONFIG_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass
    _cache = data
    return public_view()


def public_view() -> dict:
    """给前端看的版本：密钥只回传「配没配」，内容一律不外传。"""
    d = load()
    key = (d.get("deepseek_api_key") or "").strip()
    return {
        "force_english_ime": bool(d["force_english_ime"]),
        "audio_accent": d["audio_accent"],
        "deepseek_model": d["deepseek_model"],
        "today_decay": clamp_decay(d.get("today_decay")),
        "pos_limit": clamp_pos_limit(d.get("pos_limit")),
        "meaning_count": clamp_meaning_count(d.get("meaning_count")),
        "deepseek_ready": bool(key),
        "deepseek_hint": "已配置" if key else "",
        "config_path": str(CONFIG_PATH),
    }
