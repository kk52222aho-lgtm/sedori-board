# -*- coding: utf-8 -*-
"""アラート常駐 — サイトを開いとらんときでも手元に飛ばす。

工場(souba-league/src/factory.py)も webhook を叩くが、あれは**等級を見とらん**。
ここは盤の等級で濾してから飛ばす:

  * 🔴(検品で全滅した型番)は握り潰す
  * 🟢/🟡 は自動で本文検品まで済ませて、撃墜なら飛ばさん
  * 売りアラート(買取表の下落)は保有玉に当たったときだけ飛ばす

    python watch.py                # 1周
    python watch.py --loop 20      # 20分おきに常駐
    python watch.py --no-inspect   # 検品せず素で飛ばす(速い)
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

from core import alerts as A
from core import inspect_live as IL
from core import sources as S
from core import watchlist as W

SENT = S.DATA / "alert_log.csv"
GRADE_TO_SEND = {"A", "B", "?"}


def _webhook() -> str | None:
    env = Path(r"C:\dev\.env")
    if not env.exists():
        return None
    for line in env.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("FACTORY_WEBHOOK_URL="):
            return line.split("=", 1)[1].strip().strip('"')
    return None


def _sent_keys() -> set[str]:
    d = S.read_csv(SENT)
    return set(d["key"]) if not d.empty and "key" in d else set()


def _record(rows: list[dict]) -> None:
    if not rows:
        return
    old = S.read_csv(SENT)
    new = pd.concat([old, pd.DataFrame(rows)], ignore_index=True) if not old.empty \
        else pd.DataFrame(rows)
    SENT.parent.mkdir(parents=True, exist_ok=True)
    new.to_csv(SENT, index=False, encoding="utf-8-sig")


def _say(msg: str, hook: str | None) -> None:
    sys.stdout.buffer.write(msg.encode(sys.stdout.encoding or "utf-8", "replace") + b"\n")
    sys.stdout.flush()
    if hook:
        try:
            requests.post(hook, json={"content": msg}, timeout=15)
        except requests.RequestException as exc:
            print(f"[webhook] {exc}", file=sys.stderr)


def cycle(inspect: bool, use_llm: bool, hook: str | None) -> int:
    master = W.build_master()
    sent = _sent_keys()
    fresh: list[dict] = []
    now = datetime.now().isoformat(timespec="seconds")

    # ---------------------------------------------------------- 買い
    live = A.buy_alerts(master, include_dead=False)
    rows = list(live.iterrows()) if not live.empty else []
    for _, r in rows:
        key = f"buy:{r['auction_id']}"
        if key in sent or r["等級"] not in GRADE_TO_SEND:
            continue
        verdict, hit = "", ""
        if inspect:
            res = IL.inspect_and_cache(r["auction_id"], use_llm)
            verdict, hit = res.get("verdict", ""), res.get("hit", "")
            if verdict == "kill":
                fresh.append({"key": key, "kind": "buy", "at": now,
                              "sent": 0, "note": f"検品で撃墜: {hit}"})
                continue
        mark = {"keep": "✅検品通過", "unknown": "❔判定不能", "": ""}.get(verdict, "")
        _say(f"🟩 買い {r['判定']} {r['商品']} ｜ 純利+{r['想定純利']:,.0f}円 "
             f"｜ 現在{r['現在価格']:,.0f}/上限{r['max_bid']:,.0f} "
             f"｜ 残{r['残り時間h']:.1f}h {mark}\n{r['url']}", hook)
        fresh.append({"key": key, "kind": "buy", "at": now, "sent": 1,
                      "note": f"{verdict} {hit}"[:120]})

    # ---------------------------------------------------------- 売り(保有玉のみ)
    held = A.holdings_pl(master)
    if not held.empty:
        d_old, d_new, hit = A.sell_alerts(master)
        if not hit.empty:
            mine = hit[hit["family"].isin(set(held["family"]))]
            for _, r in mine.iterrows():
                key = f"sell:{r['family']}:{d_new}"
                if key in sent:
                    continue
                _say(f"🟥 売り {r['向き']} {r['商品']} ｜ "
                     f"{r['旧']:,.0f} → {r['新']:,.0f} ({r['差額']:+,.0f}円) "
                     f"｜ {r['含み']}", hook)
                fresh.append({"key": key, "kind": "sell", "at": now, "sent": 1,
                              "note": f"{r['差額']:+.0f}"})

    _record(fresh)
    n_sent = sum(r["sent"] for r in fresh)
    print(f"[{now}] 買い候補{len(live)}件 / 新規通知{n_sent}件 "
          f"/ 検品で握り潰し{len(fresh) - n_sent}件", flush=True)
    return n_sent


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", type=float, default=0, help="分。0なら1周で終了")
    ap.add_argument("--no-inspect", action="store_true", help="本文検品を挟まん")
    ap.add_argument("--no-llm", action="store_true", help="検品をregexだけでやる")
    args = ap.parse_args()

    hook = _webhook()
    print(f"webhook={'on' if hook else 'off'} "
          f"inspect={'off' if args.no_inspect else 'on'}")
    while True:
        try:
            cycle(not args.no_inspect, not args.no_llm, hook)
        except Exception as exc:  # 常駐を1回の失敗で落とさん
            print(f"[cycle] {type(exc).__name__}: {exc}", file=sys.stderr)
        if not args.loop:
            return 0
        time.sleep(args.loop * 60)


if __name__ == "__main__":
    raise SystemExit(main())
