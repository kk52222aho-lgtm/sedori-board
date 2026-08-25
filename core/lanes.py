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

🚨 **その落札中央値は「その玉と同じ状態」のものだけで作る**(2026-08-25)。
前は新品の落札が混ざっとって、**中古を仕入れて新品の値段で売る**計算になっとった
(落札17,963行の13.0%が新品。新品と中古が両方2件以上ある159型番の**145=91%で
新品が高い**)。当てた効果はフリマ候補92件で **純利合計 ¥886,359 → ¥649,599**、
MAX HN-65N4 の玉は **+¥9,118 → −¥8,706 と符号が反転**した。
`状態` がその玉の判定、`出口基準` がどっちの中央値を当てたか。**2列とも空の行は
混ぜたままの古い走査**やから、旗が立って監査キューへ落ちる。

同じ表に混ぜると、机上の中央値と目の前の1個が同じ重さに見えてまう。**列で分ける。**
"""
from __future__ import annotations

import re
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
           "買い線", "入口中央", "買線内", "汚染率", "出口n", "入口n",
           "棚年数", "年利/台",
           "出口生", "出口本体", "期待粗利180d", "いま買える", "いま最安",
           "相場n", "相場p25", "売値$", "p25$", "売れる間隔", "実測滞留",
           "フリマなら")
TEXTUAL = ("品", "レーン", "種別", "仕入面", "売面", "玉", "根拠", "url",
           "買いに行く", "売りに行く", "走査", "検品", "等級",
           "帯", "構成", "構成差", "出口状態", "型番弱",
           # **「その玉の状態」と「どっちの中央値で売値を出したか」。**
           # 輸出は `構成`(枝番/セット/状態)が既に持っとる。国内は別列や
           "状態", "出口基準",
           # 🚨 **NUMERIC に入れとって `pd.to_numeric("ジャンク|…")` が NaN に
           # なり、旗が黙って消えとった**(2026-08-24)。同じ日に「欠損が有利側の
           # 値に化ける」を3件潰した直後に、俺が4件目を作っとった。
           # **列を足す時は型の登録先を必ず確かめる。**
           "マスク救済")

# ---- 旗の閾値。**画面のスライダーで動かせるが、既定はここが正本や** ----
# Reverb(楽器・音響の海外出口)。**式は souba-league の reverb_probe.py から借りる。**
#   FEE_XB = 0.1325(越境の手数料)/ ship = 2000 + kg*3000(国際送料のざっくり)
# こっちで作り直したら、向こうの判定と盤の数字がズレる。
# 🚨 **国内(現物)は生モノや。** 実測で候補の73%が27時間で売れる
# (2026-08-17)。走査からこの時間を過ぎた行は「いま買える」と言うたらあかん。
# 2026-08-24、盤の国内37本のうち14本(38%)が8〜9日前の走査やった——
# メルカリとラクマの走査器はブラウザが要るので定期実行に載っとらん。
# **status は走査した時にしか更新されんので、古い行は SOLD にならず生き残る。**
STALE_HOURS = 48

# 🚨 **買い線の内側=その商品、やない。**
# ヤフオク側は英語の ACC_RE しか通っとらんので、日本語の付属品が本体判定を抜ける:
#   ¥7,980 「marantz SACDプレーヤー SA-10 プリメインアンプ PM-10 純正 リモコン」
#   ¥4,400 「【製作品】Technics SL-1200GAE SL-1200G SL-1200GR SL-1500C …」
# しかも must_re の `SL-1200G` が `SL-1200GAE/GR` を飲むので対応表判定も効かん。
# 語彙で追うと際限が無いから**値段で切る**。入口p25のこの割合を下回る玉は、
# 40万のSACDプレーヤーが7,980円で出とる、いう話にしかならん。
LIVE_MIN_RATIO = 0.30

# 国内の出口の手数料。**値段の差は入っとらん。**
# ヤフオクだけが落札(実売)を測れとって、フリマ/メルカリ/ラクマは現在の出品しか
# 見えん(フリマの SOLD 57件は「買い線を割った安い玉」だけの偏った標本や)。
# せやから比べられるのは手数料だけ——同じ値段で売れたと仮定した時の差になる。
# 実際にはヤフオクは競りで上がることもあるし、フリマは即決で下に張り付く。
JP_EXIT_FEE = {"ヤフオク": 0.10, "Yahoo!フリマ": 0.05, "メルカリ": 0.10, "ラクマ": 0.06}
JP_EXIT_BASE = "ヤフオク"          # medians.csv の exit_net が前提にしとる面

REVERB_FEE = 0.1325
JPY = 163.5              # purity.py と同じレート
MIN_NET = 30000          # purity.py と同じ

MIN_BUY_RATIO = 0.05   # 仕入値が売値のこれ未満 = 引き算の左右がズレとる疑い
DIRTY = 0.15           # purity の汚染率がこれ以上 = 母集団に別物が混ざっとる
BODY_RATE = 0.20       # 打ち切りに当たった上で本体率がこれ未満 = 中央値が壊れとる
ENTRY_P25_RATIO = 0.6  # 入口p25が入口中央のこれ未満 = 安値側にゴミが残っとる
THIN_N = 10            # 出口/入口の標本がこれ未満 = 中央値が数件で動く
                       # (5やと PXW-Z190 の出口n=6 が通ってまう。
                       #  1台¥12万の判断が6件の中央値に乗るのは薄い)


def _col(d: pd.DataFrame, name: str) -> pd.Series:
    """欠けとる列を**全部空文字の Series** として返す。

    🚨 `d.get(name, "")` は列が無いと**文字列そのもの**を返すので、後ろの
    `.map()` や `.fillna()` が `'str' object has no attribute` で落ちる
    (2026-08-25、走査し直した直後の候補CSVに `verdict` がまだ無くて踏んだ)。
    **欠損は空欄として素通しさせる**——盤が落ちるのが一番あかん。
    """
    if name in d:
        return d[name].fillna("").astype(str)
    return pd.Series("", index=d.index, dtype=object)


def _num(df: pd.DataFrame, *cols: str) -> None:
    for c in cols:
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="coerce")


def _export_from_souba() -> pd.DataFrame:
    """輸出レーン。**出所は purity.csv**。

    以前は two_sided.csv を読んどったが、あれは**トリムも構成分割もしとらん
    生の中央値**や。purity.py は同じ元データに対して
      ①中央値の1/5未満を反復で落とす(部品の混入)
      ②構成(枝番・セット)で割ってから両側を突き合わせる
      ③標本の薄い構成は出口中央へ引き戻す(shrink)
    をやっとって、148機種のうち **62機種で出口中央が2%以上ちがう**。
    買い線は出口中央から決まるんやから、汚れた側で線を引いたら高く買わされる。

    **粗利/台・買い線・年間粗利は purity の計算をそのまま使う。** 2026-08-23 に
    purity.py へ「買い線」列を足したのは、盤で式を書き直さんで済ませるためや。
    """
    p = S.SOUBA / "data" / "purity.csv"
    if not p.exists():
        return pd.DataFrame()
    d = S.read_csv(p)
    if d.empty or "買い線" not in d:
        return pd.DataFrame()
    _num(d, "出口中央", "出口p25", "入口p25", "粗利/台", "買い線", "年間粗利",
         "年台数", "買線内", "汚染率", "出口n", "入口n", "出口生", "出口本体")
    d = d[d["粗利/台"].notna() & d["買い線"].notna()]
    if d.empty:
        return pd.DataFrame()
    q = _model_queries()
    live = _live_buys()

    def _hits(name: str, floor=None) -> list[dict]:
        k = _norm_model(name)
        got: list[dict] = []
        for t, v in live.items():
            if t and (t in k or k in t):
                got = v
                break
        if floor is not None and pd.notna(floor) and floor > 0:
            got = [x for x in got
                   if pd.notna(x["price"]) and x["price"] >= floor]
        return got

    jp = d["機種"].map(lambda m: q.get(m, ("", ""))[0])
    us = d["機種"].map(lambda m: q.get(m, ("", ""))[1])
    out = pd.DataFrame({
        "品": d["機種"], "レーン": "ヤフオク → eBay US", "種別": "輸出(相場)",
        "仕入面": "ヤフオク(落札p25)", "仕入値": d["入口p25"],
        "売面": "eBay US(実売中央)", "売値": d["出口中央"],
        # **いくらで売るか。** 円換算の中央値だけでは eBay に出せん。
        # p25 は「早く捌きたい時の下側」、中央は「そこで実際に捌けた値段」。
        # 裏付けの件数(出口n)を横に置いて、1件の中央値と区別できるようにする。
        # 米国市場が何日に1台吸収しとるか。**あんたの出品のETAやない**——
        # 他の出品と競るので、これは市場の回転の速さや
        "売れる間隔": (365.0 / d["年台数"]).where(d["年台数"] > 0),
        "売値$": d["出口中央"] / JPY,
        "p25$": d["出口p25"] / JPY,
        "相場n": d["出口n"], "相場p25": d["出口p25"],
        # 引かれ = 売値 − 仕入 − 粗利。手数料16%・国際送料・関税をまとめた実効控除
        "引かれ": d["出口中央"] - d["入口p25"] - d["粗利/台"],
        "純利": d["粗利/台"], "年台数": d["年台数"],
        "年間粗利": d["年間粗利"], "買い線": d["買い線"],
        "買線内": d["買線内"],
        # 入口中央は purity に無いので、安値ゴミの旗は「p25 が出口の何%か」に
        # 任せる。purity は既にトリム済みやから、そもそも安値ゴミは落ちとる
        "汚染率": d["汚染率"], "出口n": d["出口n"], "入口n": d["入口n"],
        "出口生": d.get("出口生"), "出口本体": d.get("出口本体"),
        "帯": d.get("帯", ""), "構成": d.get("構成", ""),
        "構成差": d.get("構成差", ""), "型番弱": d.get("型番弱", ""),
        "出口状態": d.get("出口状態", ""),
        "玉": "", "url": "",
        # **いま買い線の内側におる玉があれば、検索やのうてその出品へ直接飛ばす。**
        "いま買える": [float(len(_hits(m, f * LIVE_MIN_RATIO)))
                       for m, f in zip(d["機種"], d["入口p25"])],
        # **件数だけでは動けん。** いくらで出とるかまで見せる
        "いま最安": [(_hits(m, f * LIVE_MIN_RATIO)[0]["price"]
                    if _hits(m, f * LIVE_MIN_RATIO) else float("nan"))
                   for m, f in zip(d["機種"], d["入口p25"])],
        "買いに行く": [
            (_hits(m, f * LIVE_MIN_RATIO)[0]["url"]
             if _hits(m, f * LIVE_MIN_RATIO) else
             (YAHOO_SEARCH.format(q=_q(v)) if v else ""))
            for m, v, f in zip(d["機種"], jp, d["入口p25"])],
        # **その玉が「マスクに救われて生き残った」なら名指しする。**
        # 免責マスクを緩めた変更は「落とすようになった0本」が保証された挙動で、
        # 失敗方向(真の欠陥を通す)は測れてへん(2026-08-24)。測れんなら、
        # せめて**測れてへん玉を人に渡す**。空欄なら生存はマスクと無関係や
        "マスク救済": [
            "|".join(sorted({x.get("マスク救済", "") for x in
                             _hits(m, f * LIVE_MIN_RATIO)} - {""}))
            for m, f in zip(d["機種"], d["入口p25"])],
        # **輸出行にも検品を出す。** 買える玉は fleet_watch が本文を読んどるのに
        # 列が空で、「検品してへん」の旗が誤発火しとった(2026-08-24)。
        # 玉が無い行は空欄のまま——そっちは検査対象やない
        "検品": [
            "|".join(sorted({x.get("verdict", "") for x in
                             _hits(m, f * LIVE_MIN_RATIO)} - {""}))
            for m, f in zip(d["機種"], d["入口p25"])],
        "棚年数": d["機種"].map(lambda m: _shelf_years().get(str(m))),
        # 🚨 **粗利/台では「捌ける玉」と「動かん棚」の区別が付かん。**
        # 2026-08-24 の実測: 純利¥20,000以上の62行 机上¥7,927,934 のうち
        #   棚2年以下=捌ける  33機種 ¥2,670,017
        #   棚5年以上=動かん  12機種 ¥2,734,678   ← ほぼ同額
        # 粗利の降順で並べとる限り、この2つは隣り合って並ぶ。
        #
        # **金は寝とる間は働かん。** 棚年数=今の在庫が捌けるまでの年数で、
        # 出品したら自分もその列の後ろに並ぶ。1台あたりの年利はこうなる:
        #
        #     年利/台 = 粗利/台 ÷ 棚年数
        #
        #   HIOKI IM3536  ¥297,845 ÷ 19.9年 = **¥14,967/年**
        #   SONY PXW-Z190 ¥122,946 ÷  1.2年 = **¥102,455/年**
        # 粗利では IM3536 が2.4倍やが、年利では Z190 が6.8倍や。
        #
        # 棚が薄いと分母が小さすぎて跳ねるので**下限を3ヶ月**で切る。
        # 仕入れて出品して着金するまで、どんなに速うても四半期はかかる。
        "年利/台": [
            (float(n) / max(float(sh), 0.25))
            # **棚0.0年=ACTIVE 0本=競合なし**や。`> 0` で弾いたら NaN になって
            # 最下位に落ちとった(2026-08-24、YAMAHA CP88)。競合ゼロは最高の
            # 面やのに、欠損と同じ扱いにしとった。下限0.25年が受け止める
            if (pd.notna(n) and sh is not None and float(sh) >= 0)
            else float("nan")
            for n, sh in zip(d["粗利/台"],
                             [_shelf_years().get(str(m)) for m in d["機種"]])],
        "売りに行く": us.map(lambda v: EBAY_SOLD.format(q=_q(v)) if v else ""),
        "根拠": "purity.csv(トリム+構成分割済み。Terapeak 3年実売 × aucfree 12ヶ月)",
    })
    return out


def _shelf_years() -> dict[str, float]:
    """機種 -> 棚年数。`souba-league/data/sell_through.csv`。

    **値段の差だけ見とったら、買い手が年に何人おるかが抜ける。**
    棚年数 = 今 eBay に出とる本数 ÷ (直近3年の実売台数 ÷ 3)。
    「今の在庫が捌けるのに何年かかるか」や。2026-08-24 の実測:

        PANA HC-X2000  0.4年 / SONY PXW-Z190 1.2年   ← 捌ける面
        HIOKI PW3360  18.3年 / HIOKI LR8450 50.4年   ← 棚が動かん

    同じ「純利+¥7万」でも中身が別物になる。**割合(sold率)にはせん**——
    3年の流量と一時点の在庫を混ぜた数字は意味を持たんからや。
    """
    p = S.SOUBA / "data" / "sell_through.csv"
    if not p.exists():
        return {}
    d = S.read_csv(p)
    if d.empty:
        return {}
    _num(d, "棚年数")
    return {str(r["機種"]): r["棚年数"] for _, r in d.iterrows()
            if pd.notna(r["棚年数"])}


def verified() -> dict[str, dict]:
    """人が出口のタイトルを読んで下した判定。`data/exit_verified.csv`。

    **汚染率は入力の汚さで、出力の汚さやない。** purity は中央値の1/5未満を
    落とした後の数字を出しとるので、汚染率が高い=結果が汚い、とは限らん。
    2026-08-23 に上位4機種の出口タイトルを全部読んだら:

    | 機種 | 汚染率 | 出口IQR | 実際 |
    |---|---|---|---|
    | ICOM IC-7610 | 17.5% | 0.21 | 66件全部が実機単体。安値はDOA明記 |
    | TECHNICS SL-1200G | 20.3% | 0.21 | 38件全部が単体 |
    | ICOM IC-9700 | 25.4% | 0.18 | 105件、セット混入1件だけ |
    | MAMIYA 7II | 18.6% | **0.46** | **レンズキットが中央値を吊り上げ→却下のまま** |

    汚染率では3清潔と1汚染を区別できんかった。出口IQR は区別しとるが、
    78機種の中央値が 0.43 で MAMIYA が 0.46 やから、**4例から閾値を決めたら
    過剰適合**になる。せやから機械の閾値をいじらず、**読んだ事実を記録して
    その機種だけ汚染の旗を外す**。読んでない機種は今までどおり落ちる。
    """
    p = S.DATA / "exit_verified.csv"
    if not p.exists():
        return {}
    d = S.read_csv(p)
    if d.empty or "機種" not in d:
        return {}
    return {str(r["機種"]): {"判定": str(r.get("判定") or ""),
                            "確認日": str(r.get("確認日") or "")}
            for _, r in d.iterrows()}


def _live_buys() -> dict[str, list[dict]]:
    """機種 -> **いま買い線の内側におるヤフオク**の一覧。

    `fleet_watch` が1時間おきに見て `data/fleet/buy_targets.csv` に書いとる。
    盤は今まで**検索ページに飛ばすだけ**で、「いま玉があるか」を答えてへんかった。
    `under_max` が True の行だけ拾って、安い順で出す。

    同じ auction_id が何度も記録されとるので**最後に見た行だけ**採る。
    """
    p = S.SOUBA / "data" / "fleet" / "buy_targets.csv"
    if not p.exists():
        return {}
    d = S.read_csv(p)
    if d.empty or "under_max" not in d:
        return {}
    d = d[d["under_max"].astype(str) == "True"]
    if d.empty:
        return {}
    d = d.sort_values("checked_at").drop_duplicates("auction_id", keep="last")
    # 🚨 **買い線の内側=買える、やない。** fleet_watch は本文も読んどって、
    # 2026-08-24 の実測では under_max の14件中**6件が kill**やった
    #   TASCAM DA-3000 ¥34,000  [動作未確認]
    #   SONY PXW-Z190 ¥161,013  [ジャンク|動作未確認]
    #   YOKOGAWA WT1800 ¥474,100 [ジャンク]
    # 撃墜された玉に飛ばしたら、盤が嘘をついたことになる。
    if "本文判定" in d:
        # 🚨 **`!= "kill"` やと未検品(空)と取得不能(unknown)が生存として通る。**
        # 走査器の fleet_watch は `== "keep"` で閉じとるのに、盤だけ開いとった
        # (2026-08-24)。`judge()` は本文が取れんかったら "unknown" を返す——
        # 「欠陥が無い」やのうて「見てへん」や。同じ列を逆向きに読んどった
        d = d[d["本文判定"].fillna("").astype(str) == "keep"]
    if d.empty:
        return {}
    _num(d, "cur_price", "max_bid")
    out: dict[str, list[dict]] = {}
    for _, r in d.iterrows():
        out.setdefault(_norm_model(r.get("target")), []).append({
            "url": str(r.get("url") or ""),
            "price": r.get("cur_price"),
            "title": str(r.get("title") or ""),
            "verdict": str(r.get("本文判定") or ""),
            # `str(NaN)` は "nan" いう**文字列**になる。欠損が値に化ける
            # 形がここにも出た(2026-08-24)。空文字に潰す
            "マスク救済": ("" if pd.isna(r.get("マスク救済"))
                        else str(r.get("マスク救済") or "")),
        })
    for v in out.values():
        v.sort(key=lambda x: (x["price"] if pd.notna(x["price"]) else 1e18))
    return out


def _norm_model(v) -> str:
    """機種名の突き合わせ用。メーカー名や区切りの揺れを落とす。"""
    return re.sub(r"[\s\-_]", "", str(v or "")).upper()


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


def _grades_by_family() -> dict[str, dict]:
    """family -> 等級と期待粗利180日。**人手で実物を読んで通った実績**の側や。

    レーンの粗利は「相場どうしの引き算」やが、こっちは「本文検品を通った件数 ×
    その粗利の中央値」。**硬さが別物やから、同じ行に並べて温度差を見せる。**
    """
    p = S.DATA / "snapshot" / "master.csv"
    if not p.exists():
        return {}
    d = S.read_csv(p)
    if d.empty or "family" not in d:
        return {}
    out = {}
    for _, r in d.iterrows():
        out[str(r["family"])] = {
            "等級": str(r.get("等級") or ""),
            "期待粗利180d": pd.to_numeric(r.get("期待粗利180d"), errors="coerce"),
            "判定": str(r.get("判定") or ""),
        }
    return out


def _domestic_from_souba() -> pd.DataFrame:
    """国内レーン。**1行=いま出とる現物1個**や。売切と kill は落とす。"""
    fam_q = _family_queries()
    grade = _grades_by_family()
    # **売る側は「一覧に飛ばす」では決められん。** いくらで出すかを決めるのに
    # 要るのは分布や。medians.csv が件数・p10・p25・中央を持っとる
    mp = S.SOUBA / "data" / "flip" / "medians.csv"
    md = S.read_csv(mp) if mp.exists() else pd.DataFrame()
    if not md.empty:
        _num(md, "n", "median", "p25")
        dist = {str(r["family"]): (r["n"], r["p25"]) for _, r in md.iterrows()}
    else:
        dist = {}
    # 検品の見せ方は buylist.py の正本を借りる。**keep は「買ってええ」やない**——
    # 「本文に欠陥の自白が無い」だけで、LLM検品の生存判定は実測25%や
    from . import buylist as BL
    rows = []
    for fname, market in FLIP_MARKET.items():
        p = S.SOUBA / "data" / "flip" / fname
        if not p.exists():
            continue
        d = S.read_csv(p)
        if d.empty:
            continue
        _num(d, "price", "median", "net", "buy_line")
        if "status" in d:
            d = d[d["status"].fillna("") != "SOLD"]
        if "verdict" in d:
            # 上と同じ。未検品を生存扱いにせん(flea_xtab には unknown が実在する)
            d = d[d["verdict"].fillna("") == "keep"]
        d = d[d["net"].notna()]
        if d.empty:
            continue
        rows.append(pd.DataFrame({
            "品": _col(d, "title").str.slice(0, 46),
            "レーン": f"{market} → ヤフオク", "種別": "国内(現物)",
            "仕入面": market, "仕入値": d["price"],
            "売面": "ヤフオク(再出品)", "売値": d["median"],
            "引かれ": d["median"] - d["price"] - d["net"],
            "純利": d["net"], "年台数": float("nan"),
            # 出口を Yahoo!フリマ(5%)にしたら手数料が半分になる。**値段が同じなら**
            # この額だけ純利が増える。medians の exit_net はヤフオク10%が前提や
            "フリマなら": d["median"] * (JP_EXIT_FEE[JP_EXIT_BASE]
                                    - JP_EXIT_FEE["Yahoo!フリマ"]),
            "買い線": d.get("buy_line"),
            "玉": _col(d, "family"), "url": _col(d, "url"),
            "走査": _col(d, "scanned_at"),
            # medians.csv の n は**過去180日**の落札数(backtest_flip.py)。
            # 年換算は n×2、平均間隔は 182.5/n 日
            "売れる間隔": _col(d, "family").map(
                lambda f: (182.5 / dist[str(f)][0])
                if dist.get(str(f)) and dist[str(f)][0] else float("nan")),
            "相場n": _col(d, "family").map(
                lambda f: dist.get(str(f), (float("nan"), float("nan")))[0]),
            "相場p25": _col(d, "family").map(
                lambda f: dist.get(str(f), (float("nan"), float("nan")))[1]),
            "検品": _col(d, "verdict").map(
                lambda v: BL.VERDICT_LABEL.get(str(v), str(v))),
            # 🚨 **中古を仕入れて新品の中央値で売る計算になっとった**(2026-08-25)。
            # 走査器が玉ごとに状態を判定して、**同じ状態の落札中央値だけ**で
            # 売値を出すようにした。ここはその結果を持ち回るだけや。
            # 走査が古い行はこの2列が空で、下の旗が拾う
            "状態": _col(d, "状態"),
            "出口基準": _col(d, "出口基準"),
            "等級": _col(d, "family").map(
                lambda f: grade.get(str(f), {}).get("等級", "")),
            "期待粗利180d": _col(d, "family").map(
                lambda f: grade.get(str(f), {}).get("期待粗利180d")),
            "買いに行く": _col(d, "url"),
            "売りに行く": _col(d, "family").map(
                lambda f: AUCFREE.format(q=_q(fam_q.get(f, ""))) if fam_q.get(f) else ""),
            "根拠": fname,
        }))
    if not rows:
        return pd.DataFrame()
    # 全NAの列(等級/期待粗利180d は camera/gakki にしか付かん)を放って concat すると
    # dtype が決まらず pandas が将来の挙動変更を警告する。先に型を決める
    for g in rows:
        if "期待粗利180d" in g:
            g["期待粗利180d"] = pd.to_numeric(g["期待粗利180d"],
                                            errors="coerce").astype("float64")
        for c in ("等級", "検品"):
            if c in g:
                g[c] = g[c].fillna("").astype(str)
    return pd.concat(rows, ignore_index=True)


def _reverb_from_souba() -> pd.DataFrame:
    """Reverb レーン。**ask は一切使わん。** live→sold に化けた玉の中央値だけ。

    2026-08-24 に個体追跡で分かったこと: **ask と sold の差は −6〜−31%(中央 −19%)**。
    ask で組んだら「海外が高い」に必ず傾く。せやから `state == "sold"` の行だけ拾う。

    その代わり**標本が薄い**。追跡を始めて7日で13件しか化けとらんので、
    ほとんどの型番が `出口標本N件` の旗で監査キューに落ちる。**それでええ**——
    追跡が続けば件数が増えて、閾値を越えた型番から自動で買い候補に上がる。
    """
    trk = S.SOUBA / "data" / "flip" / "reverb_track.csv"
    prb = S.SOUBA / "data" / "flip" / "reverb.csv"
    med = S.SOUBA / "data" / "flip" / "medians.csv"
    if not (trk.exists() and prb.exists() and med.exists()):
        return pd.DataFrame()
    t, pr, md = S.read_csv(trk), S.read_csv(prb), S.read_csv(med)
    if t.empty or pr.empty or md.empty:
        return pd.DataFrame()
    _num(t, "price_usd", "days_listed")
    _num(pr, "kg")
    _num(md, "median", "p25", "n")
    sold = t[t["state"] == "sold"]
    if sold.empty:
        return pd.DataFrame()
    kg = dict(zip(pr["family"], pr["kg"]))
    q = dict(zip(pr["family"], pr.get("query", pr["family"])))
    jp_mid = dict(zip(md["family"], md["median"]))
    jp_p25 = dict(zip(md["family"], md["p25"]))
    jp_n = dict(zip(md["family"], md["n"]))
    fam_q = _family_queries()

    rows = []
    for fam, g in sold.groupby("family"):
        us = float(g["price_usd"].median()) * JPY
        # **ここだけが本物の「売れるまで」**。live→sold に化けた個体の掲載日数や
        dl = pd.to_numeric(g.get("days_listed"), errors="coerce").dropna()
        stay = float(dl.median()) if len(dl) else float("nan")
        w = float(kg.get(fam) or 3)
        ship = 2000 + w * 3000                      # reverb_probe.py と同じ式
        buy = jp_p25.get(fam)
        if buy is None or pd.isna(buy):
            buy = jp_mid.get(fam)
        if buy is None or pd.isna(buy):
            continue
        net = us * (1 - REVERB_FEE) - ship - float(buy)
        line = us * (1 - REVERB_FEE) - ship - MIN_NET
        jq = fam_q.get(fam, "")
        rows.append({
            "品": str(q.get(fam, fam)), "レーン": "ヤフオク → Reverb US",
            "種別": "輸出(Reverb)",
            "仕入面": "ヤフオク(落札p25)", "仕入値": float(buy),
            "売面": f"Reverb 実売中央({len(g)}件)", "売値": us,
            "引かれ": us - float(buy) - net,
            "純利": net, "買い線": line, "実測滞留": stay,
            "年台数": float("nan"), "年間粗利": float("nan"),
            "出口n": float(len(g)), "入口n": float(jp_n.get(fam) or 0),
            # 🚨 **`or 0` の向きが規則によって逆になる。** 同じ行の
            # 入口n は 0 やと `v < 10` に当たって旗が立つ(閉じる)が、
            # 入口中央は 0 やと flags の `em > 0` で**規則ごと飛ぶ**(開く)。
            # 不明は NaN のまま渡して、旗側で「不明」として拾わせる
            "入口中央": float(jp_mid.get(fam) or float("nan")),
            "玉": fam, "url": "",
            "買いに行く": (YAHOO_SEARCH.format(q=_q(jq)) if jq else ""),
            "売りに行く": f"https://reverb.com/marketplace?query={_q(q.get(fam, fam))}",
            "根拠": "reverb_track.csv(live→soldに化けた玉のみ)× medians.csv",
        })
    return pd.DataFrame(rows)


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
    return combine(_export_from_souba(), _domestic_from_souba(),
                   _reverb_from_souba())


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
    er = ENTRY_P25_RATIO
    ver = verified()
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
    entry_mid, line = num("入口中央"), num("買い線")
    ex_raw, ex_body = num("出口生"), num("出口本体")
    dirty_s, years = num("汚染率"), num("年台数")
    outn, inn = num("出口n"), num("入口n")
    out = []
    for i in d.index:
        w = []
        b, s_ = buy.get(i), sell.get(i)
        if pd.notna(b) and pd.notna(s_) and s_ > 0 and b / s_ < r:
            w.append(f"入口が売値の{b / s_ * 100:.1f}%=左右ズレ疑い")
        # **人が「汚い」と読んだんなら、それは旗や。**
        # clean は旗を外すのに dirty は何もしとらんかった(2026-08-24)。
        # 人手の判定が片側にしか効かんのは、読んだ労力の半分を捨てとる。
        vr0 = ver.get(str(d["品"].get(i) if "品" in d else ""), {})
        if vr0.get("判定") == "dirty":
            w.append(f"人が読んで汚い[{str(vr0.get('確認日') or '')}]")
        v = dirty_s.get(i)
        if pd.notna(v) and v >= dt:
            # 人が出口を読んで clean と判定しとったら、汚染の旗は外す
            vr = ver.get(str(d["品"].get(i) if "品" in d else ""), {})
            if vr.get("判定") == "clean":
                pass
            else:
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
        # 🚨 **打ち切りに当たった生データは中央値が壊れる。**
        # 人気機は付属品の出品が多く、上限が付属品で埋まって本体が外へ押し出される。
        # ICOM IC-9100 は生150(打ち切り)本体8=5%で出口中央¥5,637(実機は¥13万級)。
        # これを「赤字」と出したら「この機種は駄目」いう誤った結論が残る。
        # **0件やのうて未測**と同じ話で、赤字やのうて**測定不能**と言う。
        rw, bd = ex_raw.get(i), ex_body.get(i)
        if (pd.notna(rw) and pd.notna(bd) and rw >= 150 and rw % 50 == 0
                and bd / rw < BODY_RATE):
            w.append(f"打ち切り{int(rw)}件・本体率{bd / rw * 100:.0f}%=測定不能")
        # 🚨 **入口の安値側にゴミが残っとると、粗利が盛られる。**
        # 粗利/台 = 出口中央×0.84 − 送料 − **入口p25** やから、p25 が地面に
        # 引っ張られるほど粗利が大きく見える。買い線は出口だけで決まるので
        # 壊れんが、**順位が壊れる**。2026-08-23、AG-DVX200 の本体11件に
        # ¥16,000(中央¥122,000)が混ざって p25 が¥50,000 に落ち、
        # 粗利が¥104,175=実勢の3倍に見えとった。
        em = entry_mid.get(i)
        if pd.notna(b) and pd.notna(em) and em > 0 and b / em < er:
            w.append(f"入口p25が中央の{b / em * 100:.0f}%=安値側にゴミ")
        elif (pd.notna(b) and not pd.notna(em)
                and not pd.notna(dirty_s.get(i))
                and "p25" in str(d["仕入面"].get(i) if "仕入面" in d else "")):
            # **入口中央が無い行では、この規則は一度も走っとらん。**
            # 空欄を「検査して問題なし」と読ませたらあかん。
            #
            # ただし **purity 由来の行は除く**。あっちは入口p25の桁トリムを
            # 先に通しとるので、安値ゴミの検査は別の形で済んどる(上の
            # 「入口中央は purity に無いので…」のコメントの通り)。
            # 見分けは汚染率の有無や——purity の行だけが汚染率を持つ。
            # **国内(現物)も除く。** あっちの仕入値は実在の1個の値段で、
            # 入口の分布やない。「p25が中央の何%か」は分布の統計にしか
            # 意味が無いので、仕入面が p25 と名乗っとる行だけに当てる。
            # 初版はこれを外しとって**126行中126行に旗が立った**。
            # 旗が全部に立つのは、旗が無いのと同じや(2026-08-24)
            w.append("入口中央が不明=安値ゴミの検査でけてへん")
        # **買い線が安値4分の1より下なら、まず落とせん。**
        # 買い線 = 出口×0.84 − 送料 − 最低利益¥30,000 やから、粗利が3万に
        # 届かん機種はこうなる。数字はプラスでも「買える見込み」が無い。
        ln = line.get(i)
        if pd.notna(ln) and pd.notna(b) and b > 0 and ln < b:
            w.append(f"買い線が落札p25を{(b - ln) / b * 100:.0f}%下回る=まず買えん")
        # 国内(現物)の鮮度。**走査した瞬間しか status は更新されん**ので、
        # 古い行は SOLD にならずに「まだ買える」顔で残る
        sc = d["走査"].get(i) if "走査" in d else None
        if isinstance(sc, str) and sc.strip():
            try:
                age = (pd.Timestamp.now() - pd.Timestamp(sc)).total_seconds() / 3600
                if age > STALE_HOURS:
                    w.append(f"走査から{age / 24:.0f}日=玉は消えとる公算")
            except (ValueError, TypeError):
                pass
        comp = d["構成"].get(i) if "構成" in d else None
        if isinstance(comp, str) and "セット" in comp:
            w.append("構成にセット混在")
        # 🚨 **中古を仕入れて新品の値段で売る計算になっとった**(2026-08-25)。
        # ヤフオク落札17,963行のうち13.0%が新品で、新品と中古が両方2件以上ある
        # 159型番の**145(91%)で新品のほうが高い**。混合の中央値を中古の玉に
        # 当てると出口が中央+1.8%・最悪+39.3%(p_home_k06a ¥25,785→¥42,501)
        # 盛られる。**空欄は「混ぜたまま」や**——走査し直すまで信用したらあかん。
        st_ = str(d["状態"].get(i) or "") if "状態" in d else ""
        bs = str(d["出口基準"].get(i) or "") if "出口基準" in d else ""
        if str(d["種別"].get(i) if "種別" in d else "").startswith("国内"):
            if not bs:
                w.append("出口が新品と中古の混合=走査し直すまで信用でけへん")
            elif st_ and st_ != bs:
                w.append(f"{st_}の玉を{bs}の中央値で評価しとる")
        # purity が既に出しとる2つ。**盤が見てへんかった**(2026-08-22)。
        # DAIWA EXIST が「旗なし首位・年間粗利508万」に居座っとった原因や。
        # 入口p25 ¥9,000 に対し中央 ¥28,273 = 替えスプールや部品が混ざっとる。
        diff = d["構成差"].get(i) if "構成差" in d else None
        if isinstance(diff, str) and diff.strip():
            # 構成差(トリム後もIQRが閾値超え)も、人が出口を読んで
            # 「単体しか無い」と確かめとったら外す。汚染と同じ扱いや——
            # どっちも「出口の母集団が一種類か」を別の角度で見とるだけ
            if ver.get(str(d["品"].get(i) if "品" in d else ""), {}).get("判定") != "clean":
                w.append(f"構成差[{diff.strip()}]")
        # **買える顔で出しとる行に検品が無いのは、旗を立てなあかん。**
        # 「検品が空欄」は「欠陥が無い」やのうて「本文を読んでへん」や
        insp = d["検品"].get(i) if "検品" in d else None
        buyable = d["いま買える"].get(i) if "いま買える" in d else None
        # **「空欄」には2つの顔がある。** 輸出行は文字どおり空文字やが、
        # 国内行は `VERDICT_LABEL[""]` を通って「⚪ 未検品」いう**文字**になる。
        # 空白だけ見とったら国内側の未検品が旗をすり抜けた(2026-08-25)
        from . import buylist as _BL
        blank = isinstance(insp, str) and (not insp.strip()
                                           or insp.strip() == _BL.VERDICT_LABEL[""])
        if (blank and pd.notna(pd.to_numeric(buyable, errors="coerce"))
                and float(pd.to_numeric(buyable, errors="coerce")) > 0):
            w.append("検品してへん")
        # 🚨 **国内(現物)は1行=目の前の1個や。無条件で検査対象になる。**
        # 前は候補CSVの `verdict == "keep"` で先に絞れとったので旗が要らんかった。
        # 走査し直した直後は**その列がまだ存在せん**ので絞りが素通りして、
        # 未検品の玉が「旗なし」に並んだ(2026-08-25に踏んだ)。
        # 絞りが効いとるかどうかに旗を依存させたらあかん——**空欄は空欄で数える**
        elif blank and str(d["種別"].get(i) if "種別" in d else "").startswith("国内"):
            w.append("検品してへん")
        # **マスクに救われた玉は監査キューへ。** 生存が「欠陥語が無い」やのうて
        # 「消した」やった玉や。コーパス78本では19%(15本)がこれに当たる
        # **棚が動かん面は、粗利が出とっても金が返ってこん。**
        # HIOKI PW3360 は eBay に67本並んどって年3.7台しか売れとらん=18年分。
        # 「年台数」は出口の流量だけを見とって、**競合の在庫**を見てへんかった
        # **実測滞留は個体の実数やから信用してええ。** Reverb の published_at と
        # sold の差で、追跡の窓の長さに依らん。長いのは長いままの事実や。
        # 2026-08-24: Martin 000-28 は**実売1件が売れるのに1,417日**かかっとった。
        # 純利¥311,023 は「4年待って1本」の値段や。
        # (対して**棚年数を Reverb で出すのは今はでけへん**——追跡の窓が7日しか
        #  無いので、1件の実売を年率に直すと52件/年になってまう)
        stay = num("実測滞留").get(i)
        if pd.notna(stay) and stay > 180:
            w.append(f"実売が売れるのに{stay:.0f}日=資金が{stay / 365:.1f}年寝る")
        sh = num("棚年数").get(i)
        if pd.notna(sh) and sh >= 5:
            w.append(f"棚{sh:.0f}年分=在庫が動かん")
        resc = d["マスク救済"].get(i) if "マスク救済" in d else None
        if isinstance(resc, str) and resc.strip():
            w.append(f"マスクで生存[{resc.strip()}]=人が本文を読む")
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
