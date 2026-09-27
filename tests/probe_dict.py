"""竹喧 · 词典源探测（调研用）

看看哪些词典接口在这台机器上可用、返回什么字段、要多少时间。
以后想换释义来源，重跑这个脚本就行。

    .venv/Scripts/python.exe tests/probe_dict.py
"""
from __future__ import annotations

import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE          # 只做可达性探测，不校验证书

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


def fetch(url: str, timeout: float = 12.0) -> tuple[int, bytes, float]:
    t0 = time.time()
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=CTX) as resp:
            return resp.status, resp.read(), time.time() - t0
    except urllib.error.HTTPError as exc:
        return exc.code, b"", time.time() - t0
    except Exception as exc:
        return 0, str(exc).encode(), time.time() - t0


def probe_youdao(word: str = "apple") -> None:
    url = "https://dict.youdao.com/jsonapi?q=" + urllib.parse.quote(word)
    status, body, dt = fetch(url)
    print(f"\n【有道 jsonapi】{status}  {dt:.2f}s  {len(body)} bytes")
    if status != 200:
        print("   ", body[:200])
        return
    try:
        data = json.loads(body.decode("utf-8", "ignore"))
    except Exception as exc:
        print("    解析失败:", exc)
        return
    print("    顶层字段:", list(data.keys())[:12])
    ec = data.get("ec") or {}
    words = ec.get("word") or []
    if words:
        w = words[0]
        print("    ec.word[0] 字段:", list(w.keys())[:14])
        trs = w.get("trs") or []
        for tr in trs[:3]:
            for item in (tr.get("tr") or [])[:1]:
                print("    释义:", json.dumps(item.get("l"), ensure_ascii=False)[:160])
        print("    美音:", w.get("usphone"), " 英音:", w.get("ukphone"))
        ex = (w.get("exam_type") or [])[:5]
        if ex:
            print("    考纲标签:", ex)
    else:
        print("    没有 ec 字段，返回片段:", body[:200])


def probe_youdao_suggest(word: str = "apple") -> None:
    url = f"https://dict.youdao.com/suggest?q={urllib.parse.quote(word)}&num=1&doctype=json"
    status, body, dt = fetch(url)
    print(f"\n【有道 suggest】{status}  {dt:.2f}s")
    print("   ", body.decode("utf-8", "ignore")[:300])


def probe_gitee_ecdict() -> None:
    url = "https://gitee.com/api/v5/search/repositories?q=ECDICT&per_page=8"
    status, body, dt = fetch(url)
    print(f"\n【Gitee 搜 ECDICT 仓库】{status}  {dt:.2f}s")
    if status != 200:
        print("   ", body[:200])
        return
    try:
        items = json.loads(body.decode("utf-8", "ignore"))
    except Exception as exc:
        print("    解析失败:", exc, body[:200])
        return
    if not items:
        print("    没有找到仓库")
        return
    for it in items:
        print(f"    · {it.get('full_name')}  ★{it.get('stargazers_count')}  "
              f"更新 {str(it.get('updated_at'))[:10]}  {it.get('description')}")


def probe_pypi_wordfreq() -> None:
    """顺便看看有没有能用的 pip 词典包。"""
    url = "https://pypi.tuna.tsinghua.edu.cn/simple/ecdict/"
    status, body, dt = fetch(url)
    print(f"\n【清华源 ecdict 包】{status}  {dt:.2f}s")
    if status == 200:
        print("   ", body.decode("utf-8", "ignore")[:300].replace("\n", " ")[:300])
    else:
        print("    没有这个包")


if __name__ == "__main__":
    probe_youdao("apple")
    probe_youdao("give up")
    probe_youdao("ubiquitous")
    probe_youdao("zzzznotaword")
    probe_youdao_suggest("apple")
    probe_gitee_ecdict()
    probe_pypi_wordfreq()
