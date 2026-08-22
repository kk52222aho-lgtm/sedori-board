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
from core import lanes as LN
from core import sources as S
from core import watchlist as W

SNAP = S.DATA / "snapshot"
# souba-league が吐く**いま買える玉**。フリマ候補に検品判定と売切状態を付けたもの
# 生パスは `` がフォームフィードに化ける。Path を継ぎ足して組む
FLIP = Path("C:/dev/souba-league/data/flip")


def build_buylist() -> pd.DataFrame:
    """フリマ候補 + 検品 + 売切状態 を1枚にする。

    **上位ほど誤マッチが濃い**という規律(core/audit_gate.py)はここでも同じや。
    純利の降順で出すが、それは買いキューやのうて監査キューや。
    """
    # **仕入れ面は1つやない。** 面を足すたびにここを書き換える形にしとったら
    # 必ず忘れる(2026-08-16、ラクマを4面目にしたのに検査器へ入れ忘れた)。
    # **ファイル名から自動で拾う。**
    MARKET = {"flea": "Yahoo!フリマ", "mercari": "メルカリ", "rakuma": "ラクマ"}
    frames = []
    for f in sorted(FLIP.glob("*_candidates.csv")):
        key = f.name.replace("_candidates.csv", "")
        d = pd.read_csv(f, encoding="utf-8-sig")
        if d.empty:
            continue
        d["市場"] = MARKET.get(key, key)
        frames.append(d)
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    # **候補CSVが既に検品を持っとるなら、それが最新や。**
    # 2026-08-15: ここで無条件に merge しとったせいで pandas が
    # `verdict_x`/`verdict_y` に分裂させ、**盤が全件「未検品」になった**。
    # 別ファイルは「候補に検品が無いとき」の補いにしか使わん。
    for c in ("verdict", "hit", "status"):
        if c not in df:
            df[c] = ""
        df[c] = df[c].fillna("")
    need = df["verdict"].astype(str).str.strip() == ""
    x = FLIP / "flea_xtab2.csv"
    if need.any() and x.exists():
        xt = pd.read_csv(x, encoding="utf-8-sig")[["url", "verdict", "hit", "status"]]
        m = dict(zip(xt["url"], zip(xt["verdict"], xt["hit"], xt["status"])))
        for i in df.index[need]:
            got = m.get(df.at[i, "url"])
            if got:
                df.at[i, "verdict"], df.at[i, "hit"], df.at[i, "status"] = got
    keep = ["市場", "family", "title", "price", "median", "net", "condition",
            "verdict", "hit", "status", "url", "scanned_at"]
    return df[[c for c in keep if c in df]]



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
    dump("live_winners", W.live_winners())

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

    dump("buylist", build_buylist())
    # 「どこで買ってどこで売るか」。**旗立ては画面側でやる**
    # (閾値をスライダーで動かすので、生の列を持たせたまま出す)
    dump("lanes", LN.build())
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
        "実績サンプル": int(len(W.winners())),
        "いま買える玉": int(len(W.live_winners())),
    }
    (SNAP / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n{json.dumps(meta, ensure_ascii=False)}")
    total = sum(p.stat().st_size for p in SNAP.glob("*")) / 1024
    print(f"合計 {total:.0f} KB -> {SNAP}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
