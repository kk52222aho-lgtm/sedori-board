# -*- coding: utf-8 -*-
"""**軍資金いくらで、今日なにを買うか。** ¥10万 / 30万 / 50万 / 100万の実弾版。

## なんで別の盤が要るか
レーン比較は「1台あたりナンボ儲かるか」を出す。せやけど実弾は**手持ちの金**で
切られる。¥10万の財布で¥70万のアキュフェーズは買えんし、逆に¥100万を1本に
全部入れたら、次の玉が落ちてきても撃てん。**1台の利幅と、資金の効率は別の軸や。**

## 資金は「スロット」で数える
1スロット = 1台分の資金。輸出は**買い線**(これ以下で買えたら勝ち)、
国内(現物)は**いま出とる値段**そのもの。

    スロットあたりの年利 = 純利 ÷ 保有年数      ← レーン盤の「年利/台」
    **年利回り**        = 年利/台 ÷ 1台の資金   ← **資金を並べ替えるのはこっち**

保有年数は棚年数(いまeBayに出とる在庫が捌けるまでの年数)を使う。
**下限は0.25年**——仕入れて出品して着金するまで、どんなに速うても四半期はかかる。

## 🚨 スロットは積み放題やない
同じ型番に金を積んでも、**買い線の内側へ落ちてくる玉の本数**で頭打ちになる。

    使えるスロット数 = ceil(買線内 × 保有年数)

SONY PXW-X70 は年20本が買い線の内側に落ちて保有0.25年やから 20×0.25 = **5スロット**。
6本目の資金は玉が来んから寝るだけや。**「金がある」は「撃てる」やない。**

## 1型番に寄せん(総取りせん)
割り当ては**総当たりやのうて1周ずつ**や。年利回りの高い順に1スロットずつ配って、
金が余ったら2周目に入る。理由は `audit_gate.py` と同じ——**推定利益の降順は
上ほど誤りが濃い**ので、一番おいしそうに見える1本に全部入れる操作は、そのまま
一番誤りの濃い玉に全部入れる操作になる。

## 🚨 この盤の数字は全部まだ机上や
    実弾の確定純利      **¥0**(`data/holdings.csv` が空。まだ1本も持っとらん)
    本文検品を通る割合  **14.9%**(検品n≥4の26型番・248件の実測)
    紙上で勝った6件を検品したら **0/6**(逆選択。安く落ちるのは壊れとるから)

せやから金額の下に**段を上げる条件**を並べる。¥10万→30万→50万→100万は
4つの選択肢やのうて**梯子**や。確定純利が出るまで次の段に行かん。
"""
from __future__ import annotations

import math

import pandas as pd

# 実弾の段。**選択肢やのうて梯子**や(下から順に上がる)
TIERS = (100_000, 300_000, 500_000, 1_000_000)

# 仕入れて出品して着金するまでの最短。棚年数がこれを下回っても、
# 資金がこれより速う戻ってくることは無い
MIN_HOLD_YEARS = 0.25

# 本文検品を通る割合。**26型番248件の実測**(2026-08-26時点の master から)。
# 机上の年利にこれを掛けたのが「検品後の見込み」や。
# 🚨 これでも**まだ楽観**やという証拠がある——紙上で勝った6件を検品したら
# 0/6 やった。keep は「本文に欠陥の自白が無い」だけで、買ってええ、やない
KEEP_RATE = 0.149

# 1台の資金がこれ未満の行は出さん。送料・梱包・手間で消える帯や
MIN_SLOT = 5_000


