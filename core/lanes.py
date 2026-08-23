# -*- coding: utf-8 -*-
"""**どこで買って、どこで売るか**を1枚に並べる。国内と輸出をまとめて。

## この盤での位置
sedori-board は計算せん。ここも同じで、souba-league が既に出した数字を
**形を揃えるだけ**や。粗利の式をこっちで書き直したら、`is_body` の門が
ニッチ間でズレたのと同じ事故になる(`check_gates.py` がある理由)。

## クラウドでどう動くか
`streamlit.app` には `C:\\dev\\souba-league` が無い。`export_snapshot.py` が
ローカルで正規化して `data/snapshot/lanes.csv` に落とし、クラウドはそれだけ読む。
`sources.CLOUD` の分岐は他のデータ源と同じ作りにしてある。

## 2種類のレーンは数字の温度がちゃう
- **輸出(相場)** — 1行=1機種。**ヤフオク落札(p25) → eBay US 実売(中央)**。
  中央値の推定で、目の前に玉は無い。年に何台出るかまで読む
- **国内(現物)** — 1行=**いま出とる1個**。**フリマ現物 → ヤフオク再出品**。
  URLを開けばそこにある。売れたら消える

出口の「ヤフオク再出品」は 落札中央値 ×(1−IQRマージン)×(1−落札手数料10%)− 送料¥1,000。
買取店に売る話やない——**自分が売り手に回る**。査定人が自分になるぶんの状態リスクは
こっち持ちで、その保守側の倒しが IQRマージンや。

同じ表に混ぜると、机上の中央値と目の前の1個が同じ重さに見えてまう。**列で分ける。**
"""
from __future__ import annotations

from urllib.parse import quote_plus

import pandas as pd

from . import sources as S

FLIP_MARKET = {
    "flea_candidates.csv": "Yahoo!フリマ",
    "mercari_candidates.csv": "メルカリ",
    "rakuma_candidates.csv": "ラクマ",
}

# ---- 行から直接飛べる場所。**盤で見て、その足で動けるように** ----
# 検索語は souba-league が実際に使っとる jp_q / ebay_q をそのまま流用する。
# ここで自前のクエリを作ったら、盤で見た母集団と飛んだ先の母集団がズレる。
YAHOO_SEARCH = "https://auctions.yahoo.co.jp/search/search?p={q}&s1=end&o1=a"
EBAY_SOLD = "https://www.ebay.com/sch/i.html?_nkw={q}&LH_Sold=1&LH_Complete=1"
AUCFREE = "https://aucfree.com/search?q={q}"


def _q(v) -> str:
    return quote_plus(str(v or "").strip())


NUMERIC = ("仕入値", "売値", "引かれ", "純利", "年台数", "年間粗利", "関税",
           "買い線", "汚染率", "出口n", "入口n")
TEXTUAL = ("品", "レーン", "種別", "仕入面", "売面", "玉", "根拠", "url",
           "買いに行く", "売りに行く",
           "帯", "構成", "構成差", "出口状態", "型番弱")

# ---- 旗の閾値。**画面のスライダーで動かせるが、既定はここが正本や** ----
MIN_BUY_RATIO = 0.05   # 仕入値が売値のこれ未満 = 引き算の左右がズレとる疑い
DIRTY = 0.15           # purity の汚染率がこれ以上 = 母集団に別物が混ざっとる
THIN_N = 10            # 出口/入口の標本がこれ未満 = 中央値が数件で動く
                       # (5やと PXW-Z190 の出口n=6 が通ってまう。
                       #  1台¥12万の判断が6件の中央値に乗るのは薄い)


def _num(df: pd.DataFrame, *cols: str) -> None:
    for c in cols:
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="coerce")


