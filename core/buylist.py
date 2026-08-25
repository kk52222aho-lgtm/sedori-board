# -*- coding: utf-8 -*-
"""**いま買える玉**の一覧。souba-league が吐いた候補を、盤で読める形に整える。

## なんでフリマなんか
2026-08-15、仕入れ3面を391型番・同じ門で比べた:

| 面 | 買い線割れ | 機械検品 | 人手 | 代理入札の減衰 |
|---|---|---|---|---|
| **Yahoo!フリマ** | **98件** | 61% | **62%** | **無し** |
| メルカリ | 22件 | — | — | 無し |
| ヤフオク | 937件 | 15% | 30% | **25%** |

ヤフオクは競りやから **良い玉は中央値まで競り上がって買い線に届かん**。
実測で「宣言した上限で勝てた」のは決済8件中2件=**25%**やった。
フリマは固定価格やから**出とる値で今すぐ買える**。宣言と実行の差がゼロや。

## 逆選択の向きが逆
| 面 | 何が安く残るか |
|---|---|
| ヤフオク | 競りやから**壊れた玉だけ**が安く残る |
| **フリマ** | 出品者が値付けするから**相場を知らん人が普通の玉を安く出す** |

人手で60件読んだら、上位は「新しいモデルに買い替えたため出品」「動作に問題ありません」
という職人の出品やった(MAX 高圧エア釘打機 中央¥62,900に対して¥22,800〜25,000)。

## 速い者勝ち
候補98件を数時間後に追跡したら **61%が既にSOLD**やった。
しかも**純利2万超は10件中10件が売れとった**——市場も「安い」と認めとる。
**1日1回の走査やと6割は見つけた時点で消えとる。**
"""
from __future__ import annotations

import pandas as pd

from . import sources as S

# 買い目に出すときの列と表示名
COLS = {
    "市場": "市場",
    "family": "型番",
    "title": "商品",
    "price": "いま",
    "median": "相場",
    "net": "純利",
    # 🚨 **`condition` は面の生の申告(new/used10…)で、`状態` は判定結果や。**
    # 前は condition を「状態」いう名前で出しとったが、それとは別に
    # 「その玉の売値をどっちの中央値で出したか」が要る(2026-08-25)
    "condition": "申告",
    "状態": "状態",
    "出口基準": "出口基準",
    "verdict": "検品",
    "status": "売切",
    "url": "リンク",
}
# 検品の判定をそのまま出す。**keep=買ってええ、やない**——
# keep は「本文に欠陥の自白が無い」だけや。人手で読むまで買わん
VERDICT_LABEL = {
    "keep": "🟢 自白なし",
    "kill": "🔴 欠陥の自白あり",
    "unknown": "⚪ 本文が取れん",
    "": "⚪ 未検品",
}


def load() -> pd.DataFrame:
    """買い目。無ければ空を返す。"""
    df = S.snap("buylist")
    if df is None or df.empty:
        return pd.DataFrame()
    for c in ("price", "median", "net"):
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df["判定"] = df.get("verdict", "").fillna("").map(
        lambda v: VERDICT_LABEL.get(str(v), str(v)))
    # 売り切れた玉は下に沈める(記録としては残す——**61%が数時間で消える**
    # という事実そのものが、走査頻度を決める材料やから)
    df["_sold"] = (df.get("status", "") == "SOLD").astype(int)
    return df.sort_values(["_sold", "net"], ascending=[True, False])


def live(df: pd.DataFrame) -> pd.DataFrame:
    """まだ買える玉だけ。"""
    if df.empty:
        return df
    return df[df["_sold"] == 0]
