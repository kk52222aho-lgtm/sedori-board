# -*- coding: utf-8 -*-
"""鮮度の門の検定。**python tests/test_freshness.py** で回る。

2026-09-21に2つ踏んだ。どっちも「止まっとるのに生存と出る」向きの壊れ方や:

  1. **クラウドが写真を出しとった。** `freshness()` は CLOUD だと
     `snap("freshness")` をそのまま返しとって、あれは export した瞬間の
     鮮度を撮った写真や。export が止まったら永久に「生存」と言い続ける
  2. **時計が9時間ズレとった。** 中の時刻は全部JSTなのに「今」だけ
     走っとる機械のローカル時刻やった。UTCのコンテナで9時間若く出る

    🚨 **検定は `_freshness_cloud()` を名指しで叩く。** `freshness()` 経由やと
    souba-league が見える機械(= 家)では**別の関数が走ってまう**ので、
    直したはずのクラウドの穴を一度も通らん。実際、初版は家で1本落ちた
    (断面の行はクラウド側にしか無い)。**どっちの機械でも同じ物を測る。**
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
    """写真の「経過」やのうて、「最終更新」と今を比べ直しとるか。

    🚨 **本物の断面と比べたらあかん。** 初版は実物の写真の「経過」と
    測り直した値が**違うこと**を assert しとった。せやが export した直後は
    どっちも「0.5時間」で一致してまう——**盤が一番健康なときだけ落ちる**
    検定や。凍らせた偽の断面を食わせて、**古い写真が🚨に化ける**かを見る。
    """
    fake = pd.DataFrame([{
        "データ源": "偽の源", "パス": "C:/なし.csv",
        # 10日前に更新されたのに、写真は「0.2時間前・生存」で凍っとる
        "最終更新": (S._now_jst() - pd.Timedelta(days=10)).strftime("%Y-%m-%d %H:%M"),
        "経過": "0.2時間", "周期": "1.0時間", "状態": "生存",
        "土台": True, "備考": "",
    }])
    real_snap = S.snap
    S.snap = lambda name, **kw: fake.copy() if name == "freshness" else real_snap(name, **kw)
    try:
        live = S._freshness_cloud()
    finally:
        S.snap = real_snap
    row = live[live["データ源"] == "偽の源"].iloc[0]
    assert row["状態"].endswith("停止"), f"写真のまま出しとる: {row['状態']}"
    assert row["経過"] == "10.0日", row["経過"]
    print(f"OK 測り直し: 写真「0.2時間・生存」→ 実際「{row['経過']}・{row['状態']}」")


def test_古い断面は先頭で赤くなる():
    """**盤が5日前の写真やったら、先頭の行が🚨になって上段の警告にも出るか。**

    2026-09-17〜22に実際にこうなった(push が35回弾かれて断面が凍った)。
    本物の `meta.json` が古い日だけ通る検定にしたら、**直った日から
    二度と通らん**。作成時刻を偽って、両側(新しい/古い)を測る。
    """
    real_meta = S.snap_meta
    for 日, 赤 in ((0.0, False), (5.0, True)):
        made = (S._now_jst() - pd.Timedelta(days=日)).isoformat()
        S.snap_meta = lambda: {"作成": made}
        try:
            live = S._freshness_cloud()
        finally:
            S.snap_meta = real_meta
        head = live.iloc[0]
        assert "断面" in head["データ源"], head["データ源"]
        if 赤:
            assert "停止" in head["状態"], head["状態"]
            assert head["データ源"] in set(S.stalled(live)["データ源"]), "上段の🚨に出らん"
        else:
            assert head["状態"] == "生存", head["状態"]
        print(f"OK 断面 {日:.0f}日前 → {head['状態']}")


def test_断面そのものが行として出る():
    live = S._freshness_cloud()
    head = live.iloc[0]
    assert "断面" in head["データ源"], f"先頭が断面やない: {head['データ源']}"
    assert head["土台"] is True or str(head["土台"]).lower() == "true"
    age = S.snap_age_h()
    if age is not None and age > 24 * S.FRESH_DEAD:
        assert "停止" in head["状態"], head["状態"]
        assert head["データ源"] in set(S.stalled(live)["データ源"]), "上段の🚨に出らん"
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
    test_古い断面は先頭で赤くなる()
    print("\n検定ぜんぶ通った")
