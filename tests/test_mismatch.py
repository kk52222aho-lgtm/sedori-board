# -*- coding: utf-8 -*-
"""`core/mismatch.py` の検定。**python tests/test_mismatch.py** で回る。

道具は「既知の答えを拾えるか」で検定せなあかん([sedori-board] 2026-08-07)。
殺す側の精度だけ見とったら、全データで一番良い玉を自分のパイプラインが
殺しとった穴に半日気付かんかった。せやから2本立てにした:

  1. **実データ全量**(buylist.csv 95行)で、人手ラベルの誤マッチを全部拾って
     本体を1件も撃たんこと
  2. **素朴な語リストなら必ず踏む10行**を名指しで固定。ここが緩むと
     「充電器・ケース別売」の本体を撃ち落とす向きに戻る
"""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import mismatch as MM  # noqa: E402

# 中身が本体やない行(= median の比較対象と別物)。2026-09-17に人手で当たった
人手ラベル = [
    "Geekria PRO 充電ヘッドホンケース",            # ×3。ケースが本体¥30,990と比較
    "UC18YDML",                                     # 急速充電器が本体¥36,500と比較
    "液晶ディスプレイ　A2159 2019年より取り外し",
    "A2159 ロジックボード",
    "A1706 ロジックボード",
]

# 素朴な語リストが必ず踏む10行。(タイトル, family, 旗が立つべきか)
際どい行 = [
    ("未使用品 HiKOKI ハイコーキ UC18YDML 2ポート 36v 10.8v バッテリー急速充電器 WH36DD ",
     "p_tools_wh36dd", True),
    ("Geekria PRO 充電ヘッドホンケース ソニー Sony WH-1000XM6、WH-1000XM5、WH-1000XMVL",
     "p_audio_wh1000xm5", True),
    ("【完動品】MacBook Pro 13inch 2019 A2159 ロジックボード Intel Core i5 SSD 250",
     "p_pc_a2159", True),
    # ↓ ここから下は全部**本体**や。語だけ見たら全部撃ち落とす
    ("HiKOKI ハイコーキ　コードレスインパクトドライバ WH36DD 36V 充電器 ケース　未使用",
     "p_tools_wh36dd", False),
    ("HiKOKI(ハイコーキ) 36V 充電式 インパクトドライバ スパイダーイエロー 蓄電池・充電器・ケース別売 WH36DD(NN",
     "p_tools_wh36dd", False),
    ("未使用品　HiKOKI インパクトドライバー WH36DD 本体ケース ブラック",
     "p_tools_wh36dd", False),
    ("HiKOKI コードレスインパクトドライバ WH36DDフォレストグリーン本体ケース",
     "p_tools_wh36dd", False),
    ("HiKOKI 36V コードレスインパクトドライバ WH36DD 本体とビット",
     "p_tools_wh36dd", False),
    ("SONY DSC-RX100M4 サイバーショット コンパクトデジタルカメラ 充電池×2個付属",
     "w_rx100m4", False),
    ("FUJIFILM XF56mm F1.2 R 単焦点レンズ #C260624-07", "w_xf56mm", False),
]


def test_実データ全量():
    d = pd.read_csv(ROOT / "data/snapshot/buylist.csv", dtype=str).fillna("")
    d = MM.flag(d)
    真 = d["title"].map(lambda t: any(k in t for k in 人手ラベル))
    旗 = d["疑い"] != ""
    誤爆 = d[~真 & 旗]
    取り逃し = d[真 & ~旗]
    assert 誤爆.empty, "本体を撃ち落としとる:\n" + "\n".join(誤爆["title"])
    assert 取り逃し.empty, "誤マッチを取り逃しとる:\n" + "\n".join(取り逃し["title"])
    print(f"OK 実データ{len(d)}行: 誤マッチ{int(真.sum())}件を全部拾い、"
          f"本体{int((~真).sum())}件は1件も撃っとらん")


def test_際どい行():
    for t, f, want in 際どい行:
        got = MM.reason(t, f) != ""
        assert got == want, f"{'旗' if got else '素通し'}になっとる: {t}"
    print(f"OK 際どい{len(際どい行)}行: 全部正しく捌いた")


if __name__ == "__main__":
    test_実データ全量()
    test_際どい行()
    print("\n検定ぜんぶ通った")
