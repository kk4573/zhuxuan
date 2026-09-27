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
}

_cache: dict | None = None


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
        "deepseek_ready": bool(key),
        "deepseek_hint": "已配置" if key else "",
        "config_path": str(CONFIG_PATH),
    }
