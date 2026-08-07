# -*- coding: utf-8 -*-
"""streamlit.app に上げるための小さいスナップショットを書き出す。

クラウドには `C:\\dev\\souba-league` が無い。かというて生データを積むわけにもいかん
(キタムラ買取表は1枚6MB、ヤフオク落札は16MB)。なので**計算し終わった結果だけ**を
`data/snapshot/` に落とす。クラウドのアプリはそこしか読まん。

    python export_snapshot.py     # ローカルで回す。git push する前に必ず1回

書き出すもの(全部小さい):
    master.csv     型番マスタ(等級つき)
    winners.csv    買い物リスト
    signals.csv    工場の台帳
    keeps.csv      検品を通った個体
    moves.csv      買取表の日次差分
    freshness.csv  データ源の鮮度
    fa_morning.csv fa-souba 朝リスト
    meta.json      いつ・どの断面か
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from core import alerts as A
from core import sources as S
from core import watchlist as W

SNAP = S.DATA / "snapshot"


def dump(name: str, df: pd.DataFrame) -> int:
    SNAP.mkdir(parents=True, exist_ok=True)
    if df is None or df.empty:
        df = pd.DataFrame()
    df.to_csv(SNAP / f"{name}.csv", index=False, encoding="utf-8-sig")
    kb = (SNAP / f"{name}.csv").stat().st_size / 1024
    print(f"  {name:<14} {len(df):>5} 行  {kb:>7.1f} KB")
    return len(df)


def main() -> int:
    if not S.SOUBA.exists():
        print(f"! {S.SOUBA} が無い。ローカルで回すこと。")
        return 1

    print("スナップショットを書き出す")
    master = W.build_master()
    dump("master", master)
    dump("winners", W.winners())

    sig = pd.concat([W.load_signals(n) for n in S.NICHES], ignore_index=True)
    dump("signals", sig)

    keeps = []
    for niche, cfg in S.NICHES.items():
        k = W.keep_items(niche)
        if not k.empty:
            k = k.copy()
            k["ニッチ"] = cfg["label"]
            keeps.append(k)
    dump("keeps", pd.concat(keeps, ignore_index=True) if keeps else pd.DataFrame())

    d_old, d_new, hit = A.sell_alerts(master)
    _, _, moves = A.buyback_moves("camera")
    dump("sell_hits", hit)
    dump("moves", moves.head(500) if not moves.empty else moves)

    dump("freshness", S.freshness())
    fa_date, fa = S.fa_morning()
    dump("fa_morning", fa)

    # 判定器はクラウドにも要る(進行中個体の検品と勝ち語採点)。
    # 別実装は持たん主義やから、**souba-league の実物をコピーする**。
    # あくまでビルド成果物で、原本は souba-league/src。ここを直接編集したらあかん。
    vendor = Path(__file__).parent / "core" / "vendor"
    vendor.mkdir(parents=True, exist_ok=True)
    (vendor / "__init__.py").write_text("", encoding="utf-8")
    for name in ("verify_body.py", "find_winners.py", "spread_camera.py"):
        src = S.SOUBA / "src" / name
        if src.exists():
            head = f"# 自動コピー(原本: souba-league/src/{name})。直接編集するな。\n"
            (vendor / name).write_text(
                head + src.read_text(encoding="utf-8"), encoding="utf-8")
            print(f"  vendor/{name}")

    meta = {
        "作成": datetime.now().isoformat(timespec="seconds"),
        "判定器": {k: S.judge_kind(k) for k in S.NICHES},
        "買取表の差分": f"{d_old} → {d_new}",
        "fa朝リスト": fa_date,
        "型番数": int(len(master)),
        "買い物リスト": int(len(W.winners())),
    }
    (SNAP / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n{json.dumps(meta, ensure_ascii=False)}")
    total = sum(p.stat().st_size for p in SNAP.glob("*")) / 1024
    print(f"合計 {total:.0f} KB -> {SNAP}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
