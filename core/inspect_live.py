# -*- coding: utf-8 -*-
"""進行中ヤフオクの本文検品。

souba-league/src/verify_body.py は **落札済み**個体を aucfree から引く。
買いアラートに要るのはその逆で、**まだ終わっとらん個体**の本文や。
ヤフオクの商品ページは __NEXT_DATA__ に descriptionHtml を素で持っとるので、
そこから本文を抜いて、判定ロジックは verify_body のものをそのまま借りる。

  * 判定器を書き直さんのが肝。regex も LLM プロンプトも 38件で精度実測済みで、
    ここで別実装を持つと精度の根拠が消える。
  * 結果は data/live_inspect.csv にキャッシュ(同じ個体を何度も叩かん)。
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

from . import sources as S

# 判定器は souba-league が原本。クラウドには export_snapshot.py が
# core/vendor/ にコピーしたものが乗っとる。どっちも「別実装を持たん」原則の内側。
sys.path.insert(0, str(S.SOUBA / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent / "vendor"))
try:
    import verify_body as VB          # 判定器の唯一の実装
except Exception:                      # 読めん環境でもサイトは開く
    VB = None
try:
    import find_winners as FW          # 勝ち語の採点器
except Exception:
    FW = None

CACHE = S.DATA / "live_inspect.csv"
PAGE = "https://page.auctions.yahoo.co.jp/jp/auction/{}"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
NEXT_RE = re.compile(r'id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)


def fetch_live(auction_id: str, session: requests.Session | None = None) -> dict:
    """進行中個体の本文と状態。取れんかったら body=None。"""
    s = session or requests.Session()
    try:
        r = s.get(PAGE.format(auction_id), headers={"User-Agent": UA},
                  timeout=25, allow_redirects=True)
    except requests.RequestException as exc:
        return {"auction_id": auction_id, "body": None, "error": type(exc).__name__}
    if r.status_code != 200:
        return {"auction_id": auction_id, "body": None, "error": f"HTTP{r.status_code}"}
    m = NEXT_RE.search(r.text)
    if not m:
        return {"auction_id": auction_id, "body": None, "error": "no __NEXT_DATA__"}
    try:
        j = json.loads(m.group(1))
        item = j["props"]["pageProps"]["initialState"]["item"]["detail"]["item"]
    except Exception:
        return {"auction_id": auction_id, "body": None, "error": "parse"}

    html = item.get("descriptionHtml") or item.get("description") or ""
    text = re.sub(r"<[^>]+>", " ", VB.TAG_RE.sub("", html) if VB else html)
    text = re.sub(r"\s+", " ", text).strip()
    return {
        "auction_id": auction_id,
        "title": item.get("title", ""),
        "price": item.get("price"),
        "bids": item.get("bids"),
        "condition": (item.get("conditionName") or ""),
        "end_time": item.get("formattedEndTime", ""),
        "body": text or None,
        "body_chars": len(text),
        "error": "",
    }


def inspect(auction_id: str, use_llm: bool = True,
            session: requests.Session | None = None) -> dict:
    """(verdict, hit) を付けて返す。LLM が使えんかったら regex に退避。"""
    info = fetch_live(auction_id, session)
    if VB is None:
        info.update(verdict="unknown", hit="verify_body を読めん", how="—")
        return info
    if not info.get("body"):
        info.update(verdict="unknown", hit=info.get("error") or "本文取得不能", how="—")
        return info

    # **regex を先に通す。** 2026-08-11まで LLM を先に呼んで regex は退避扱いやった。
    # せやから「ジャンク」「動作確認不可」と書いてある出品でも、LLM が
    # 「分類のみで具体的な欠陥の記述がない」と言うたらそのまま素通りしとった
    # (落札済みの検品で D850 の玉が純利+26,545の生存に化けた実例あり)。
    # 等級・素性の宣言は LLM に諮らず確定させる。免責定型との区別が要るのは
    # 状態語だけで、そこだけ LLM に渡す。
    verdict, hit = VB.judge(info["body"])
    how = "regex"
    locked = verdict == "kill" and (set(hit.split("|")) & VB.NO_OVERTURN)
    if locked:
        hit = f"(確定) {hit}"
        how = "regex(確定)"
    elif use_llm:
        key = VB._load_env().get("GROQ_API_KEY")
        if key:
            lv, lh = VB.judge_llm(session or requests.Session(), info["body"], key)
            if lv not in ("error", "throttled", "exhausted"):
                if lv == "keep" and verdict == "kill":
                    hit = f"(LLMが撤回: {hit}) {lh}"[:140]
                else:
                    hit = lh
                verdict, how = lv, "LLM"
    # 欠陥が無いことと良品であることは別や。**勝ち語**も必ず採る——
    # 2026-08-07の人手検証で落ちた17件のうち6件は「欠陥は無いが状態が確認できん」
    # (通電のみ・記述ゼロ・代理出品)やった。負のフィルタだけでは拾えん。
    pts, sigs = FW.score(info["body"]) if FW else (0, [])
    info.update(verdict=verdict, hit=hit, how=how,
                win_score=pts, win_signals="|".join(sigs),
                checked_at=datetime.now().isoformat(timespec="seconds"))
    return info


def load_cache() -> pd.DataFrame:
    d = S.read_csv(CACHE, dtype={"auction_id": str})
    return d if not d.empty else pd.DataFrame(
        columns=["auction_id", "verdict", "hit", "how", "win_score",
                 "win_signals", "title", "condition", "body_chars",
                 "checked_at"])


def save_result(res: dict) -> None:
    keep = ["auction_id", "verdict", "hit", "how", "win_score", "win_signals",
            "title", "condition", "body_chars", "checked_at"]
    row = {k: res.get(k, "") for k in keep}
    cache = load_cache()
    cache = cache[cache["auction_id"] != res["auction_id"]]
    cache = pd.concat([cache, pd.DataFrame([row])], ignore_index=True)
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    cache.to_csv(CACHE, index=False, encoding="utf-8-sig")


def inspect_and_cache(auction_id: str, use_llm: bool = True) -> dict:
    res = inspect(auction_id, use_llm)
    if res.get("verdict"):
        save_result(res)
    return res
