# -*- coding: utf-8 -*-
"""買いアラートと売りアラート。

**買い** — 工場(souba-league/src/factory.py)が発火した進行中ヤフオクのうち、
まだ終わっとらんもの。ただし工場は等級を見とらんので、ここで等級を貼り直す。
🔴 の型番のシグナルは**握り潰す**(母集団が腐っとると分かっとる型番に
実弾を入れる理由が無い)。

**売り** — 出口(買取表)が動いた型番。買取価格は日次スナップで全量退避されとるので、
前日との差分がそのまま「出口の改善/悪化」になる。
  * 下落 → 保有しとるなら急げ。買取表は一方向にしか動かん癖がある
  * 上昇 → その型番の裁定窓が開いた。買いアラート側の閾値も自動で上がる
"""
from __future__ import annotations

import time

import numpy as np
import pandas as pd

from . import sources as S
from . import watchlist as W

# 出口の変化として意味のある最小額。ノイズ(±数百円)を切る
MOVE_MIN_YEN = 2000
MOVE_MIN_PCT = 0.03


def buy_alerts(master: pd.DataFrame, include_dead: bool = False) -> pd.DataFrame:
    """進行中の買いシグナル。等級つき・残り時間つき。"""
    frames = [W.load_signals(n) for n in S.NICHES]
    sig = pd.concat([f for f in frames if not f.empty], ignore_index=True) \
        if any(not f.empty for f in frames) else pd.DataFrame()
    if sig.empty:
        return sig

    now = time.time()
    live = sig[(sig["status"] == "open") & (sig["end_ts"] > now)].copy()
    if live.empty:
        return live

    live["残り時間h"] = ((live["end_ts"] - now) / 3600).round(1)
    live["現在価格"] = live["last_price"].fillna(live["first_price"])
    live["想定純利"] = live["exit_net"] - live["現在価格"] - live["ship"]
    live["余力"] = live["max_bid"] - live["現在価格"]
    # 工場は発火後も last_price を更新し続けるので、上限を抜かれた個体が
    # open のまま残る。もう買えんのやからアラートから外す。
    live = live[live["余力"] >= 0]
    if live.empty:
        return live

    cols = ["family", "商品", "等級", "判定", "根拠", "生存", "検品n", "生存率",
            "期待粗利180d", "ニッチ"]
    live = live.merge(master[cols], on="family", how="left")
    live["等級"] = live["等級"].fillna("?")
    live["判定"] = live["判定"].fillna(W.GRADE_LABEL["?"])
    live["商品"] = live["商品"].fillna(live["family"])

    if not include_dead:
        live = live[live["等級"] != "C"]

    live["_ord"] = live["等級"].map(W.GRADE_ORDER)
    return live.sort_values(["_ord", "残り時間h"], ascending=[True, True])


def buyback_moves(niche: str = "camera") -> tuple[str, str, pd.DataFrame]:
    """買取表の日次差分。(前スナップ日, 最新スナップ日, 差分df)"""
    if S.CLOUD:
        a, _, b = (S.snap_meta().get("買取表の差分", " → ")).partition(" → ")
        return a, b, S.snap("moves")
    cfg = S.NICHES[niche]
    snaps = S.snapshots(niche)
    if len(snaps) < 2:
        return "", "", pd.DataFrame()
    (d_old, p_old), (d_new, p_new) = snaps[-2], snaps[-1]
    key, price, title = cfg["snapshot_key"], cfg["snapshot_price"], cfg["snapshot_title"]
    usecols = [key, title, price]
    a = S.read_csv(p_old, dtype={key: str}, usecols=usecols)
    b = S.read_csv(p_new, dtype={key: str}, usecols=usecols)
    if a.empty or b.empty:
        return d_old, d_new, pd.DataFrame()

    m = a.merge(b, on=key, suffixes=("_旧", "_新"))
    m["旧"] = pd.to_numeric(m[f"{price}_旧"], errors="coerce")
    m["新"] = pd.to_numeric(m[f"{price}_新"], errors="coerce")
    m["差額"] = m["新"] - m["旧"]
    m["変化率"] = m["差額"] / m["旧"].replace(0, np.nan)
    m["商品"] = m[f"{title}_新"]
    moved = m[(m["差額"].abs() >= MOVE_MIN_YEN)
              & (m["変化率"].abs() >= MOVE_MIN_PCT)].copy()
    moved["向き"] = np.where(moved["差額"] > 0, "📈 上昇", "📉 下落")
    return d_old, d_new, moved.sort_values("差額", key=abs, ascending=False)


def _watched_titles(master: pd.DataFrame) -> dict[str, str]:
    """キタムラの商品名 → family。models の master_title がそのまま鍵になる。"""
    m = master.dropna(subset=["master_title"])
    m = m[m["master_title"].astype(str).str.len() > 0]
    return dict(zip(m["master_title"], m["family"]))


def sell_alerts(master: pd.DataFrame, niche: str = "camera") -> tuple[str, str, pd.DataFrame]:
    """監視中の型番に起きた出口の変化だけを抜く。"""
    if S.CLOUD:
        a, _, b = (S.snap_meta().get("買取表の差分", " → ")).partition(" → ")
        return a, b, S.snap("sell_hits")
    d_old, d_new, moved = buyback_moves(niche)
    if moved.empty:
        return d_old, d_new, moved
    t2f = _watched_titles(master)
    moved["family"] = moved["商品"].map(t2f)
    hit = moved.dropna(subset=["family"]).copy()
    if hit.empty:
        return d_old, d_new, hit
    hit = hit.merge(master[["family", "等級", "判定", "ニッチ", "商品"]],
                    on="family", how="left", suffixes=("", "_m"))
    hit["含み"] = np.where(hit["差額"] > 0,
                           "出口が改善。上限入札も上がる",
                           "出口が悪化。保有分は急いで出せ")
    return d_old, d_new, hit.sort_values("差額", key=abs, ascending=False)


def holdings_pl(master: pd.DataFrame, niche: str = "camera") -> pd.DataFrame:
    """保有玉(data/holdings.csv)の現在価値。買取表の最新値で評価する。"""
    h = S.read_csv(S.DATA / "holdings.csv")
    if h.empty:
        return h
    h["仕入値"] = pd.to_numeric(h.get("仕入値"), errors="coerce")
    snaps = S.snapshots(niche)
    cur = {}
    if snaps:
        cfg = S.NICHES[niche]
        last = S.read_csv(snaps[-1][1],
                          usecols=[cfg["snapshot_title"], cfg["snapshot_price"]])
        if not last.empty:
            t2f = _watched_titles(master)
            last["family"] = last[cfg["snapshot_title"]].map(t2f)
            last = last.dropna(subset=["family"])
            cur = dict(zip(last["family"],
                           pd.to_numeric(last[cfg["snapshot_price"]], errors="coerce")))
    h["現在買取"] = h["family"].map(cur)
    ship = h["family"].map(
        lambda f: S.NICHES[master.set_index("family")["niche"].get(f, "camera")]["ship_default"]
        if f in set(master["family"]) else 1000)
    h["手取り見込"] = (h["現在買取"] * S.HAIRCUT - ship).round()
    h["含み損益"] = h["手取り見込"] - h["仕入値"]
    return h
