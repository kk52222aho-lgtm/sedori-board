# -*- coding: utf-8 -*-
"""勝てる商品マスタ — 「どの型番なら実弾を入れてええか」を1枚に落とす。

## 採点の思想(souba-league の実測から来とる。変えるときは根拠を持ってこい)

タイトルフィルタが出す候補は**85〜89%がゴミ**やった(カメラ個体検証20件中17件撃墜、
楽器43件中35件kill)。つまり:

  * **スプレッドの大きさは勝てる証拠にならん。** むしろ大スプレッドは
    「良品価格に腐った個体がマッチした」誤マッチの濃縮標本や。
  * **証拠は本文検品を通った件数だけ。** ここでは verified CSV の
    body_verdict == keep を唯一の生存カウントとする。
  * **紙上WON(工場台帳)は証拠にならん。** max_bid で買えたかを見とるだけで、
    その個体が良品やったかは見とらん。バッジとして出すが等級は上げん。

期待粗利は「keep件数 × keep時の粗利中央値」= **180日あたりの実弾見込み額**。
候補CSVが180日窓の落札から作られとるので、そのまま月商の12分の6になる。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from . import sources as S

# 等級のしきい値。180日で1万円未満なら「事業やない」(楽器の最終判定¥6,090/180日
# = 月¥1,015 を『事業やない』と切った前例に合わせる)
GO_YEN_180D = 10000
MIN_N_FOR_KILL = 3      # これ未満のnで「死」とは言わん(標本不足)
MIN_LIQ = 10            # 180日でこれ未満の落札しか無い型番は「玉が薄い」

# 候補ゼロの型番を全部「未検品」に放り込むのは嘘や。180日の落札を全部見た上で
# 買取を超える安値が1件も出んかった型番(=⚫)と、そもそも収集しとらん型番(=⚪)は
# 意味が正反対で、前者は**結論が出とる**。実数は ⚫137 / ⚪9 やった。
GRADE_LABEL = {
    "A": "🟢 実弾GO",
    "B": "🟡 薄い",
    "S": "🟣 標本不足",
    "?": "⚪ 未収集",
    "L": "🔵 玉が薄い",
    "N": "⚫ スプレッド無し",
    "C": "🔴 死",
}
GRADE_ORDER = {"A": 0, "B": 1, "S": 2, "?": 3, "L": 4, "N": 5, "C": 6}
# 画面の初期表示。⚫と🔴は結論が出とるので畳む
DEFAULT_GRADES = ["A", "B", "S", "?", "L"]


def load_models(niche: str) -> pd.DataFrame:
    cfg = S.NICHES[niche]
    frames = []
    for p in cfg["models"]:
        d = S.read_csv(p)
        if not d.empty:
            frames.append(d)
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    df = df.drop_duplicates(subset="family", keep="first")
    df["買取"] = pd.to_numeric(df.get("buyback_a"), errors="coerce")
    if "master_title" not in df:
        df["master_title"] = ""
    if "sub_category" not in df:
        df["sub_category"] = ""
    name = df["master_title"].fillna("")
    df["商品"] = np.where(name.str.len() > 0, name, df["query"].fillna(df["family"]))
    return df[["family", "商品", "query", "買取", "sub_category", "master_title"]]


def load_verified(niche: str) -> pd.DataFrame:
    """本文検品済み候補。列名をニッチ間で正規化する。

    人手で覆した判定は data/human_verdicts.csv が最終権限を持つ。
    LLMも間違うし(2026-08-03の実測で生存4件中1件を落とした)、
    実物ページを人間が見た結論が一番強い。
    """
    cfg = S.NICHES[niche]
    frames = [S.read_csv(S.verified_path(niche) or "")]
    # 帯を分けて測った検品結果を足す(camera_cheap 等)。列は同じスキーマ。
    frames += [S.read_csv(p) for p in cfg.get("verified_extra", [])]
    frames = [f for f in frames if not f.empty]
    if not frames:
        return pd.DataFrame()
    d = pd.concat(frames, ignore_index=True).drop_duplicates(subset="auction_id")
    human = S.read_csv(S.DATA / "human_verdicts.csv", dtype={"auction_id": str})
    if not human.empty and "auction_id" in d:
        override = dict(zip(human["auction_id"], human["verdict"]))
        d["auction_id"] = d["auction_id"].astype(str)
        d["overridden"] = d["auction_id"].isin(override)
        d["body_verdict"] = d["auction_id"].map(override).fillna(d["body_verdict"])
    buy = next((c for c in cfg["buyback_cols"] if c in d), None)
    d = d.rename(columns={buy: "buyback"}) if buy else d.assign(buyback=np.nan)
    for c in ("price", "buyback", "gross", "gross_hc", "bids"):
        if c in d:
            d[c] = pd.to_numeric(d[c], errors="coerce")
    d["niche"] = niche
    return d


def load_signals(niche: str) -> pd.DataFrame:
    cfg = S.NICHES[niche]
    if S.CLOUD:
        d = S.snap("signals", dtype={"auction_id": str})
        d = d[d["niche"] == niche] if "niche" in d else d
    else:
        d = S.read_csv(cfg["signals"], dtype={"auction_id": str})
    if d.empty:
        return d
    for c in ("buyback_a", "exit_net", "max_bid", "first_price", "last_price",
              "end_ts", "final_price", "realized_net", "ship"):
        if c in d:
            d[c] = pd.to_numeric(d[c], errors="coerce")
    d["ship"] = d["ship"].fillna(cfg["ship_default"])
    d["niche"] = niche
    return d


def load_closed(niche: str, filtered: bool = True) -> pd.DataFrame:
    """180日の落札。型番ごとの流動性(=そもそも玉が出るか)の唯一の出所。

    **生の行を数えたらあかん。** yahoo_closed.csv はクエリのヒットを全部
    持っとって、X100V の行には互換バッテリーもフードも混ざる(実測: 生1000行・
    落札中央¥9,999、本体は¥18万)。玉の数として数えてええのは
    工場が実際に入札対象にする行だけやから、判定は factory.title_ok を借りる
    (ここで自前の正規表現を書いたら、工場と盤で「玉」の定義がズレる)。
    """
    frames = [S.read_csv(p) for p in S.NICHES[niche].get("closed", [])]
    frames = [f for f in frames if not f.empty]
    if not frames:
        return pd.DataFrame()
    raw = pd.concat(frames, ignore_index=True).drop_duplicates(subset="auction_id")
    if not filtered:
        return raw

    specs, fac = _factory_specs(niche)
    if not specs:
        return raw
    price = pd.to_numeric(raw["price"], errors="coerce")
    keep = []
    for i, (fam, title, p) in enumerate(zip(raw["family"], raw["title"], price)):
        spec = specs.get(fam)
        keep.append(bool(spec) and isinstance(title, str)
                    and fac.title_ok(spec, title)
                    and p >= fac.PRICE_FLOOR * spec["a"])
    return raw[pd.Series(keep, index=raw.index)]


def _factory_specs(niche: str):
    """工場と同じ型番スペックとフィルタ束を借りる。"""
    import importlib
    import sys

    sys.path.insert(0, str(S.SOUBA / "src"))
    try:
        fac = importlib.import_module("factory")
        mod = importlib.import_module(S.NICHES[niche]["spread_module"])
    except Exception:
        return {}, None
    # factory はモジュール変数でフィルタ束を切り替える(--niche と同じ手口)
    fac.PARTS_RE = mod.PARTS_RE
    fac.JUNK_RE = mod.JUNK_RE
    fac.COMPAT_RE = getattr(mod, "COMPAT_RE", None)
    fac.PRICE_FLOOR = mod.PRICE_FLOOR
    try:
        fams = fac.load_models([Path(p) for p in S.NICHES[niche]["models"]])
    except Exception:
        return {}, None
    return {f["family"]: f for f in fams}, fac


def _grade(n_closed: int, n_raw: int, n: int, keep: int,
           yen180: float) -> tuple[str, str]:
    if n == 0:
        if n_raw == 0:
            return "?", "180日の落札をまだ集めとらん。等級を付ける根拠が無い"
        if n_closed == 0:
            return "L", (f"検索は{n_raw}件当たったが、本体の落札は180日で0件"
                         "(部品・互換品・別世代だけ)。仕入れる玉が存在せん")
        if n_closed >= MIN_LIQ:
            return "N", (f"180日で本体が{n_closed}件落ちたが、買取を超える安値は"
                         "1件も出んかった。母集団は厚いのにスプレッドが立たん")
        return "L", f"180日で本体が{n_closed}件しか落ちとらん。玉が薄くて判定できん"
    if keep == 0:
        if n >= MIN_N_FOR_KILL:
            return "C", f"検品{n}件が全滅。母集団が腐っとる型番"
        return "S", f"検品{n}件のみで全滅。標本不足でまだ死とは言えん(要追試)"
    if yen180 >= GO_YEN_180D:
        return "A", f"検品を{keep}/{n}件が通過し、180日で¥{yen180:,.0f}の見込み"
    return "B", f"検品は{keep}/{n}件通ったが180日で¥{yen180:,.0f}。手間に合わん"


def build_master() -> pd.DataFrame:
    """全ニッチの型番マスタ。1行=1型番、等級つき。"""
    if S.CLOUD:                       # クラウドは計算済みを読むだけ
        return S.snap("master")
    rows = []
    for niche, cfg in S.NICHES.items():
        models = load_models(niche)
        ver = load_verified(niche)
        sig = load_signals(niche)

        if not ver.empty:
            ver["is_keep"] = ver["body_verdict"].eq("keep")
            agg = ver.groupby("family").agg(
                検品n=("body_verdict", "size"),
                生存=("is_keep", "sum"),
                生存粗利中央=("gross_hc", lambda s: s[ver.loc[s.index, "is_keep"]].median()),
                粗利中央_全=("gross_hc", "median"),
            )
        else:
            agg = pd.DataFrame(columns=["検品n", "生存", "生存粗利中央", "粗利中央_全"])

        if not sig.empty:
            sg = sig.groupby("family").agg(
                シグナル=("auction_id", "size"),
                紙上勝=("status", lambda s: (s == "settled_won").sum()),
                紙上負=("status", lambda s: (s == "settled_lost").sum()),
                紙上純利=("realized_net", "sum"),
                稼働中=("status", lambda s: (s == "open").sum()),
            )
        else:
            sg = pd.DataFrame(columns=["シグナル", "紙上勝", "紙上負", "紙上純利", "稼働中"])

        closed = load_closed(niche)
        raw = load_closed(niche, filtered=False)
        if not closed.empty:
            cl = closed.groupby("family").agg(
                流動性180d=("auction_id", "size"),
                落札中央=("price", "median"),
            )
        else:
            cl = pd.DataFrame(columns=["流動性180d", "落札中央"])
        if not raw.empty:
            cl = cl.join(raw.groupby("family").size().rename("生ヒット"), how="outer")
        else:
            cl["生ヒット"] = 0

        m = (models.set_index("family")
             .join(agg, how="outer").join(sg, how="outer").join(cl, how="outer"))
        m = m.reset_index().rename(columns={"index": "family"})
        m["niche"] = niche
        m["ニッチ"] = cfg["label"]
        m["出口"] = cfg["channel"]
        rows.append(m)

    df = pd.concat(rows, ignore_index=True)
    for c in ("検品n", "生存", "シグナル", "紙上勝", "紙上負", "稼働中",
              "流動性180d", "生ヒット"):
        df[c] = pd.to_numeric(df.get(c), errors="coerce").fillna(0).astype(int)
    for c in ("生存粗利中央", "粗利中央_全", "紙上純利", "買取", "落札中央"):
        df[c] = pd.to_numeric(df.get(c), errors="coerce")

    df["生存率"] = np.where(df["検品n"] > 0, df["生存"] / df["検品n"], np.nan)
    df["期待粗利180d"] = (df["生存"] * df["生存粗利中央"].fillna(0)).clip(lower=0)
    graded = df.apply(lambda r: _grade(r["流動性180d"], r["生ヒット"], r["検品n"],
                                       r["生存"], r["期待粗利180d"]),
                      axis=1, result_type="expand")
    df["等級"] = graded[0]
    df["根拠"] = graded[1]
    df["判定"] = df["等級"].map(GRADE_LABEL)
    df["上限入札"] = (df["買取"] * S.HAIRCUT
                      - df["niche"].map(lambda n: S.NICHES[n]["ship_default"])
                      - S.NET_MIN).round()
    df["商品"] = df["商品"].fillna(df["family"])
    df["_ord"] = df["等級"].map(GRADE_ORDER)
    return df.sort_values(["_ord", "期待粗利180d"], ascending=[True, False])


def live_winners() -> pd.DataFrame:
    """**いま買える玉**。進行中ヤフオク × 勝ち語(souba-league/src/live_winners.py)。

    下の winners() は落札済みの回顧やから買えん。こっちが本物の買い物リストや。
    """
    d = (S.snap("live_winners", dtype={"auction_id": str}) if S.CLOUD
         else S.read_csv(S.SOUBA / "data/camera/live_winners.csv",
                         dtype={"auction_id": str}))
    if d.empty:
        return d
    for c in ("現在価格", "max_bid", "想定純利", "勝ち語", "残り時間h"):
        if c in d:
            d[c] = pd.to_numeric(d[c], errors="coerce")
    human = S.read_csv(S.DATA / "human_verdicts.csv", dtype={"auction_id": str})
    if not human.empty:
        d = d[~d["auction_id"].isin(set(human[human["verdict"] == "kill"]["auction_id"]))]
    d["段"] = np.where(d["勝ち語"] >= 5, "🏆 実弾GO",
                       np.where(d["勝ち語"] >= 4, "👍 買える", "🤏 見送り"))
    return d.sort_values(["勝ち語", "想定純利"], ascending=False)


def winners() -> pd.DataFrame:
    """**過去の実績サンプル**。「こういう玉なら勝てた」であって**買えるものやない**。

    元は yahoo_closed.csv = 180日の**落札済み**。2026-08-08に実際にリンクを
    開いて発覚した——盤が「買い物リスト」と名乗って出しとった玉は全部2〜6月に
    終わっとった。**看板に偽りがあった。** 買える玉は live_winners() を見ること。

    等級(型番単位)やのうて**玉単位**の答えや。「どの型番が有望か」やのうて
    「この玉を買え」を出す。撃墜語で殺した残りやのうて、
    **出品者が状態を保証しとる語**で選んどるのが違い。
    人手判定(human_verdicts.csv)は最終権限としてここにも効かせる。
    """
    d = (S.snap("winners", dtype={"auction_id": str}) if S.CLOUD
         else S.read_csv(S.SOUBA / "data/camera/winners.csv",
                         dtype={"auction_id": str}))
    if d.empty:
        return d
    if S.CLOUD:                       # 段/url は書き出し済み
        return d
    human = S.read_csv(S.DATA / "human_verdicts.csv", dtype={"auction_id": str})
    if not human.empty:
        killed = set(human[human["verdict"] == "kill"]["auction_id"])
        d = d[~d["auction_id"].isin(killed)]
    for c in ("price", "gross_hc", "win_score"):
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d["url"] = "https://auctions.yahoo.co.jp/jp/auction/" + d["auction_id"]
    d["段"] = np.where(d["win_score"] >= 5, "🏆 実弾GO",
                       np.where(d["win_score"] >= 3, "👍 買える", "🤏 見送り"))
    return d.sort_values(["win_score", "gross_hc"], ascending=False)


def survivors(master: pd.DataFrame) -> pd.DataFrame:
    """実弾GOだけ。トップ画面はこれしか出さん。"""
    return master[master["等級"] == "A"]


def keep_items(niche: str) -> pd.DataFrame:
    """検品を通った個体そのもの(=実際に勝てた玉の実例)。"""
    if S.CLOUD:
        d = S.snap("keeps")
        lab = S.NICHES[niche]["label"]
        return d[d["ニッチ"] == lab] if "ニッチ" in d else d
    d = load_verified(niche)
    if d.empty:
        return d
    return d[d["body_verdict"] == "keep"].sort_values("gross_hc", ascending=False)
