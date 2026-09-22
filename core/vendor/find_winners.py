# 自動コピー(原本: souba-league/src/find_winners.py)。直接編集するな。
# -*- coding: utf-8 -*-
"""勝てる玉を **拾う**。撃墜語で殺すんやのうて、勝ち語で選ぶ。

## なぜ要るか
verify_body.py は「欠陥語があるか」で殺す**負のフィルタ**しか持っとらん。
それで残るのは「欠陥が書いてない玉」であって「良品と保証された玉」やない。
2026-08-07の人手検証で、LLM生存20件のうち17件が落ちた内訳がそれを示した——
落ちた理由の多くは「状態が確認できん」(通電のみ・記述ゼロ・代理出品)やった。
**欠陥が無いことと、良品であることは別や。**

一方で生き残った3本を読むと、はっきり共通の署名があった:

    XF56mm     : 動作確認済 / カビ・クモリはありません / 防湿庫 / 美品 / 返品保証 / 初期不良対応
    SAL70200G2 : カビくもりなくクリアー / 元箱
    SEL1224G   : 防湿庫 / 使用頻度は低く

全部「**出品者が状態を積極的に保証しとる**」語や。とくに **返品保証・初期不良対応** は
状態リスクを出品者に戻せる = 逆選択の唯一の解毒剤になる。

## 使い方
    python src/find_winners.py --candidates data/camera/candidates.csv \
                               data/camera/candidates_cheap.csv
    python src/find_winners.py --candidates ... --min-score 3 --min-gross 5000

本文は data/bodies/ にキャッシュするので2回目以降はタダ。
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import verify_body as V  # noqa: E402  判定器と本文取得は借りる

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "bodies"

# 勝ち語と重み。**2026-08-07に人手ラベル44件(keep 9/kill 35)で較正済み。**
# 初版の重みは理屈で置いたもので、実測すると2つが**逆向き**やった:
#
#   語          初版  n   keep率  リフト   → 較正後
#   光学クリア     3   7   71%   +61%      4
#   防湿庫        2   3   67%   +50%      3
#   動作確認済     3  15   40%   +30%      3
#   低使用        1   4   50%   +32%      2
#   美品         2   9   22%    +2%      1
#   完品         1   6   17%    -4%      1
#   返品保証      3  17   12%   -14%      0  ←初版で最重要と書いた語
#   専門店       1  15    7%   -21%      0
#
# **効いた語は全部「この個体について具体的に何かを主張しとる語」で、
#   効かんかったのは「店の方針」を述べる語やった。**
# 返品保証は業者の定型文で、しかも保証範囲は「初期不良のみ・ジャンク品は対象外」と
# **一番効いてほしい状態不良をきっちり外しとる**。逆選択の解毒剤やと書いたのは間違い。
WIN_SIGNALS = [
    ("光学クリア", 4, r"(カビ|クモリ|くもり|曇り|ヘイズ|バルサム)[^。]{0,12}"
                      r"(なし|ありません|無し|見られません|確認できません)|"
                      r"クリア[ーな]?|透明度|スッキリ"),
    ("動作確認済", 3, r"動作確認済|実写確認|試写確認|全機能.{0,4}確認|"
                      r"各部.{0,4}(動作|作動).{0,4}確認|正常(に)?(動作|作動)"),
    ("防湿庫", 3, r"防湿庫|ドライボックス|除湿保管"),
    ("低使用", 2, r"使用頻度.{0,4}(低|少)|ショット数.{0,6}(少|[1-9]\d{0,3}枚)|"
                  r"数回(のみ)?(使用|しか)"),
    ("美品", 1, r"超美品|極上|美品|新品同様|未使用に近い"),
    ("完品", 1, r"元箱|付属品.{0,4}(完備|揃|全て)|完品|フルセット"),
    # 重み0。消さずに残すのは、**実測で効かんかったという事実を持っとくため**。
    ("返品保証", 0, r"返品保証|初期不良.{0,6}(対応|返品|返金|保証)|返品可|"
                    r"返品[・、]?交換.{0,4}(可|承)|保証期間|動作保証"),
    ("専門店", 0, r"当店|弊社|専門店|カメラ店|質屋|古物商|真贋"),
]
# 長い本文 = 業者の定型文が厚い = 玉の質はバラバラ。実測で **1800字以上は keep率 0%(0/11)**。
# 🚨🚨 **「閾値4で精度70%」は前向きに持たんかった(2026-09-22)。**
#
# 較正の44件を**同じ道具で採点し直したら 57/70/75/100% が丸ごと再現する**ので、
# 道具も重みも動いとらん。動いたんは**ラベルを貼る人**やった:
#
#     較正の44件から16件を選んで**盲検で貼り直した**ら、一致 13/16。
#     食いちごうた3件は**3件とも keep→kill で、逆向きはゼロ**。
#     (ひび割れ有りやが動作良好 / レンズヒーターで溶けた / 前玉に傷あり)
#
# ラベル付けを**片側に揃えて**測り直した表がこれや:
#
#   閾値 | in-sample(8/07のラベル) | in-sample(同じ人) | out-of-sample(同じ人)
#    3  |        8/14 = 57%       |   5/14 = 36%     |    4/16 = 25%
#    4  |        7/10 = **70%**   |   4/10 = 40%     |    3/13 = **23%**
#    5  |         6/8 = 75%       |    3/8 = 38%     |     3/6 = 50%
#    7  |         4/4 = 100%      |    2/4 = 50%     |     3/4 = 75%
#
# **規則が腐ったんやない。最初から 70% ではなかった。**
# 同じラベル付けどうしで in 4/10 vs out 3/13 を検定すると p=0.65 で差が無い。
# 最初に「前向きで70%→23%に落ちた(p=0.040)」と書きかけたが、あれは
# **別の人が貼ったラベルどうしを比べとった**——時点の比較やのうて人の比較や。
#
# ## 前向きで効くんは7点だけ
# holdout(終了日が 8/07 より後・較正に入っとらん)の **4点以上13件を全数**
# 盲検で貼って、3点以下17件を無作為に貼った:
#
#     閾値4: 3/13 = 23%  vs 素の 2/17 = 12%  → p=0.628  ← **素と区別が付かん**
#     閾値5: 3/6  = 50%  vs 素の 12%         → p=0.089
#     閾値7: 3/4  = 75%  vs 素の 12%         → **p=0.028**
#
# 拾う数は 13→4 に減るが、**当たりの本数は3本で同じ**で無駄買いが 10→1 になる。
# せやから既定を **4点 → 7点** に上げた。
#
# ## 4〜6点が落ちる形(全部同じ形やった)
# **勝ち語は「ひとつの欠陥を否定した文」に当たる。その本文の別のところに
#   失格の欠陥が書いてあっても、こっちは見とらん。**
#
#     「クモリ・カビ・キズは見られませんでした」→ 光学クリア4点 / 実は**ボディ認識エラー**
#     「カビ・曇り・バルサム切れなどはありません」→ 4点 / 実は**動作確認できておりません**
#     「レンズ内のカビは見られませんし」→ 4点 / 実は**鏡筒の歪みで要修理の訳あり品**
#     「撮影に影響するカビや曇りはありません」→ 7点 / 同じ本文に**「カビありますが」**
#
# 正の採点器は負のフィルタが効いとる前提でしか使えん。
BOILERPLATE_CHARS = 1800
BOILERPLATE_PENALTY = 3
WIN_SIGNALS = [(n, w, re.compile(p)) for n, w, p in WIN_SIGNALS]
MAX_SCORE = sum(w for _, w, _ in WIN_SIGNALS)


def body_of(session, auction_id: str, sleep: float) -> str | None:
    """本文をキャッシュ越しに取る。二度と同じ玉を取りに行かん。"""
    CACHE.mkdir(parents=True, exist_ok=True)
    p = CACHE / f"{auction_id}.txt"
    if p.exists():
        # キャッシュは生ページ。判定前に必ず本文だけ切り出す
        # (関連商品欄の他人の出品を勝ち語/殺し語として拾わんため)
        return V.clean_body(p.read_text(encoding="utf-8")) or None
    b = V.fetch_body(session, auction_id)   # 既に clean 済みで返る
    p.write_text(b or "", encoding="utf-8")
    time.sleep(sleep)
    return b


def score(body: str) -> tuple[int, list[str]]:
    if not body:
        return 0, []
    got, pts = [], 0
    for name, w, pat in WIN_SIGNALS:
        if pat.search(body):
            got.append(name)
            pts += w
    if len(body) >= BOILERPLATE_CHARS:
        pts -= BOILERPLATE_PENALTY
        got.append(f"定型文長い(-{BOILERPLATE_PENALTY})")
    return pts, got


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidates", nargs="+", required=True)
    ap.add_argument("--out", default="data/camera/winners.csv")
    ap.add_argument("--min-score", type=int, default=7,
                    help="**7点**。前向き30件の盲検で、4点は素の当たり率と区別が付かんかった"
                         "(23%% vs 12%%, p=0.63)。7点だけが素を超える(75%% vs 12%%, p=0.028)")
    ap.add_argument("--min-gross", type=int, default=3000)
    ap.add_argument("--sleep", type=float, default=2.0)
    ap.add_argument("--escalate", type=int, default=3,
                    help="勝ち語がこの点以上なら、正規表現のkillをLLMに再審させる")
    args = ap.parse_args()

    env = V._load_env()
    providers = [(n, env[V.PROVIDERS[n]["env"]]) for n in V.PROVIDER_ORDER
                 if env.get(V.PROVIDERS[n]["env"])]
    n_saved = 0

    rows = []
    for p in args.candidates:
        with open(ROOT / p, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                r["_src"] = Path(p).stem
                rows.append(r)
    print(f"候補 {len(rows)} 件を勝ち語で採点する")

    session = requests.Session()
    session.headers["User-Agent"] = V.UA
    s = session
    out = []
    for i, r in enumerate(rows, 1):
        b = body_of(s, r["auction_id"], args.sleep)
        pts, got = score(b)
        # 欠陥語があるものは勝ち語があっても採らん(負のフィルタは残す)
        verdict, hit = V.judge(b) if b else ("unknown", "取得不能")
        # **勝ち語が濃い玉を正規表現に殺させん。** ここがこの道具の肝や。
        # 実例: XF56mm は勝ち語14点(全データ最高)やのに、免責の定型文
        # 「保証対象外…カビ、くもり」を拾われて regex に撃墜されとった。
        # 人手で生存確定させた玉やのに、パイプラインが自分で殺しとった。
        # 免責と実欠陥の区別はLLMの唯一の得意分野やから、そこだけ呼ぶ。
        if verdict == "kill" and pts >= args.escalate and providers:
            snips = V.defect_snippets(b)
            for name, key in list(providers):
                lv, lh = V.judge_llm(session, b, key, snippets=snips,
                                     provider=name)
                if lv in ("keep", "kill"):
                    if lv == "keep":
                        n_saved += 1
                        hit = f"(LLMが撤回) {lh}"[:120]
                    else:
                        hit = lh
                    verdict = lv
                    break
                if lv == "exhausted":
                    providers.remove((name, key))
        # タイトルで自白しとる玉は本文がどれだけ良うても採らん。
        # 実例:【不具合有 説明よくお読みください】が勝ち語6点で通っとった
        tl = r.get("title") or ""
        import spread_camera as SC
        if SC.JUNK_RE.search(tl) or SC.PARTS_RE.search(tl):
            verdict, hit = "kill", "タイトルで自白"
        r["win_score"] = pts
        r["win_signals"] = "|".join(got)
        r["defect"] = "" if verdict == "keep" else hit
        r["verdict"] = verdict
        out.append(r)
        if i % 25 == 0:
            print(f"  {i}/{len(rows)}", flush=True)

    for r in out:
        r["gross_hc"] = int(float(r.get("gross_hc") or 0))
    winners = [r for r in out
               if r["win_score"] >= args.min_score
               and r["verdict"] == "keep"
               and r["gross_hc"] >= args.min_gross]
    winners.sort(key=lambda r: (-r["win_score"], -r["gross_hc"]))

    dest = ROOT / args.out
    dest.parent.mkdir(parents=True, exist_ok=True)
    cols = ["family", "auction_id", "price", "gross_hc", "win_score",
            "win_signals", "title", "_src"]
    with dest.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(winners)

    print(f"\n勝ち語スコア{args.min_score}点以上・欠陥語なし・粗利{args.min_gross:,}円以上"
          f" = **{len(winners)}件**")
    dist = {}
    for r in out:
        dist[r["win_score"]] = dist.get(r["win_score"], 0) + 1
    print("スコア分布:", dict(sorted(dist.items(), reverse=True)))
    print(f"LLMが正規表現のkillを撤回して救った玉: {n_saved}件")
    print(f"合計粗利hc: {sum(r['gross_hc'] for r in winners):,}円")
    print(f"-> {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