def _hold_years(r) -> float:
    """その玉の資金が寝る年数。**棚年数が本命、無ければ売れる間隔。**

    棚年数 = いまeBayに並んどる在庫 ÷ 直近3年の実売台数。出品したら自分も
    その列の後ろに並ぶんやから、これが資金の拘束期間になる。
    国内(現物)は棚年数が無いので `売れる間隔`(日)から作る。
    """
    v = pd.to_numeric(pd.Series([r.get("棚年数")]), errors="coerce").iloc[0]
    if pd.isna(v):
        d = pd.to_numeric(pd.Series([r.get("売れる間隔")]), errors="coerce").iloc[0]
        v = (d / 365.0) if pd.notna(d) else float("nan")
    if pd.isna(v):
        return MIN_HOLD_YEARS
    return max(float(v), MIN_HOLD_YEARS)


def _num(r, key) -> float:
    v = pd.to_numeric(pd.Series([r.get(key)]), errors="coerce").iloc[0]
    return float(v) if pd.notna(v) else float("nan")


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    """レーンの行を**資金の単位**に組み直す。1行=1型番のスロット定義。

    入れるのは `lanes.profitable(lanes.clean(...))` を通った行だけ——
    **旗が立っとる行は監査キューや。実弾の割り当てに混ぜたらあかん。**
    """
    if df is None or df.empty:
        return pd.DataFrame()
    out = []
    for _, r in df.iterrows():
        kind = str(r.get("種別") or "")
        net = _num(r, "純利")
        if pd.isna(net) or net <= 0:
            continue
        hold = _hold_years(r)
        live_n = _num(r, "いま買える")
        low = _num(r, "いま最安")
        if kind.startswith("国内"):
            # **1行=目の前の1個。** 出とる値段で買う。おかわりは無い
            cost, slots, today = _num(r, "仕入値"), 1, True
        else:
            # 輸出は「買い線までなら出す」いう予約や。**資金は買い線で押さえる**
            # ——実際は入口p25で買える見込みやが、上限まで出す覚悟の金が要る
            cost = _num(r, "買い線")
            within = _num(r, "買線内")
            if pd.isna(within) or within <= 0:
                continue          # 年に1本も買い線の内側へ落ちん = 撃てん
            slots = max(1, int(math.ceil(within * hold)))
            today = pd.notna(live_n) and live_n > 0
            if today and pd.notna(low) and low > 0:
                # **いま実在する玉があるなら、その値段が本当の資金や。**
                # 利幅は値段に対して傾き−1で動く(どっちも同じ出口から引いとる)
                net = net + (_num(r, "仕入値") - low)
                cost = low
                slots = min(slots, int(live_n))
        if pd.isna(cost) or cost < MIN_SLOT or net <= 0:
            continue
        # 🚨 **利幅は「いくらで買えたか」で決まる。上限まで出したら最低保証まで縮む。**
        # 純利は入口p25(過去に実際に落ちた安いほう4分の1)で買えた場合の値やが、
        # 押さえとかなあかん資金は**買い線**(上限まで出す覚悟の金)や。
        # その2つを混ぜたまま1つの数字で出したら、幅が見えんようになる。
        #   純利は値段に対して傾き−1 → 買い線で買った場合 = 純利 + 仕入値 − 買い線
        #   ICOM IC-7610: 95,386 + 201,214 − 266,600 = **¥30,000**(目標利益そのもの)
        line = _num(r, "買い線")
        entry = _num(r, "仕入値")
        floor_net = (net + entry - line) if (pd.notna(line) and pd.notna(entry)
                                             and not today) else net
        # 年に何回この型番を撃てるか。玉の供給(買線内)と、スロットの回転
        # (1/保有年数)の**小さい方**で決まる。国内の現物は1回きり
        supply = 1.0 if kind.startswith("国内") else _num(r, "買線内")
        # 🚨 **国内(現物)は1行1個やが、同じ型番の玉は出口を食い合う**(2026-09-01)。
        # ¥100万の案が23本中**13本が同じ WH36DD** になっとった。1行ずつ独立に
        # 足しとったからで、13台まとめて捌けるかは一切見てへん。
        # 輸出は1機種1スロットずつ配って分散しとるのに、国内だけ素通しやった。
        # **群(型番)で束ねて、輸出と同じ扱いにする。**
        grp = str(r.get("玉") or r.get("品") or "")
        # その型番が保有期間のあいだに市場が吸える台数。相場n は**過去180日**の
        # 落札数やから年は ×2。これを超えて積んでも捌けん
        n180 = _num(r, "相場n")
        absorb = (n180 * 2 * hold) if pd.notna(n180) and n180 > 0 else float("nan")
        out.append({
            "品": r.get("品", ""), "種別": kind, "群": grp,
            "群の上限": (max(1, int(math.floor(absorb))) if pd.notna(absorb)
                       else (slots if not kind.startswith("国内") else 1)),
            "1台の資金": cost, "純利": net, "上限で買ったら": floor_net,
            "保有年数": hold, "年利/台": net / hold,
            "年利回り": net / hold / cost,
            "スロット上限": slots, "年の供給": supply,
            # 🚨 **予約した金は、玉が落ちてくるまで1円も働かん。**
            # 買い線を張るいうのは「年に何本か落ちてくるのを待つ」ことで、
            # 買線内=5 の型番は次の玉まで中央73日かかる。**待ち日数を出さんと
            # 「¥50万を割り当てた」が「¥50万が働いとる」に見えてまう**
            "次の玉まで日": (0.0 if today
                          else (365.0 / supply if supply and supply > 0
                                else float("nan"))),
            "今日買える": today,
            "買いに行く": r.get("買いに行く", ""),
            "売りに行く": r.get("売りに行く", ""),
        })
    if not out:
        return pd.DataFrame()
    return pd.DataFrame(out).sort_values("年利回り", ascending=False,
                                         ignore_index=True)


