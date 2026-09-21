# -*- coding: utf-8 -*-
"""鮮度の門の検定。**python tests/test_freshness.py** で回る。

2026-09-21に2つ踏んだ。どっちも「止まっとるのに生存と出る」向きの壊れ方や:

  1. **クラウドが写真を出しとった。** `freshness()` は CLOUD だと
     `snap("freshness")` をそのまま返しとって、あれは export した瞬間の
     鮮度を撮った写真や。export が止まったら永久に「生存」と言い続ける
  2. **時計が9時間ズレとった。** 中の時刻は全部JSTなのに「今」だけ
     走っとる機械のローカル時刻やった。UTCのコンテナで9時間若く出る
"""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import sources as S  # noqa: E402


def test_今はJSTで取る():
    diff = (S._now_jst() - pd.Timestamp.now(tz="UTC").tz_localize(None))
    hours = diff.total_seconds() / 3600
    assert 8.9 < hours < 9.1, f"JSTになっとらん: UTCとの差 {hours:.2f}時間"
    print(f"OK 時計: 「今」はUTC+{hours:.1f}時間 = JST")


def test_クラウドの鮮度は測り直す():
    """写真の「経過」やのうて、「最終更新」と今を比べ直しとるか。"""
    d = S.snap("freshness")
    assert not d.empty, "スナップが無いと検定にならん"
    frozen = dict(zip(d["データ源"], d["経過"]))
    live = S.freshness()
    row = live[live["データ源"] == "カメラ・工場台帳"]
    assert not row.empty
    before, after = frozen["カメラ・工場台帳"], row.iloc[0]["経過"]
    assert before != after, f"写真のまま出しとる({before})"
    print(f"OK 測り直し: カメラ・工場台帳 写真「{before}」→ 実際「{after}」")


def test_断面そのものが行として出る():
    live = S.freshness()
    head = live.iloc[0]
    assert "断面" in head["データ源"], f"先頭が断面やない: {head['データ源']}"
    assert head["土台"] is True or str(head["土台"]).lower() == "true"
    age = S.snap_age_h()
    if age is not None and age > 24 * S.FRESH_DEAD:
        assert "停止" in head["状態"], head["状態"]
        assert head["データ源"] in set(S.stalled()["データ源"]), "上段の🚨に出らん"
        print(f"OK 断面: {head['経過']}前 → {head['状態']}・上段の警告にも出る")
    else:
        print(f"OK 断面: {head['経過']}前 → {head['状態']}")


def test_周期の文字列を時間に戻せる():
    assert S._unhuman("1.0時間") == 1.0
    assert S._unhuman("30.0日") == 720.0
    assert S._unhuman("—") is None and S._unhuman("") is None
    print("OK 周期のパース: 時間/日/欠損")


if __name__ == "__main__":
    test_今はJSTで取る()
    test_周期の文字列を時間に戻せる()
    test_クラウドの鮮度は測り直す()
    test_断面そのものが行として出る()
    print("\n検定ぜんぶ通った")
