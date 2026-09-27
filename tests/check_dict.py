"""竹喧 · 词典模块测试

分两部分：
  · 不联网的单元测试：释义编排规则（_extract）
  · 联网的实测：真查几个词、缓存是否命中、音频能不能拿到

    .venv/Scripts/python.exe tests/check_dict.py
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["ZHUXUAN_DB"] = str(ROOT / "data" / "dict-test.db")   # 独立库，不碰真实数据

from core import db, dictionary  # noqa: E402

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


def mock_word(*blocks: str) -> dict:
    """造一个有道那样的返回结构"""
    return {"ec": {"word": [{
        "usphone": "ˈtest", "ukphone": "ˈtest",
        "trs": [{"tr": [{"l": {"i": [b]}}]} for b in blocks],
    }]}}


def main() -> int:
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(db.DB_PATH) + suffix)
        if p.exists():
            p.unlink()
    db.init()

    print("— 释义编排规则（构造数据，不联网）—")
    g = dictionary._extract(mock_word(
        "n. 记录，记载；（某人或某物过去的）记录，经历；唱片",
        "v. 记录，记载；录制",
        "adj. 创纪录的",
        "【名】 （Record）（美）勒科尔（人名）",
    ))
    check(f"词性全保留（含 adj.）：{g['pos']!r}", g["pos"] == "n. / v. / adj.", g["pos"])
    check(f"词性内联进释义、前 2 个词性各 2 个义项、第 3 个只 1 个 → {g['cn']!r}",
          g["cn"] == "n. 记录，记载；（某人或某物过去的）记录，经历 / v. 录制 / adj. 创纪录的", g["cn"])
    check("人名义项被丢掉", "勒科尔" not in g["cn"], g["cn"])

    g2 = dictionary._extract(mock_word("v. 抛弃，遗弃；中止，不再有；放弃（信念）"))
    check(f"只有一个词性时保留 2 个义项 → {g2['cn']!r}",
          g2["cn"] == "v. 抛弃，遗弃；中止，不再有", g2["cn"])

    g3 = dictionary._extract(mock_word("n. 甲一；甲二", "v. 乙一；乙二", "adj. 丙一；丙二"))
    check(f"第 3 个词性起只留 1 个 → {g3['cn']!r}",
          g3["cn"] == "n. 甲一；甲二 / v. 乙一；乙二 / adj. 丙一", g3["cn"])

    g4 = dictionary._extract(mock_word("n. 沙漠，荒漠；荒凉的地方", "v. 离弃，舍弃（某地）", "【地】 desert 沙漠"))
    check(f"地名条目被丢掉 → {g4['cn']!r}", g4["cn"].count("/") == 1, g4["cn"])

    check("词典里完全没有这个词时返回 None", dictionary._extract({"ec": {"word": []}}) is None)
    check("只有人名义项时也返回 None",
          dictionary._extract(mock_word("【名】 （Fine）（英）法恩（人名）")) is None)

    print("\n— 真实查词（联网）—")
    t0 = time.time()
    r = dictionary.lookup("apple")
    check(f"apple：{r.get('cn')}  {r.get('ph')}",
          r.get("ok") and "苹果" in r.get("cn", "") and r.get("pos") == "n.", r)

    r2 = dictionary.lookup("desert")
    check(f"desert 保留全部词性：{r2.get('pos')}",
          r2.get("pos") == "n. / v. / adj.", r2)
    check(f"desert 释义：{r2.get('cn')}",
          "沙漠" in (r2.get("cn") or "") and "离弃" in (r2.get("cn") or ""), r2)

    r3 = dictionary.lookup("give up")
    check(f"短语 give up：{r3.get('cn')}", r3.get("ok") and r3.get("cn"), r3)

    r4 = dictionary.lookup("zzzznotarealword")
    check("词典里没有的词会被识别出来", not r4.get("ok"), r4)

    r5 = dictionary.lookup("apple")
    check(f"再查一次走本地缓存（{r5.get('source')}）", r5.get("source") == "本地缓存", r5)

    r6 = dictionary.lookup("zzzznotarealword")
    check("没配 AI 兜底时不写 miss，以后配了 key 还能重试",
          r6.get("cached_miss") is not True and "AI" in (r6.get("reason") or ""), r6)
    check(f"以上查询共耗时 {time.time()-t0:.1f}s", True)

    print("\n— AI 兜底（用临时配置，不会真花钱；也不碰你的 config.json）—")
    from core import ai as ai_mod, config as cfg_mod

    saved_cache = cfg_mod._cache
    cfg_mod._cache = {**cfg_mod.DEFAULTS, "deepseek_api_key": ""}
    check("没配 key 时 enabled() = False", ai_mod.enabled() is False)
    check("没配 key 时 generate() 返回 None（不联网）", ai_mod.generate("whatever") is None)

    r7 = dictionary.lookup("zzzznokeyprobe", force=True)
    check(f"词典没有 + 没配 key → 明确提示：{r7.get('reason')}",
          "AI 兜底" in (r7.get("reason") or ""), r7)
    hit = db.dict_get("zzzznokeyprobe")
    check("**没配 key 时不写 miss**（以后配了 key 还能再试）",
          not hit or hit.get("source") != "miss", hit)

    cfg_mod._cache = {**cfg_mod.DEFAULTS, "deepseek_api_key": "sk-fake-key-for-test"}
    check("配上 key 后 enabled() = True", ai_mod.enabled() is True)
    r8 = dictionary.lookup("zzzznotarealword2", force=True)
    check(f"配了假 key → 调用失败但如实报告：{(r8.get('reason') or '')[:46]}",
          r8.get("ok") is False and "AI" in (r8.get("reason") or ""), r8)
    hit2 = db.dict_get("zzzznotarealword2")
    check("这种情况要写 miss（别每次补全都去白跑一趟 AI）",
          bool(hit2) and hit2.get("source") == "miss", hit2)
    cfg_mod._cache = saved_cache

    print("\n— 真人发音 —")
    audio = dictionary.fetch_audio("apple")
    check(f"拿到 apple 音频 {len(audio) if audio else 0} 字节", bool(audio) and len(audio) > 512)
    check("取不到的音频返回 None", dictionary.fetch_audio("zzzznotarealword") is None)

    for suffix in ("", "-wal", "-shm"):
        p = Path(str(db.DB_PATH) + suffix)
        if p.exists():
            p.unlink()

    print(f"\n结果：{OK} 通过 / {FAIL} 失败")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