def plan(df: pd.DataFrame, budget: float) -> pd.DataFrame:
    """軍資金 `budget` の割り当て。**年利回りの高い順に1スロットずつ配る。**

    総取りにせん理由は上の docstring のとおり——降順の1位に全部入れる操作は、
    誤りの一番濃い玉に全部入れる操作と同じや。
    """
    src = prepare(df)
    if src.empty:
        return pd.DataFrame()
    taken = [0] * len(src)
    # **群ごとの取得数**。同じ型番の玉は、輸出の1機種と同じ天井で止める
    by_grp: dict = {}
    left = float(budget)
    moved = True
    while moved:
        moved = False
        # 🚨 **1周で同じ型番は1台まで。** 国内(現物)は1行1個やから、
        # 行で回すと同じ型番が13本並ぶ(2026-09-01、¥100万の23本中13本が WH36DD)。
        # 輸出は1機種1スロットずつ配って分散しとるのに、国内だけ素通しやった。
        # **出口を何台食えるかは一度も測っとらん**(実弾の売却実績が¥0や)ので、
        # 勝手な取り分を決めるより「他を全部1台ずつ配ってから2台目」が正直や。
        seen_grp: set = set()
        for i, r in src.iterrows():
            if taken[i] >= r["スロット上限"]:
                continue
            g = r["群"]
            if g in seen_grp:
                continue          # この周では、その型番はもう配った
            if by_grp.get(g, 0) >= r["群の上限"]:
                continue          # 保有期間に市場が吸える台数を超えとる
            if r["1台の資金"] > left:
                continue
            taken[i] += 1
            by_grp[g] = by_grp.get(g, 0) + 1
            seen_grp.add(g)
            left -= r["1台の資金"]
            moved = True
    rows = []
    for i, r in src.iterrows():
        k = taken[i]
        if not k:
            continue
        # k スロットで年に何回撃てるか。**供給と回転の小さい方**や
        shots = min(r["年の供給"], k / r["保有年数"])
        rows.append({
            "品": r["品"], "種別": r["種別"], "台数": k,
            "1台の資金": r["1台の資金"], "使う金": r["1台の資金"] * k,
            "1台の純利": r["純利"], "上限で買ったら": r["上限で買ったら"],
            "保有年数": r["保有年数"],
            "年に撃てる": shots, "机上の年利": r["純利"] * shots,
            "年利回り": r["年利回り"], "今日買える": r["今日買える"],
            "次の玉まで日": r["次の玉まで日"],
            "買いに行く": r["買いに行く"], "売りに行く": r["売りに行く"],
        })
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values("机上の年利", ascending=False,
                                          ignore_index=True)


