# 自動コピー(原本: souba-league/src/spread_camera.py)。直接編集するな。
# -*- coding: utf-8 -*-
"""カメラニッチ: yahoo→kitamura_buy チャネルの擬似回収率。

プレー: ヤフオク落札価格+送料 が キタムラ買取上限(良品=trade_in_price_a)を
GROSS_MIN以上 下回った断面 = 「業者買取を下回って落ちる個体」の全量測定。

出口が買取(手数料ゼロ)のため、凍結スキーマの式のうち
手取り = trade_in_price_a(減額リスクはhaircut感度で併記)、
仕入 = 落札価格 + SHIP_IN。列定義自体は scoring_schema.md v1.0 と同一。
"""
import argparse
import csv
import re
import statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHIP_IN = 1000
GROSS_MIN = 3000
HAIRCUT = 0.9   # 買取「上限」からの減額感度

PARTS_RE = re.compile(
    r"グリップ|バッテリ|充電器|ストラップ|キャップ|フード単|説明書|"
    r"箱のみ|元箱のみ|ケース|アイカップ|フィルター|プレート|リモコン|"
    r"アダプタ|スピードライト|ストロボ|フラッシュ|レンタル|フット|"
    r"メモリ|XQD|CFexpress|SDカード|645|Visoflex|まとめ|テレコン|"
    r"エクステンダー|コンバーター|"
    # 2026-08-07: Xperia の「液晶パネル 互換品 フロントパネル 交換 修理 パーツ」が
    # 本体としてマッチし、盤の実弾GO(¥13,820/180日)に化けとった。
    # キタムラ買取マスタはスマホも持っとるので、修理部品語は必須
    r"液晶パネル|互換品|フロントパネル|修理パーツ|パーツ$|部品|"
    # 2026-08-08: 保護フィルムが本体としてマッチして「純利+22万」に化けとった。
    # 「LUMIX FZ85D 保護 フィルム」のようにタイトルに型番が入るので、
    # 型番マッチだけでは絶対に落とせん。アクセサリ語で殺すしかない。
    r"保護フィルム|液晶保護|保護シール|プロテクター|フィルム|"
    r"イージーカバー|シリコンカバー|液晶カバー|レンズフード|純正フード|"
    r"OverLay|オーバーレイ|貼り付け|"
    # フラッシュ用バッテリーパック等。「SB-5000 SB-910 SB-900用」のように
    # 対応機種を並べる形は本体やない
    r"パワーアシストパック|バッテリーパック|グリップパック|"
    r"用$")
JUNK_RE = re.compile(
    r"ジャンク|訳あり|訳アリ|不動|故障|難あり|カビ|クモリ|くもり|曇り|"
    r"バルサム|キズあり|動作未確認|部品取り|エラー|シャッター不良|"
    # 「動作不良」は 不動 にも 故障 にも当たらんかった。2026-08-07に
    # 工場が「SONY α7III ILCE-7M3 本体（動作不良品）」を発火させて
    # 紙上WON(+¥12,300)に計上しとった穴。タイトルで自白しとるのに通した。
    r"動作不良|作動不良|不具合|通電のみ|通電確認のみ|"
    r"未点検|未清掃|"
    # 「1円[〜~]」だけやと「1円スタート」を取り逃す(2026-08-07にスマホ3件が通過)
    r"現状|1円[〜~]|1円スタート|要確認")
