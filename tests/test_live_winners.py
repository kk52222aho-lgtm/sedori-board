# -*- coding: utf-8 -*-
"""「いま買える玉」の札が**買えるかを見とる**か。**python tests/test_live_winners.py**

2026-09-23。段は勝ち語の点数だけで付いとって、**買い線を超えとる玉にも
「🏆 実弾GO」「👍 買える」が貼られとった**。実測で70件中10件、
そのうち5件は想定純利がマイナス(最悪 −¥16,400)。

このファイル(souba-league/src/live_winners.py)は 2026-08-08 に
「盤の買い物リストの玉が全部2〜6月に終わっとった。**看板に偽りがあった**」
いうて書かれたもんやのに、**看板の付け方が同じ穴を開けとった**。

**札は2つの条件の掛け算や**: 買い線の内側(値段) × 勝ち語(質)。
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import watchlist as W  # noqa: E402


def _stage(d: pd.DataFrame) -> pd.Series:
    """watchlist.live_winners と同じ式。**写しやのうて同じ形を確かめるため**や。"""
    buyable = d["いま買える"].astype(str).eq("○")
    clean = d["欠陥"].isna() | d["欠陥"].astype(str).str.strip().eq("")
    return pd.Series(np.where(~buyable, "👀 監視(買い線の外)",
                              np.where(~clean, "🥶 欠陥あり",
                                       np.where(d["勝ち語"] >= 5, "🏆 実弾GO",
                                                np.where(d["勝ち語"] >= 4,
                                                         "👍 買える",
                                                         "🤏 見送り")))),
                     index=d.index)


def test_買い線の外は点が高うても買えると言わん():
    d = pd.DataFrame({
        "いま買える": ["○", "○", "○", "監視", "監視", "監視"],
        "勝ち語": [7, 4, 2, 9, 4, 0],
        "欠陥": [None, "", None, None, "", None],
    })
    got = list(_stage(d))
    assert got[0] == "🏆 実弾GO" and got[1] == "👍 買える" and got[2] == "🤏 見送り"
    # **点が9点でも買い線の外なら「買える」とは言わん。ここが穴やった**
    assert all("監視" in g for g in got[3:]), got
    print("OK 札: ○×点数の掛け算(9点でも買い線の外なら監視)")


def test_欠陥がある玉に買える札を貼らん():
    """**掛け算の3項目**(2026-09-23)。元の道具は `not r["欠陥"]` で絞っとる。

    1回目の直しで「買えるか」を足して満足したが、**盤はまだ `欠陥` を
    見とらんかった**。唯一「👍 買える」が立っとった玉は **欠陥=欠品**やった。
    **盤が、データを作った道具より甘かった。**
    """
    d = pd.DataFrame({
        "いま買える": ["○", "○", "○", "○"],
        "勝ち語": [9, 7, 4, 4],
        "欠陥": ["欠品", None, "カビ・くもり", ""],
    })
    got = list(_stage(d))
    assert got[0] == "🥶 欠陥あり", got      # 9点でも欠陥があれば貼らん
    assert got[1] == "🏆 実弾GO", got
    assert got[2] == "🥶 欠陥あり", got
    assert got[3] == "👍 買える", got        # 空文字は「欠陥なし」
    print("OK 欠陥: 9点でも欠品なら貼らん / 空文字は欠陥なし")


def test_盤は元の道具より甘うない():
    """`live_winners.py` が絞っとる条件を**源から読んで**、盤も全部見とるか。

    **項を1つ足して満足したら、また次の項が抜ける。**
    """
    src = Path("C:/dev/souba-league/src/live_winners.py")
    if not src.exists():
        print("OK (souba-league が見えん機械。ここは飛ばす)")
        return
    line = [l for l in src.read_text(encoding="utf-8").splitlines()
            if "go = [r for r in rows" in l]
    assert line, "元の道具の絞り込みが見つからん(形が変わったら検定も直す)"
    for need in ("勝ち語", "欠陥"):
        assert need in line[0], f"元の道具が {need} で絞っとるのに検定が知らん"
    board = (ROOT / "core" / "watchlist.py").read_text(encoding="utf-8")
    seg = board[board.index("def live_winners"):]
    seg = seg[:seg.index("def winners")]
    for need in ("いま買える", "勝ち語", "欠陥"):
        assert need in seg, f"盤の段が {need} を見とらん"
    print("OK 条件: 元の道具の絞り(勝ち語/欠陥)を盤も全部見とる + 買い線も")


def test_実物で買えん玉に買える札が付いとらん():
    d = W.live_winners()
    if d.empty:
        print("OK 実物: live_winners が空(検定はここまで)")
        return
    lab = d["段"].astype(str).str.contains("実弾GO|👍 買える")
    bad = d[lab & (d["いま買える"].astype(str) != "○")]
    assert bad.empty, f"買えんのに買える札: {len(bad)}件"
    # **3項目**: 欠陥があるのに買える札が付いとらんか
    bad2 = d[lab & d["欠陥"].notna()
             & d["欠陥"].astype(str).str.strip().ne("")]
    assert bad2.empty, f"欠陥があるのに買える札: {len(bad2)}件"
    n_ok = int((d["いま買える"].astype(str) == "○").sum())
    print(f"OK 実物: {len(d)}行のうち買えるんは {n_ok}件。"
          f"買えん玉に買える札はゼロ")


def test_数える時も買える玉だけ():
    """`meta.json` の「いま買える玉」が行数やのうて○の数を数えとるか。"""
    src = (ROOT / "export_snapshot.py").read_text(encoding="utf-8")
    assert '"いま買える玉": int(len(W.live_winners()))' not in src, \
        "行数をそのまま数えとる(監視の玉が混ざる)"
    assert '== "○"' in src, "○ を数えとらん"
    print("OK 数: meta.json は ○ の数を数えとる")


if __name__ == "__main__":
    test_買い線の外は点が高うても買えると言わん()
    test_欠陥がある玉に買える札を貼らん()
    test_盤は元の道具より甘うない()
    test_実物で買えん玉に買える札が付いとらん()
    test_数える時も買える玉だけ()
    print("\n検定ぜんぶ通った")