def _export_from_souba() -> pd.DataFrame:
    """輸出レーン。**粗利/台は two_sided.csv の計算をそのまま使う。**"""
    p = S.SOUBA / "data" / "two_sided.csv"
    if not p.exists():
        return pd.DataFrame()
    d = S.read_csv(p)
    if d.empty:
        return pd.DataFrame()
    _num(d, "送料", "out_中央", "in_p25", "in_中央", "粗利/台", "関税自腹",
         "買い線", "out_年台数", "年間粗利")
    buy = d["in_p25"].fillna(d["in_中央"])
    q = _model_queries()
    jp = d["機種"].map(lambda m: q.get(m, ("", ""))[0])
    us = d["機種"].map(lambda m: q.get(m, ("", ""))[1])
    out = pd.DataFrame({
        "品": d["機種"], "レーン": "ヤフオク → eBay US", "種別": "輸出(相場)",
        "仕入面": "ヤフオク(落札p25)", "仕入値": buy,
        "売面": "eBay US(実売中央)", "売値": d["out_中央"],
        # 引かれ = 売値 - 仕入 - 粗利。手数料・送料・関税をまとめた実効控除
        "引かれ": d["out_中央"] - buy - d["粗利/台"],
        "純利": d["粗利/台"], "年台数": d["out_年台数"],
        "年間粗利": d["年間粗利"], "関税": d["関税自腹"], "買い線": d["買い線"],
        "玉": "", "url": "",
        "買いに行く": jp.map(lambda v: YAHOO_SEARCH.format(q=_q(v)) if v else ""),
        "売りに行く": us.map(lambda v: EBAY_SOLD.format(q=_q(v)) if v else ""),
        "根拠": "two_sided.csv(Terapeak 3年実売 × aucfree 12ヶ月)",
    })
    g = _grades()
    if not g.empty:
        out = out.merge(g, on="品", how="left")
    return out[out["純利"].notna()]


def _grades() -> pd.DataFrame:
    p = S.SOUBA / "data" / "purity.csv"
    if not p.exists():
        return pd.DataFrame()
    d = S.read_csv(p)
    if d.empty:
        return pd.DataFrame()
    _num(d, "汚染率", "出口n", "入口n")
    keep = [c for c in ("機種", "帯", "汚染率", "出口n", "入口n", "構成",
                        "構成差", "出口状態", "型番弱") if c in d]
    return d[keep].rename(columns={"機種": "品"})


def _model_queries() -> dict[str, tuple[str, str]]:
    """機種 -> (ヤフオクの検索語, eBayの検索語)。souba-league の定義をそのまま借りる。"""
    p = S.SOUBA / "data" / "models_export.csv"
    if not p.exists():
        return {}
    d = S.read_csv(p)
    if d.empty or "機種" not in d:
        return {}
    return {r["機種"]: (str(r.get("jp_q") or ""), str(r.get("ebay_q") or ""))
            for _, r in d.iterrows()}


def _family_queries() -> dict[str, str]:
    """family -> 検索語。国内行の「売りに行く」(落札相場)を作るのに要る。

    出所は2つ。**master.csv だけでは prospect 系(p_kitchen_* など)が引けん**で、
    国内78行のうち65行がリンク無しになった。souba-league の models/*.csv が
    family と query を持っとるので、そっちも全部舐める。
    """
    out: dict[str, str] = {}
    paths = [S.DATA / "snapshot" / "master.csv"]
    paths += sorted((S.SOUBA / "models").glob("*.csv"))
    for path in paths:
        if not path.exists():
            continue
        d = S.read_csv(path)
        if d.empty or "family" not in d or "query" not in d:
            continue
        for _, r in d.iterrows():
            fam = str(r.get("family") or "").strip()
            q = str(r.get("query") or "").strip()
            if fam and q:
                out.setdefault(fam, q)
    return out