def summary(p: pd.DataFrame, budget: float) -> dict:
    """段ごとの数字。**「使えん金」を必ず出す**——そこがこの盤の主役や。"""
    if p is None or p.empty:
        return {"使う金": 0.0, "遊ぶ金": float(budget), "今日出す金": 0.0,
                "予約の金": 0.0, "初弾まで日": float("nan"),
                "机上の年利": 0.0, "上限で買った年利": 0.0, "検品後": 0.0,
                "年利回り": float("nan"), "本数": 0, "型番数": 0}
    use = float(p["使う金"].sum())
    gross = float(p["机上の年利"].sum())
    # **上限まで出して買った場合の年利。** 下側の端や——ここと机上の間のどこかに
    # 落ちる、という読み方をする。片方だけ出したら幅が消える
    floor = float((p["上限で買ったら"] * p["年に撃てる"]).sum())
    today = float(p.loc[p["今日買える"], "使う金"].sum())
    # **最初の1本が落ちてくるまでの日数。** 予約を何本も張っとるなら、
    # そのどれかが最初に落ちる——一番待ちの短いやつが初弾になる
    wait = pd.to_numeric(p["次の玉まで日"], errors="coerce").dropna()
    return {
        "使う金": use, "遊ぶ金": float(budget) - use, "今日出す金": today,
        "予約の金": use - today,
        "初弾まで日": float(wait.min()) if len(wait) else float("nan"),
        "机上の年利": gross, "上限で買った年利": floor,
        "検品後": gross * KEEP_RATE,
        "年利回り": (gross / use) if use else float("nan"),
        "本数": int(p["台数"].sum()), "型番数": int(len(p)),
    }


# **段を上げる条件。** 金額やのうて「なにが確かめられたか」で上がる。
# 実弾の実績がゼロのうちに段を飛ばすのが、この商売で一番でかい負け方や。
LADDER = [
    (100_000, "手を動かして、出口まで1本通す",
     "**1本だけ買う。売って、着金するまで2本目に行かん。** いまの盤は"
     "実弾の確定純利が¥0や。測っとらんのは「勝てる」やのうて「知らん」で、"
     "検品を通る割合14.9%も**買う前の話**でしかない。"
     "1本通せば、送料・梱包・出品の手間・実際に何日で売れたか、が数字になる。"),
    (300_000, "確定純利が1本出て、机上との比が分かった",
     "**2〜3本を並行に持つ段。** 1本目で「机上¥Xに対して実際は¥Y」が出とる。"
     "その比が0.5を割るなら、金を増やす前に**買い線の引き方**を直す番や。"),
    (500_000, "同じ型番で2回以上勝った",
     "**型番を絞って厚く張る段。** 1回勝つのは運でも起きる。2回目が出て初めて"
     "「その型番の出口が読めとる」と言える。ここから棚年数の短い面へ寄せる。"),
    (1_000_000, "回収率が3本連続で机上の6割を超えた",
     "**スロットを並べて回す段。** ここまで来たら制約は金やのうて"
     "**玉の供給**(買線内)と**自分の手数**や。年に撃てる回数の頭打ちを"
     "先に確かめてから入れること。"),
]


def realized(board_data) -> tuple[float, int]:
    """実弾の確定分。`data/holdings.csv` は個人の財務やからクラウドには無い。

    返すのは (確定純利, 本数)。**空なら ¥0 / 0本**——それが今の事実や。
    """
    if board_data is None or board_data.empty:
        return 0.0, 0
    n = pd.to_numeric(board_data.get("純利"), errors="coerce")
    return float(n.fillna(0).sum()), int(len(board_data))
