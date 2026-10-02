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

    print("\n— 查词页用的完整信息 lookup_full —")
    # 这几个词的字段形态各不相同（有道同一个字段会给出不同结构），专门拿它们当哨兵
    for w in ("intact", "abandon", "desert", "mingle"):
        f = dictionary.lookup_full(w, force=True)
        check(f"{w}：查得到", f.get("ok"), f.get("reason"))
        if not f.get("ok"):
            continue
        check(f"{w}：有音标", bool(f.get("ph_us") or f.get("ph")), f.get("ph_us"))
        check(f"{w}：有释义", bool(f.get("cn")), f.get("cn"))
        check(f"{w}：有双语例句", len(f.get("sents") or []) >= 1, f.get("sents"))
        check(f"{w}：例句带中文翻译",
              any((s.get("cn") or "") for s in (f.get("sents") or [])), f.get("sents"))
        # ↓ 这条是给「字段形态不稳定」留的哨兵：曾经因为 headword 是嵌套对象而整块解析成空
        check(f"{w}：短语解析出了内容（不是空壳）",
              all(p.get("en") for p in (f.get("phrs") or [])), f.get("phrs"))
        check(f"{w}：同义词解析出了内容（不是空壳）",
              all(s.get("words") for s in (f.get("synos") or [])), f.get("synos"))
        check(f"{w}：词形变化解析出了内容",
              all(x.get("en") for x in (f.get("forms") or [])), f.get("forms"))
        check(f"{w}：「更多」里有内容", bool(f.get("more")), list((f.get("more") or {}).keys()))

    hit = dictionary.lookup_full("intact")
    check("第二次查走本地缓存", hit.get("source") == "本地缓存", hit.get("source"))
    check("缓存里也保住了例句", len(hit.get("sents") or []) >= 1)
    check("查不到的词如实返回", dictionary.lookup_full("zzzznotarealword9").get("ok") is False)

    print("\n— 真人发音 —")
    audio = dictionary.fetch_audio("apple")
    check(f"拿到 apple 音频 {len(audio) if audio else 0} 字节", bool(audio) and len(audio) > 512)
    check("取不到的音频返回 None", dictionary.fetch_audio("zzzznotarealword") is None)

    # 清掉缓存库，让下面的 `~` 和例句测试从干净状态开始（**删完必须重建表**）
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(db.DB_PATH) + suffix)
        if p.exists():
            p.unlink()
    db.init()

    print("\n— 释义里的 `~`（牛津写法）—")
    from core.dictionary import tilde

    # 真正要防的是"把不该换的换掉"，所以正反两面都要断言
    tilde_cases = [
        # (单词, 原文, 期望)
        ("abandon", "v. 放弃，抛弃；abandon oneself to 沉溺于", "v. 放弃，抛弃；~ oneself to 沉溺于"),
        ("crystal", "n. 水晶；cry 哭喊", "n. 水晶；cry 哭喊"),          # 子串不能误伤
        ("cry", "v. 哭；cried 哭了", "v. 哭；~ 哭了"),                  # y→i 变形
        ("cry", "v. 哭；cries 哭喊", "v. 哭；~ 哭喊"),
        ("study", "v. studies 研究；studied 研究过的", "v. ~ 研究；~ 研究过的"),
        ("day", "n. days 天；daily 每日的", "n. ~ 天；daily 每日的"),   # daily 不是 day 的规则变形
        ("Abandon", "abandon 放弃", "~ 放弃"),                           # 大小写不敏感
        ("acid", "n. 酸；酸类物质", "n. 酸；酸类物质"),                  # 没出现就不动
        ("record", "n. 记录 / v. 录制", "n. 记录 / v. 录制"),
        ("go", "v. go 去；going 去", "v. ~ 去；~ 去"),
    ]
    for en, src, want in tilde_cases:
        got = tilde(en, src)
        check(f"tilde({en!r}) → {got[:34]}", got == want, f"期望 {want}")

    # 释义为空时不能炸
    check("tilde 对空释义安全", tilde("abandon", "") == "" and tilde("", "abc") == "abc")

    print("\n— 背单词时那句例句 —")
    from core.dictionary import first_sentence

    r1 = first_sentence("abandon")
    check("能取到 abandon 的例句", r1.get("ok") and bool(r1.get("sent")), r1)
    if r1.get("ok"):
        check("例句是英文", any(c.isalpha() for c in r1["sent"]) and not r1["sent"].startswith("n."))
        check("例句带中文翻译", bool(r1.get("cn")), r1.get("cn"))

    r2 = first_sentence("abandon")
    check("第二次走本机缓存", r2.get("cached") is True, r2)

    check("同一个词两次结果一致", r1.get("sent") == r2.get("sent"))

    # 空输入不能炸
    r3 = first_sentence("")
    check("空单词安全", r3.get("ok") is False)

    # 乱码词：应该返回 ok=False，而不是抛异常
    r4 = first_sentence("zzzqqq-not-a-word")
    check("查不到的词不抛异常", r4.get("ok") is False, r4)

    print("\n— 释义详细程度可以设置 —")
    import json as _json
    import urllib.parse as _up
    from core.dictionary import JSON_API, _get, _extract
    raw = _json.loads(_get(JSON_API + "record").decode("utf-8", "ignore"))

    a = _extract(raw, "record", pos_limit=1, meaning_count=2)
    check("词性限 1 个：只剩第一种词性", "/" not in a["cn"] and a["cn"].startswith("n."), a["cn"])

    b = _extract(raw, "record", pos_limit=2, meaning_count=2)
    check("词性限 2 个：正好两种", b["cn"].count("/") == 1, b["cn"])

    c = _extract(raw, "record", pos_limit=0, meaning_count=1)
    check("义项限 1 个：每段只有一条", "；" not in c["cn"], c["cn"])

    d = _extract(raw, "record", pos_limit=0, meaning_count=2)
    check("默认（全部词性 + 2 义项）比 1 义项长", len(d["cn"]) > len(c["cn"]))
    check("词性越多释义越长", len(d["cn"]) > len(a["cn"]))

    e = _extract(raw, "record", pos_limit=99, meaning_count=9)
    check("超范围的值被夹住，不会崩", bool(e and e["cn"]))

    # 设置真的传到了 _extract：改 config 后不带参数调用应该跟着变
    from core import config as _cfg
    _cfg.save({"pos_limit": 1, "meaning_count": 1})
    f = _extract(raw, "record")
    check("config 改了之后 _extract 默认值跟着变", f["cn"].count("/") == 0, f["cn"])
    _cfg.save({"pos_limit": 0, "meaning_count": 2})
    g = _extract(raw, "record")
    check("改回默认又能看到多种词性", g["cn"].count("/") >= 2, g["cn"])

    print(f"\n结果：{OK} 通过 / {FAIL} 失败")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