def _domestic_from_souba() -> pd.DataFrame:
    """国内レーン。**1行=いま出とる現物1個**や。売切と kill は落とす。"""
    fam_q = _family_queries()
    rows = []
    for fname, market in FLIP_MARKET.items():
        p = S.SOUBA / "data" / "flip" / fname
        if not p.exists():
            continue
        d = S.read_csv(p)
        if d.empty:
            continue
        _num(d, "price", "median", "net")
        if "status" in d:
            d = d[d["status"].fillna("") != "SOLD"]
        if "verdict" in d:
            d = d[d["verdict"].fillna("") != "kill"]
        d = d[d["net"].notna()]
        if d.empty:
            continue
        rows.append(pd.DataFrame({
            "品": d.get("title", "").astype(str).str.slice(0, 46),
            "レーン": f"{market} → ヤフオク", "種別": "国内(現物)",
            "仕入面": market, "仕入値": d["price"],
            "売面": "ヤフオク(再出品)", "売値": d["median"],
            "引かれ": d["median"] - d["price"] - d["net"],
            "純利": d["net"], "年台数": float("nan"),
            "玉": d.get("family", ""), "url": d.get("url", ""),
            "買いに行く": d.get("url", ""),
            "売りに行く": d.get("family", "").map(
                lambda f: AUCFREE.format(q=_q(fam_q.get(f, ""))) if fam_q.get(f) else ""),
            "根拠": fname,
        }))
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def combine(*frames: pd.DataFrame) -> pd.DataFrame:
    """列と型を揃えてから縦に積む。

    輸出と国内で列がちゃう(年間粗利・帯・汚染率は輸出だけ)。全NAの列を放って
    concat すると dtype が決まらず、pandas が将来の挙動変更を警告する。
    """
    frames = [f for f in frames if f is not None and not f.empty]
    if not frames:
        return pd.DataFrame(columns=list(TEXTUAL) + list(NUMERIC))
    cols = []
    for f in frames:
        for c in f.columns:
            if c not in cols:
                cols.append(c)
    fixed = []
    for f in frames:
        g = f.reindex(columns=cols)
        for c in cols:
            if c in NUMERIC:
                g[c] = pd.to_numeric(g[c], errors="coerce").astype("float64")
            elif c in TEXTUAL:
                g[c] = g[c].fillna("").astype(str)
        fixed.append(g)
    return pd.concat(fixed, ignore_index=True)


def build() -> pd.DataFrame:
    """souba-league から作る。**export_snapshot.py 専用**(ローカルでしか動かん)。"""
    return combine(_export_from_souba(), _domestic_from_souba())


def load() -> pd.DataFrame:
    """画面が呼ぶ入口。クラウドはスナップショット、ローカルは生から。"""
    if S.CLOUD:
        d = S.snap("lanes")
        if d is None or d.empty:
            return pd.DataFrame(columns=list(TEXTUAL) + list(NUMERIC))
        for c in NUMERIC:
            if c in d:
                d[c] = pd.to_numeric(d[c], errors="coerce")
        for c in TEXTUAL:
            if c in d:
                d[c] = d[c].fillna("").astype(str)
        return d
    return build()


# ---------------------------------------------------------------- 旗

