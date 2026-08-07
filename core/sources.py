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
    """その等級を作った判定器。画面に出して読み手が割り引けるようにする。"""
    if CLOUD:
        return snap_meta().get("判定器", {}).get(niche, "不明")
    p = verified_path(niche)
    if p is None:
        return "未検品"
    return "LLM" if "_llm" in p.name else "regex(生存側の精度が低い)"


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


def freshness() -> pd.DataFrame:
    """各データ源の最終更新。工場が止まっとるのを画面で気づけるように。"""
    if CLOUD:
        return snap("freshness")
    rows = []

    def add(name, path, note=""):
        p = Path(path)
        rows.append({
            "データ源": name,
            "パス": str(p),
            "最終更新": (pd.Timestamp(p.stat().st_mtime, unit="s", tz="UTC")
                         .tz_convert("Asia/Tokyo").strftime("%Y-%m-%d %H:%M")
                         if p.exists() else "—"),
            "状態": "生存" if p.exists() else "欠損",
            "備考": note,
        })

    for key, cfg in NICHES.items():
        add(f"{cfg['label']}・工場台帳", cfg["signals"], cfg["channel"])
        vp = verified_path(key)
        add(f"{cfg['label']}・検品結果", vp or cfg["verified"][0],
            f"判定器: {judge_kind(key)}")
        for c in cfg.get("closed", []):
            add(f"{cfg['label']}・落札180日", c, "流動性と等級の土台")
    snaps = snapshots("camera")
    if snaps:
        add("キタムラ買取スナップ(最新)", snaps[-1][1], f"全{len(snaps)}枚")
    add("fa-souba 朝リスト", _latest_morning() or FA / "data/morning", "ヤフオク→eBay")
    return pd.DataFrame(rows)


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
