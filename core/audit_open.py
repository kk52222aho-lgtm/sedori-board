# -*- coding: utf-8 -*-
"""**旗が黙って素通りしとる行を数える。** 確認層の上に確認層を置く道具。

    python -m core.audit_open

## なんで要るか
2026-08-24、同じ形の事故が1日で2件出た:

    seller_id が 4,048件中14件しか埋まっとらんのに「業者率 **0%**」と表示
      → フィルタ(業者率≤34%)が100%素通しして「勝てそう6件」を報告。実は0件
    check_gates がテスト出力の**最後の1行しか見てへん**
      → jp_part のテストを足した瞬間、is_body 本体の 39/39 が黙って無検査に

どっちも**門のロジックは正しかった**。壊れとったのは「門が効いとることを
確かめる層」で、しかも**確認層の上には確認層が無い**から、自分で踏むまで
見つからん。

`lanes.flags()` は盤の背骨やが、規則が全部この形をしとる:

    if pd.notna(v) and v >= 閾値:   ← **v が NaN やと絶対に旗が立たん**

「測れてへん」が「問題なし」に化ける。旗が空欄の行は、
**検査して通った行と、検査でけへんかった行が混ざっとる。**

10個の規則のうち**正しく書けとるのは1つだけ**やった——出口n/入口n が
`elif is_export: w.append("標本が不明")` と、不明にも旗を立てとる。
そのコメント自身が「0件と未測を同じ入れ物に入れると盤が嘘をつく」と
言うとるのに、他の9個には適用されとらん。しかもその1つも輸出行限定で、
国内行の標本欠損は黙る。

## 何を出すか
規則ごとに3つに割る。

    旗が立った     欠陥を見つけた
    検査して通った  入力があって閾値の内側やった
    **黙って通った** 入力が欠損しとって検査自体が起きんかった  ← これが答え

「黙って通った」が多い規則は、**その規則が守っとるつもりの穴が開いとる**。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import lanes as LN  # noqa: E402

# 🚨 **空欄の意味は2種類ある。ここを混ぜたら監査自身が嘘をつく。**
# 初版で `構成差` と `型番弱` を「88%が黙って通っとる」と報告したが、
# purity.py はこの2つを**全行に対して計算して、該当せんかったら空文字**を
# 書いとる(`"構成差": "要注意" if iqr > MAX_IQR else ""`)。つまり空欄は
# **測って問題なし**や。監査が、今まさに指摘しとる失敗をやっとった。
#
#   NEGATIVE  空欄 = 検査して該当せんかった   → 穴やない
#   UNKNOWN   空欄 = そもそも測っとらん       → 穴
#
# 見分け方は「その列を書く側のコードが、全行に対して書いとるか」や。
# 表の側からは区別でけへん——**出所を読まなあかん**。
BLANK_IS_NEGATIVE = {"構成差", "型番弱", "構成", "出口状態"}

# (名前, 要る列, 説明) — flags() の規則と1対1に対応させる
RULES = [
    ("左右ズレ疑い", ("仕入値", "売値"), "入口が売値の5%未満=引き算の左右がズレとる"),
    ("汚染率", ("汚染率",), "出口の母集団に別物が混ざっとる"),
    ("出口標本", ("出口n",), "出口の標本が薄い"),
    ("入口標本", ("入口n",), "入口の標本が薄い"),
    ("年台数", ("年台数",), "年1台未満=待ち"),
    ("打ち切り", ("出口生", "出口本体"), "生データが打ち切られて中央値が壊れとる"),
    ("入口p25ゴミ", ("仕入値", "入口中央"), "入口の安値側にゴミが残って粗利が盛られる"),
    ("買い線が届かん", ("買い線", "仕入値"), "買い線が落札p25を下回る=まず買えん"),
    ("走査の鮮度", ("走査",), "古い行が「まだ買える」顔で残る"),
    ("構成セット混在", ("構成",), "セットと単体を同じ上限で見とる"),
    ("構成差", ("構成差",), "トリム後もIQRが閾値超え"),
    ("型番弱", ("型番弱",), "型番の照合が弱い"),
    ("検品", ("検品",), "本文に欠陥の自白が無いか"),
]


def filled(s: pd.Series) -> pd.Series:
    """埋まっとるか。数値列は NaN、文字列列は空文字が欠損や。"""
    if pd.api.types.is_numeric_dtype(s):
        return s.notna()
    t = s.astype(str).str.strip()
    return s.notna() & (t != "") & (t.str.lower() != "nan")


def applicable(df: pd.DataFrame, cols) -> bool:
    """その規則がこのレーンに当てはまるか。

    **輸出だけの列(汚染率・年台数)と国内だけの列(走査)を同じ分母で混ぜたら、
    俺自身が incomparable な測定をしとることになる。** 判定は「そのレーンの
    どれか1行でも埋まっとるか」——1行でも埋まるなら、その列はこのレーンで
    取れるはずの列や。1行も無いなら、そもそも別レーンの列やと見なす。
    """
    for c in cols:
        if c not in df or not filled(df[c]).any():
            return False
    return True


def report(df: pd.DataFrame, label: str) -> None:
    n = len(df)
    if not n:
        return
    raised = df["要注意"].fillna("").astype(str).str.strip() != ""
    print(f"\n■ {label} {n}行 / 旗が立った行 {int(raised.sum())} "
          f"({raised.mean() * 100:.0f}%)")
    print(f"   {'規則':<16}{'旗':>5}{'検査して通った':>14}{'黙って通った':>14}"
          f"{'穴':>8}")
    skipped = []
    holes = []
    for name, cols, _why in RULES:
        if not applicable(df, cols):
            skipped.append(name)
            continue
        missing = pd.Series(False, index=df.index)
        for c in cols:
            if c in BLANK_IS_NEGATIVE:
                continue          # 空欄=検査して該当せんかった。穴やない
            missing |= ~filled(df[c])
        hit = df["要注意"].fillna("").astype(str).str.contains(
            name.replace("が届かん", "").replace("疑い", ""), regex=False)
        silent = int((missing & ~hit).sum())
        checked = int((~missing & ~hit).sum())
        holes.append((silent / n, name, int(hit.sum()), checked, silent))
    for rate, name, h, c, s_ in sorted(holes, reverse=True):
        mark = " ←" if rate >= 0.5 else ""
        print(f"   {name:<16}{h:>5}{c:>14}{s_:>14}{rate * 100:>7.0f}%{mark}")
    if skipped:
        print(f"   (このレーンに無い列の規則は外した: {', '.join(skipped)})")

    # 「全体」はレーンを混ぜとるので、この行は出さん。輸出だけの列と
    # 国内だけの列を同じ分母に入れたら必ず 0% になる(監査自身が
    # incomparable な測定をやることになる)
    noflag = df[~raised]
    if len(noflag) and label != "全体":
        need = [c for _n, cs, _w in RULES if applicable(df, cs) for c in cs
                if c not in BLANK_IS_NEGATIVE]
        need = [c for c in dict.fromkeys(need)]
        full = noflag[need].apply(filled).all(axis=1)
        print(f"   **旗なし {len(noflag)}行のうち、入力が全部揃って旗なし: "
              f"{int(full.sum())}行** ({full.mean() * 100:.0f}%)")
        if full.mean() < 1:
            cov = sorted(((filled(noflag[c]).mean(), c) for c in need))[:5]
            print("     欠けとる入力:", ", ".join(
                f"{c} {v * 100:.0f}%" for v, c in cov))


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    df = LN.flags(LN.build())
    if df.empty:
        print("レーンが空や")
        return 1
    report(df, "全体")
    if "種別" in df:
        for kind, g in df.groupby(df["種別"].astype(str)):
            report(g, kind)
    print("\n※ 「黙って通った」が多い規則は、守っとるつもりの穴が開いとる。"
          "\n  空欄が「検査して問題なし」なのか「検査でけへんかった」なのかを"
          "\n  区別できる形(不明にも旗を立てる)に直すのが手当てや")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