def flags(df: pd.DataFrame, ratio: float | None = None,
          dirty: float | None = None, thin: int | None = None) -> pd.DataFrame:
    """行ごとに「なんで信用できんか」を並べる。空欄=旗なし。

    **これが盤の背骨や。** 純利の降順は、引き算の左右がズレた玉を必ず上位に置く
    (2026-08-19 PW3360 の「+¥105,730」は日本の単体価格×米国のセット価格やった。
    2026-08-22 には TECHNICS SL-1200G が「仕入¥1,000 / 売¥510,543」で首位に来た)。
    旗が立った行は買いキューやのうて**監査キュー**に落とす。
    """
    r = MIN_BUY_RATIO if ratio is None else ratio
    dt = DIRTY if dirty is None else dirty
    tn = THIN_N if thin is None else thin
    if df.empty:
        d = df.copy()
        d["要注意"] = pd.Series(dtype=str)
        return d
    d = df.copy()

    def num(c: str) -> pd.Series:
        """欠けとる列は**全部NaNの列**として扱う。

        `pd.to_numeric(None)` はスカラの nan を返すので、そのまま `.get(i)` すると
        `'numpy.float64' object has no attribute 'get'` で落ちる。`combine()` を
        通した表なら列は揃っとるが、国内だけ・輸出だけの表を直接渡されると欠ける。
        """
        if c in d:
            return pd.to_numeric(d[c], errors="coerce")
        return pd.Series(float("nan"), index=d.index, dtype="float64")

    buy, sell = num("仕入値"), num("売値")
    dirty_s, years = num("汚染率"), num("年台数")
    outn, inn = num("出口n"), num("入口n")
    out = []
    for i in d.index:
        w = []
        b, s_ = buy.get(i), sell.get(i)
        if pd.notna(b) and pd.notna(s_) and s_ > 0 and b / s_ < r:
            w.append(f"入口が売値の{b / s_ * 100:.1f}%=左右ズレ疑い")
        v = dirty_s.get(i)
        if pd.notna(v) and v >= dt:
            w.append(f"汚染{v * 100:.0f}%")
        # 輸出レーンは purity が標本数を出しとる。**空欄は「薄くない」やのうて
        # 「分からん」**や(構成を割れんかった行がそうなる)。0件と未測を同じ
        # 入れ物に入れると盤が嘘をつくのと同じ話で、不明も旗を立てる。
        is_export = str(d["種別"].get(i) if "種別" in d else "").startswith("輸出")
        for series, lab in ((outn, "出口"), (inn, "入口")):
            v = series.get(i)
            if pd.notna(v):
                if v < tn:
                    w.append(f"{lab}標本{int(v)}件")
            elif is_export:
                w.append(f"{lab}標本が不明")
        v = years.get(i)
        if pd.notna(v) and v < 1:
            w.append(f"年{v:.1f}台=待ち")
        comp = d["構成"].get(i) if "構成" in d else None
        if isinstance(comp, str) and "セット" in comp:
            w.append("構成にセット混在")
        # purity が既に出しとる2つ。**盤が見てへんかった**(2026-08-22)。
        # DAIWA EXIST が「旗なし首位・年間粗利508万」に居座っとった原因や。
        # 入口p25 ¥9,000 に対し中央 ¥28,273 = 替えスプールや部品が混ざっとる。
        diff = d["構成差"].get(i) if "構成差" in d else None
        if isinstance(diff, str) and diff.strip():
            w.append(f"構成差[{diff.strip()}]")
        weak = d["型番弱"].get(i) if "型番弱" in d else None
        if isinstance(weak, str) and weak.strip():
            w.append(f"型番弱[{weak.strip()}]")
        out.append(" / ".join(w))
    d["要注意"] = out
    return d


def clean(df: pd.DataFrame) -> pd.DataFrame:
    """旗の立っとらん行だけ。**ここが「今の盤で信用できるレーン」**や。"""
    if df.empty or "要注意" not in df:
        return df
    return df[df["要注意"] == ""]


def paper_total(df: pd.DataFrame) -> float:
    """机上の年間粗利。**足したらあかん数字**やが規模感として出す。

    「買い線内で買えた玉が全部さばけたら」の値や。全機種を撃つ体力は無いし、
    上位ほど誤りが濃い。**必ず実績と並べて出す。**
    """
    if df.empty or "年間粗利" not in df:
        return 0.0
    return float(pd.to_numeric(df["年間粗利"], errors="coerce").fillna(0).sum())

def profitable(df: pd.DataFrame) -> pd.DataFrame:
    """純利がプラスの行だけ。

    **旗なし=データがきれい、であって儲かるとは限らん。** 2026-08-22 の実データで
    HXR-NX5R(−¥75,954)・TD-50(−¥126,964)・CONTAX T3(−¥200,424)が
    「信用できるレーン」に並んどった。**きれいに測れた死**や。買い候補と
    同じ表に置いたら盤が嘘をつく。
    """
    if df.empty or "純利" not in df:
        return df
    return df[pd.to_numeric(df["純利"], errors="coerce").fillna(0) > 0]
