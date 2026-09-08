# -*- coding: utf-8 -*-
"""データ源のレジストリ。せどり各リポジトリのCSVはここだけで解決する。

sedori-board は**計算せん**。souba-league が吐いた台帳・検品結果・買取スナップを
読んで束ねるだけ。収集ロジックを二重に持つと必ずズレるので、パスの解決と
列名の正規化だけをここに集める。
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

DEV = Path(r"C:\dev")
SOUBA = DEV / "souba-league"
FA = DEV / "fa-souba"
REEL = DEV / "reel-souba"
BOARD = Path(__file__).resolve().parents[1]
DATA = BOARD / "data"
SNAP = DATA / "snapshot"

# streamlit.app には souba-league が無い。そこでは **export_snapshot.py が
# 書き出した計算済みCSVだけ**を読む。生データ(買取表1枚6MB・落札16MB)は積まん。
CLOUD = not SOUBA.exists()


def snap(name: str, **kw):
    """スナップショットを読む。無ければ空。"""
    return read_csv(SNAP / f"{name}.csv", **kw)


def snap_meta() -> dict:
    import json
    p = SNAP / "meta.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}

# ニッチ定義。verified は「本文検品済み」CSVの**優先順**リスト。
# _llm.csv を先に見るのは、38件の人手ラベルで測った結果が
#   regex : 撃墜の再現率は高いが**生存側の精度が致命的**(カメラ3件中1件しか残せず)
#   LLM   : 同じ再現率で生存4件中3件を正しく残す
# やったから。生存率1割の世界では生存側の精度が命で、regex版で等級を付けると
# 実際に勝てる型番(XF56mm・ES35100)を🔴死に落とす。実測済みの事故や。
NICHES = {
    "camera": dict(
        label="カメラ",
        channel="ヤフオク → キタムラ/フジヤ買取",
        models=[SOUBA / "models/camera.csv", SOUBA / "models/camera_wide.csv",
                SOUBA / "models/camera_cheap.csv"],
        # 帯ごとに別ファイル。camera_cheap は買取¥1.5〜5万帯(2026-08-07に追加)。
        # 初期の camera_wide は買取価格の降順で120本に打ち切られとって、
        # 高額=希少=玉が薄い型番ばかりを見とった。
        verified=[SOUBA / "data/camera/candidates_llm.csv",
                  SOUBA / "data/camera/candidates_verified.csv"],
        verified_extra=[SOUBA / "data/camera/candidates_cheap_llm.csv"],
        closed=[SOUBA / "data/camera/yahoo_closed.csv",
                SOUBA / "data/camera/yahoo_closed_wide.csv",
                SOUBA / "data/camera/yahoo_closed_cheap.csv"],
        spread_module="spread_camera",
        signals=SOUBA / "data/factory/signals.csv",
        buyback_cols=["buyback_a"],
        ship_default=1000,
        snapshot_dir=SOUBA / "data/camera",
        snapshot_prefix="kitamura_buy_",
        snapshot_key="id",
        snapshot_price="trade_in_price_a",
        snapshot_title="title",
        snapshot_min_rows=20000,   # 途中で落ちた部分スナップを弾く
        master_title_col="master_title",
    ),
    "gakki": dict(
        label="楽器",
        channel="ヤフオク → イシバシ/島村買取",
        models=[SOUBA / "models/gakki_factory.csv"],
        verified=[SOUBA / "data/gakki/candidates_llm.csv",
                  SOUBA / "data/gakki/candidates_verified.csv"],
        closed=[SOUBA / "data/gakki/yahoo_closed.csv"],
        spread_module="spread_gakki",
        signals=SOUBA / "data/factory/signals_gakki.csv",
        buyback_cols=["buy_normal", "buy_good"],   # 保守側(並品着地)を先に
        ship_default=2000,
        snapshot_dir=None,          # 日次スナップはまだ1枚のみ
        snapshot_prefix=None,
        snapshot_key=None,
        snapshot_price=None,
        snapshot_title=None,
        snapshot_min_rows=0,
        master_title_col=None,
    ),
}

HAIRCUT = 0.9      # 買取「上限」からの減額。souba-league/src/factory.py と同値
NET_MIN = 3000     # これ未満の純利は存在しない扱い


def read_csv(path: Path | str, **kw) -> pd.DataFrame:
    """utf-8-sig 固定。無ければ空DataFrame(サイトを落とさん)。"""
    p = Path(path)
    if not p.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(p, encoding="utf-8-sig", **kw)
    except Exception:
        return pd.DataFrame()


def verified_path(niche: str) -> Path | None:
    """実在する検品済みCSVのうち、判定器が良い方を返す。"""
    for p in NICHES[niche]["verified"]:
        if Path(p).exists():
            return Path(p)
    return None


def judge_kind(niche: str) -> str:
    """その等級を作った判定器。画面に出して読み手が割り引けるようにする。

    🚨 **ファイル名で名乗らせたらあかん。** 2026-09-08まで、この関数は
    `"_llm" in p.name` だけを見て「LLM」と表示しとった。ところが
    `verify_body.py` は LLM が使えんかった行を **黙って正規表現に退避**して、
    同じ `candidates_llm.csv` に書く。同じ日に実際そうなりかけとった——
    Cerebras(主)が HTTP402、Groq(控え)は既定モデルが消滅済みで、
    **カスケードが主も控えも全滅**。その状態で回すと全行が regex 判定やのに
    画面は「LLM」と名乗る。判定器で結論が変わるのは実測済みやから
    (regex は生存側の精度が致命的)、名乗りと中身がズレるのは等級の嘘そのものや。

    せやから**中身を数える**。退避した行は `body_hit` に `(regex退避)` が
    付いとるので、スキーマを変えんでも過去のファイルごと数えられる。
    """
    if CLOUD:
        return snap_meta().get("判定器", {}).get(niche, "不明")
    p = verified_path(niche)
    if p is None:
        return "未検品"
    if "_llm" not in p.name:
        return "regex(生存側の精度が低い)"
    n_kill, n_fb = _judge_mix(p)
    if n_kill == 0:
        return "LLM(撃墜0件)"
    if n_fb == 0:
        return f"LLM(撃墜{n_kill}件を全部LLMが裁いた)"
    return (f"🚨 LLMを名乗っとるが撃墜{n_kill}件中{n_fb}件はregex退避"
            f"({n_fb / n_kill:.0%})。その分は生存を取りこぼしとる")


def _judge_mix(path: Path) -> tuple[int, int]:
    """(撃墜件数, うち正規表現に退避した件数)。等級を作った実物を数える。"""
    d = read_csv(path)
    if d.empty or "body_verdict" not in d.columns or "body_hit" not in d.columns:
        return 0, 0
    kills = d[d["body_verdict"] == "kill"]
    if kills.empty:
        return 0, 0
    hit = kills["body_hit"].fillna("")
    return len(kills), int(hit.str.startswith("(regex退避)").sum())


def snapshots(niche: str) -> list[tuple[str, Path]]:
    """(日付, パス) を古い順で返す。行数が足りん部分スナップは捨てる。"""
    cfg = NICHES[niche]
    if not cfg["snapshot_dir"]:
        return []
    out = []
    for p in sorted(Path(cfg["snapshot_dir"]).glob(f"{cfg['snapshot_prefix']}*.csv")):
        m = re.search(r"(\d{4}-\d{2}-\d{2})", p.name)
        if not m:
            continue
        if cfg["snapshot_min_rows"]:
            # 行数はサイズで代理する(全読みすると数秒かかるため)
            if p.stat().st_size < cfg["snapshot_min_rows"] * 100:
                continue
        out.append((m.group(1), p))
    return out


# ------------------------------------------------------------------ 鮮度の門
# 🚨 **「在るか」やのうて「止まっとらんか」を測る。**
# 2026-09-08まで `状態` は `p.exists()` だけを見とった。つまり源が止まっても
# 永久に「生存」と出る門で、**止まっとるのを気づかせるいう目的を果たしてへん**。
# その日の実測: 等級の土台である検品結果2枚が **32日**古いまま「生存」やった。
# souba-league では同じ穴でキタムラ買取が**29日**死んで、上書き型やから
# その断面は永久に取り返せん(docs/scheduled.md)。二度目をやる理由が無い。
#
# 門は2つある。**どっちか片方では足りん**:
#   1. 周期 — 定期実行がある源は、その間隔の1.5倍で遅延・3倍で停止。
#      閾値は docs/scheduled.md の実際の登録間隔から取る(こっちで発明せん)。
#   2. 依存 — **派生物は入力より新しいはずや**。検品結果は落札から作るのに
#      落札(09-01)より古い(08-07)なら、25日ぶんの落札が採点に入っとらん。
#      定期実行が無い源はこっちでしか捕まらん。
FRESH_LATE, FRESH_DEAD = 1.5, 3.0     # 周期の何倍で遅延/停止とみなすか
DEP_GRACE_H = 24.0                    # 依存の門の猶予。これ未満の前後は無視する


def _age_h(p: Path, now: pd.Timestamp) -> float | None:
    if not p.exists():
        return None
    return (now - _mtime(p)).total_seconds() / 3600


def _mtime(p: Path) -> pd.Timestamp:
    return (pd.Timestamp(p.stat().st_mtime, unit="s", tz="UTC")
            .tz_convert("Asia/Tokyo").tz_localize(None))


def _human(hours: float | None) -> str:
    if hours is None:
        return "—"
    if hours < 48:
        return f"{hours:.1f}時間"
    return f"{hours / 24:.1f}日"


def freshness() -> pd.DataFrame:
    """各データ源の最終更新と鮮度。工場が止まっとるのを画面で気づけるように。

    返す列: データ源 / パス / 最終更新 / 経過 / 周期 / 状態 / 備考
    状態は 生存 / ⏳遅延 / 🚨停止 / 🚨欠損 / 🚨入力より古い のいずれか。
    """
    if CLOUD:
        return snap("freshness")
    rows = []
    now = pd.Timestamp.now()

    def add(name, path, note="", 周期h=None, 土台=False, 入力=None):
        p = Path(path)
        age = _age_h(p, now)
        if age is None:
            state = "🚨 欠損"
        elif 周期h and age > 周期h * FRESH_DEAD:
            state = "🚨 停止"
        elif 周期h and age > 周期h * FRESH_LATE:
            state = "⏳ 遅延"
        else:
            state = "生存"
        # 依存の門。定期実行が無い派生物はここでしか捕まらん。
        # 🚨 **猶予が要る。** 猶予ゼロで入れたら、落札を1機種だけ追い足した
        # 数分後に「入力より0日古い」で赤が出た(2026-09-08に実際に踏んだ)。
        # 分単位の前後で吠える門は狼少年になって、本物の32日が埋もれる。
        # 意味があるのは「1回ぶんの焼き直しを飛ばした」= 日の単位や。
        if state == "生存" and 入力:
            olds = [i for i in 入力 if Path(i).exists() and _mtime(Path(i)) > _mtime(p)]
            if olds:
                lag_h = (max(_mtime(Path(i)) for i in olds)
                         - _mtime(p)).total_seconds() / 3600
                if lag_h > DEP_GRACE_H:
                    state = f"🚨 入力より{_human(lag_h)}古い"
        rows.append({
            "データ源": name,
            "パス": str(p),
            "最終更新": _mtime(p).strftime("%Y-%m-%d %H:%M") if p.exists() else "—",
            "経過": _human(age),
            "周期": _human(周期h) if 周期h else "—",
            "状態": state,
            "土台": 土台,
            "備考": note,
        })

    for key, cfg in NICHES.items():
        # souba-factory / -gakki は30分毎(docs/scheduled.md)
        add(f"{cfg['label']}・工場台帳", cfg["signals"], cfg["channel"], 周期h=1, 土台=True)
        # 検品結果には定期実行が無い。**依存の門でしか死が見えん源**や。
        vp = verified_path(key)
        add(f"{cfg['label']}・検品結果", vp or cfg["verified"][0],
            f"判定器: {judge_kind(key)}。等級はこれだけで付く",
            土台=True, 入力=cfg.get("closed", []))
        # 落札は180日ローリング。月次で回せば無欠損(collect_backlog.md 第2層#7)
        for c in cfg.get("closed", []):
            add(f"{cfg['label']}・落札180日", c, "流動性と等級の土台",
                周期h=24 * 30, 土台=True)
    snaps = snapshots("camera")
    if snaps:
        add("キタムラ買取スナップ(最新)", snaps[-1][1], f"全{len(snaps)}枚",
            周期h=24, 土台=True)
    add("fa-souba 朝リスト", _latest_morning() or FA / "data/morning",
        "ヤフオク→eBay", 周期h=24)
    # 🚨 **掃きが止まると「いま買える」が黙って0になる。**
    # 2026-08-31、輸出レーンに鮮度の門を入れた——直近の掃きに居らん玉は
    # 落とす形や。せやから**掃きそのものが止まった日は「玉が無い日」に見える**。
    # 止まっとるのと出物が無いのは別の話やから、掃きの時刻を画面に出す
    add("fleet 買い張り(1時間おき)", SOUBA / "data/fleet/buy_targets.csv",
        "ここが古いと「いま買える」が0に見える", 周期h=1, 土台=True)
    add("fleet 掃きの点呼", SOUBA / "data/fleet/buy_sweeps.csv",
        "機種ごとに引けたかの記録。無いと終了判定が時間頼みになる", 周期h=1, 土台=True)
    return pd.DataFrame(rows)


def stalled(fresh: pd.DataFrame | None = None) -> pd.DataFrame:
    """止まっとる源だけ。盤の頭に赤を出すため——9枚目のタブに埋めたら見ん。

    土台=True の源に絞る。土台やない源(fa朝リスト等)が古いのは
    盤の判断を壊さんので、赤にするとオオカミ少年になる。
    """
    f = fresh if fresh is not None else freshness()
    if f.empty or "状態" not in f.columns:
        return pd.DataFrame()
    bad = f[f["状態"] != "生存"]
    if "土台" in bad.columns:
        bad = bad[bad["土台"].astype(str).str.lower().isin(["true", "1"])]
    return bad



def _latest_morning() -> Path | None:
    d = FA / "data" / "morning"
    if not d.exists():
        return None
    files = sorted(d.glob("20*.md"))
    return files[-1] if files else None


def fa_morning() -> tuple[str, pd.DataFrame]:
    """fa-souba の朝リスト(md表)をDataFrameで返す。(日付, df)"""
    if CLOUD:
        return snap_meta().get("fa朝リスト", ""), snap("fa_morning")
    p = _latest_morning()
    if not p:
        return "", pd.DataFrame()
    lines = p.read_text(encoding="utf-8").splitlines()
    rows = []
    for ln in lines:
        if not ln.startswith("|") or set(ln) <= set("|- "):
            continue
        cells = [c.strip().strip("*") for c in ln.strip("|").split("|")]
        rows.append(cells)
    if len(rows) < 2:
        return p.stem, pd.DataFrame()
    df = pd.DataFrame(rows[1:], columns=rows[0])
    return p.stem, df
