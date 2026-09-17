# -*- coding: utf-8 -*-
"""**付属品・部品が本体の買取と比べられとる玉**に旗を立てる。採点はせん。

## なんで盤側に要るか
台帳([sedori-board] 2026-08-07)にこう書いた——
**「誤マッチは本文検品では絶対に取れん。型番定義(match_re/PARTS_RE)側で
潰すしかない」**。それは今も正しい。ここは潰す層やない。**旗を立てるだけ**や。

工場の部品語は `is_body.JP_PARTS_CAMERA` = **カメラ用**や。盤が
`p_tools_*` / `p_audio_*` / `p_pc_*` に広がったとき、その帯の付属品語
(充電器・ケース・ロジックボード)を誰も持っとらんかった。実測(2026-09-17の
買い目95行)で、**純利の上位2行が2行とも付属品**やった:

    ¥17,422  HiKOKI UC18YDML バッテリー急速充電器 WH36DD   ← 充電器が本体¥36,500と比較
    ¥16,107  Geekria PRO 充電ヘッドホンケース WH-1000XM5   ← ケースが本体¥30,990と比較

## 旗であって門やない
自前の正規表現で**殺したら**、工場と盤で「玉」の定義が2つになる
(台帳の `factory.title_ok` を借りる節と真っ向からぶつかる)。しかも
regexで殺す向きは**この盤が一番高い授業料を払った失敗**や——
2026-08-07、全データで一番良い玉(XF56mm・勝ち語14点)を自分の正規表現が
killしとった。

せやから **`疑い` 列を足すだけ**にした。既定では畳むが、外せば全部見える。
純利も等級も1円も動かさん。最終権限は人間のまま。

## 2つの旗を別々に持つ理由
**部品語**(ロジックボード・液晶パネル)は本体の出品には絶対に出ん。精度が高い。
**付属品語**(ケース・充電器)は本体の出品にも普通に出る——
「充電器・ケース**別売**」「**本体**ケース」「WH36DD 36V 充電器 ケース」は
どれも本体や。語だけ見たら撃ち落とす。せやから2つ門を足した:

  1. **本体語・同梱語があったら旗を立てん**(本体/別売/付属/付き/込み/セット/同梱)
  2. **付属品語が型番より後ろにあったら旗を立てん**。日本語の出品タイトルは
     「〈商品〉…〈型番〉…〈付属〉」の順に書く。型番より**前**に付属品語が
     来るのは「その付属品が商品」のときや:

         Geekria PRO 充電ヘッドホン[ケース] … WH-1000XM5   ← ケースが先 = ケースが商品
         HiKOKI UC18YDML バッテリー急速[充電器] WH36DD    ← 充電器が先 = 充電器が商品
         HiKOKI インパクトドライバ [WH36DD] 36V 充電器 ケース ← 型番が先 = 本体
"""
from __future__ import annotations

import re

import pandas as pd

# **本体の出品には出ん語。** これが入っとったら中身は部品や。
PARTS_RE = re.compile(
    r"ロジックボード|マザーボード|メイン基板|基板のみ|"
    r"液晶パネル|液晶ディスプレイ|フロントパネル|バックパネル|"
    r"互換品|互換バッテリー|修理用|交換用|修理パーツ|部品取り|"
    r"取り外し品|取外し品|より取り外し|ジャンク部品"
)

# **本体の出品にも普通に出る語。** 下の2つの門を通ったときだけ旗を立てる。
ACCESSORY_RE = re.compile(
    r"ケース|カバー|充電器|充電スタンド|ACアダプタ|ACアダプター|"
    r"ストラップ|レンズフード|保護フィルム|ホルダー|三脚|"
    r"収納バッグ|キャリングバッグ"
)

# 本体やと分かる語・同梱の言い回し。これがあれば付属品語は無視する
BODY_HINT_RE = re.compile(r"本体|別売|付属|付き|込み|セット|同梱")

# family から型番トークンを取る(数字を含む最後の区切り)。
# `p_tools_wh36dd`→wh36dd / `p_audio_wh1000xm5`→wh1000xm5 / `d850`→d850
_SEP_RE = re.compile(r"[\s\-_/・,、。（）()\[\]【】]+")


def _norm(s: str) -> str:
    return _SEP_RE.sub("", str(s)).lower()


def model_token(family: str) -> str:
    """型番トークン。数字を含む区切りが無ければ空(=位置の門は使わん)。"""
    parts = [p for p in str(family).split("_") if any(c.isdigit() for c in p)]
    return parts[-1].lower() if parts else ""


def reason(title: str, family: str = "") -> str:
    """旗の理由。空文字なら疑い無し。"""
    t = str(title)
    m = PARTS_RE.search(t)
    if m:
        return f"部品の語「{m.group()}」"
    m = ACCESSORY_RE.search(t)
    if not m:
        return ""
    if BODY_HINT_RE.search(t):
        return ""                      # 「本体ケース」「充電器・ケース別売」
    tok = model_token(family)
    if tok:
        tok_at = _norm(t).find(tok)
        acc_at = len(_norm(t[:m.start()]))     # 付属品語の位置(区切りを抜いた座標)
        # 型番より後ろに出る付属品語は「本体＋付属」の書き方や
        if 0 <= tok_at < acc_at:
            return ""
    return f"付属品の語「{m.group()}」が型番より前"


def flag(df: pd.DataFrame, title_col: str = "title",
         family_col: str = "family") -> pd.DataFrame:
    """`疑い` と `疑いの理由` を足して返す。**採点は一切変えん。**"""
    if df.empty or title_col not in df:
        return df
    out = df.copy()
    fam = out[family_col] if family_col in out else pd.Series([""] * len(out),
                                                              index=out.index)
    out["疑いの理由"] = [reason(t, f) for t, f in zip(out[title_col], fam)]
    out["疑い"] = (out["疑いの理由"] != "").map({True: "⚠ 要確認", False: ""})
    return out


def drop_suspect(df: pd.DataFrame) -> pd.DataFrame:
    """旗の立った行を落とす。**既定の表示用で、データは消さん。**"""
    return df[df["疑い"] == ""] if "疑い" in df else df