# 対応機種の羅列(アダプター等)は本体モデル名を3つ以上並べる
COMPAT_RE = re.compile(r"D\d{3,4}|Z\s?\d|EOS|α\d|X-T\d|ILCE")
PRICE_FLOOR = 0.35  # 買取価格比の下限(これ未満の「本体」は現実にはジャンク)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--yahoo", default=str(ROOT / "data/camera/yahoo_closed.csv"))
    ap.add_argument("--models", default=str(ROOT / "models/camera.csv"))
    # 帯を変えて別集団を測るとき、既存の採点表/候補を潰さんように分ける
    ap.add_argument("--out-scorecard", default="data/camera/scorecard.csv")
    ap.add_argument("--out-candidates", default="data/camera/candidates.csv")
    args = ap.parse_args()

    fams = {}
    with open(args.models, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            fams[r["family"]] = {
                "match": re.compile(r["match_re"], re.I),
                "exclude": re.compile(r["exclude_re"], re.I)
                           if r["exclude_re"] else None,
                "require": re.compile(r["require_re"], re.I)
                           if r.get("require_re") else None,
                "maker": re.compile(r["maker_re"], re.I)
                         if r.get("maker_re") else None,
                "buyback_a": int(r["buyback_a"]),
            }

    n_seen = 0
    matched = 0
    liq = defaultdict(int)
    candidates = []
    snapshot_date = None
    with open(args.yahoo, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            fam = r["family"]
            if fam not in fams or not r["price"]:
                continue
            n_seen += 1
            title = r["title"] or ""
            spec = fams[fam]
            snapshot_date = snapshot_date or (r["collected_at"] or "")[:10]
            liq[fam] += 1
            if PARTS_RE.search(title) or JUNK_RE.search(title):
                continue
            if not spec["match"].search(title):
                continue
            if spec["exclude"] and spec["exclude"].search(title):
                continue
            if spec.get("require") and not spec["require"].search(title):
                continue
            if spec.get("maker") and not spec["maker"].search(title):
                continue
            if len(COMPAT_RE.findall(title)) >= 3:
                continue
            matched += 1
            price = int(float(r["price"]))
            bb = spec["buyback_a"]
            if price < PRICE_FLOOR * bb:
                continue
            gross = bb - price - SHIP_IN
            if gross >= GROSS_MIN:
                candidates.append({
                    "family": fam, "price": price, "buyback_a": bb,
                    "gross": gross,
                    "gross_hc": round(bb * HAIRCUT) - price - SHIP_IN,
                    "end_time": r["end_time"], "bids": r["bid_count"],
                    "title": title, "auction_id": r["auction_id"],
                })

    if candidates:
        rec = sum(c["buyback_a"] for c in candidates) / sum(
            c["price"] + SHIP_IN for c in candidates)
        hc_pos = [c for c in candidates if c["gross_hc"] >= GROSS_MIN]
        rec_hc = (sum(round(c["buyback_a"] * HAIRCUT) for c in hc_pos) /
                  sum(c["price"] + SHIP_IN for c in hc_pos)) if hc_pos else 0
        med_gross = statistics.median(c["gross"] for c in candidates)
    else:
        rec = rec_hc = med_gross = 0
        hc_pos = []

    row = {
        "niche": "camera", "channel": "yahoo->kitamura_buy",
        "snapshot_date": snapshot_date,
        "n_store": n_seen,          # このチャネルでは=ヤフオク落札の観測数
        "n_candidates": len(candidates),
        "pseudo_recovery_p25": round(rec_hc, 3),   # 保守=買取10%減額後
        "pseudo_recovery_med": round(rec, 3),      # 中央=買取上限どおり
        "sum_gross_p25": sum(c["gross_hc"] for c in hc_pos),
        "median_gross_p25": round(med_gross),
        "liquidity_180d": round(statistics.median(liq.values())) if liq else 0,
        "match_high_ratio": round(matched / max(n_seen, 1), 3),
        "dist_min_n": "-", "effort_days": 1.0,
        "data_risk": "非公式API・買取上限前提(減額10%を保守側に計上)",
    }
    score_csv = ROOT / args.out_scorecard
    with open(score_csv, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(row))
        w.writeheader()
        w.writerow(row)
    cand_csv = ROOT / args.out_candidates
    with open(cand_csv, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(candidates[0]) if candidates
                           else ["family"])
        w.writeheader()
        w.writerows(sorted(candidates, key=lambda c: -c["gross"]))

    for k, v in row.items():
        print(f"{k:22s} {v}")
    print()
    byfam = defaultdict(list)
    for c in candidates:
        byfam[c["family"]].append(c["gross"])
    print(f"{'family':<12}{'liq180':>7}{'cand':>6}{'/月':>5}{'中央粗利':>9}")
    for fam in fams:
        g = sorted(byfam.get(fam, []))
        print(f"{fam:<12}{liq[fam]:>7}{len(g):>6}{len(g)/6:>5.1f}"
              f"{(statistics.median(g) if g else 0):>9.0f}")
    print(f"\n-> {score_csv}\n-> {cand_csv}")


if __name__ == "__main__":
    main()
