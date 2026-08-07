# -*- coding: utf-8 -*-
"""せどり盤 — 勝てる商品と、買い/売りアラートを1枚に。

    streamlit run app.py

思想は README に書いたが、画面の設計だけここに繰り返す:
**トップに出すのは「実弾を入れてええ型番」だけ**。スプレッドが大きい順に並べたら
必ず誤マッチの濃縮標本が上に来る(souba-league の個体検証で実証済み)。
並べる軸は常に「本文検品を通った実績」や。
"""
from __future__ import annotations

import time

import pandas as pd
import streamlit as st

from core import alerts as A
from core import inspect_live as IL
from core import sources as S
from core import watchlist as W

st.set_page_config(page_title="せどり盤", page_icon="🏷️", layout="wide")

# Secrets に PASSWORD がある環境(Streamlit Cloud)でだけ合言葉ゲートを出す。
# ローカルは secrets 未設定なのでそのまま開く(edge-ledger と同じ作り)。
try:
    _pw = st.secrets.get("PASSWORD", "")
except Exception:
    _pw = ""
if _pw:
    if not st.session_state.get("authed"):
        given = st.text_input("合言葉", type="password")
        if given == _pw:
            st.session_state["authed"] = True
            st.rerun()
        elif given:
            st.error("違います")
        st.stop()

CACHE_TTL = 300


@st.cache_data(ttl=CACHE_TTL)
def get_master():
    return W.build_master()


@st.cache_data(ttl=60)
def get_buy(include_dead: bool):
    return A.buy_alerts(get_master(), include_dead)


@st.cache_data(ttl=CACHE_TTL)
def get_sell():
    return A.sell_alerts(get_master())


@st.cache_data(ttl=CACHE_TTL)
def get_moves():
    return A.buyback_moves("camera")


def yen(v) -> str:
    return "—" if pd.isna(v) else f"¥{v:,.0f}"


master = get_master()

st.title("🏷️ せどり盤")
if S.CLOUD:
    _m = S.snap_meta()
    st.info(
        f"**{_m.get('作成', '?')[:16]} の断面**(ローカルで `python export_snapshot.py` "
        "を回して push した時点)。買い/売りアラートはその時刻のもので、"
        "**リアルタイムやない**。進行中個体の検品ボタンだけは今この場でヤフオクを見に行く。")
st.caption(
    "勝てる型番と、いま出とる買い/売りアラート。"
    "**等級は本文検品(実物ページの説明文)を通った実績だけで付ける** — "
    "スプレッドの大きさは勝てる証拠にならん(候補の85〜89%が誤マッチという実測)。"
)

# ------------------------------------------------------------------ 上段の数字
go = W.survivors(master)
buy_live = get_buy(False)
n_a_alert = int((buy_live["等級"] == "A").sum()) if not buy_live.empty else 0
sig_all = pd.concat([W.load_signals(n) for n in S.NICHES], ignore_index=True)
won = sig_all[sig_all["status"] == "settled_won"] if not sig_all.empty else pd.DataFrame()
lost = sig_all[sig_all["status"] == "settled_lost"] if not sig_all.empty else pd.DataFrame()

c1, c2, c3, c4 = st.columns(4)
c1.metric("実弾GOの型番", f"{len(go)} 件",
          help="本文検品を通った実績があり、180日で1万円以上見込める型番")
c2.metric("いま出とる買い", f"{len(buy_live)} 件",
          f"うち🟢 {n_a_alert} 件" if len(buy_live) else None)
c3.metric("期待粗利 / 180日", yen(go["期待粗利180d"].sum()),
          help="実弾GOの型番だけの合計。keep件数 × keep時の粗利中央値")
c4.metric("紙上台帳", f"{len(won)}勝 {len(lost)}敗",
          yen(won["realized_net"].sum()) if len(won) else None,
          help="工場が max_bid で入札しとったら勝てたか。検品は通しとらん")

tabs = st.tabs(["🎯 勝てる商品", "🔔 アラート", "📒 台帳", "🌏 その他チャネル",
                "💀 墓場", "🏭 稼働"])

# ------------------------------------------------------------------ 勝てる商品
with tabs[0]:
    left, right = st.columns([3, 1])
    with right:
        grades = st.multiselect(
            "等級", list(W.GRADE_LABEL), default=W.DEFAULT_GRADES,
            format_func=lambda g: W.GRADE_LABEL[g])
        niches = st.multiselect("ニッチ", sorted(master["ニッチ"].dropna().unique()),
                                default=sorted(master["ニッチ"].dropna().unique()))
        q = st.text_input("型番で検索", placeholder="例: XF56, Martin, 5D")
    view = master[master["等級"].isin(grades) & master["ニッチ"].isin(niches)]
    if q:
        hay = view["商品"].fillna("") + " " + view["family"].fillna("")
        view = view[hay.str.contains(q, case=False, na=False)]

    with left:
        wins = W.winners()
        st.subheader("🏆 買い物リスト — 勝ち語で拾った玉")
        if wins.empty:
            st.info("`python src/find_winners.py --candidates data/camera/candidates.csv "
                    "data/camera/candidates_cheap.csv` を回すと出る。")
        else:
            tot = wins["gross_hc"].sum()
            st.markdown(
                f"**{len(wins)}件 / 粗利 ¥{tot:,.0f} (180日) = 月 ¥{tot/6:,.0f}**")
            st.caption(
                "**殺す語やのうて勝つ語で選んどる。** 「欠陥が書いてない玉」やのうて"
                "「出品者がこの個体について具体的に述べとる玉」や。  \n"
                "重みは人手ラベル44件で**実測較正済み**——効いたのは "
                "光学クリア明記(+61%) / 防湿庫(+50%) / 低使用(+32%) / 動作確認済(+30%)。"
                "**逆に効かんかったのが返品保証(−14%)と専門店(−21%)**で、どっちも"
                "「店の方針」を述べとるだけやから玉の質と関係なかった"
                "(返品保証は範囲が『初期不良のみ・ジャンク対象外』で、一番効いてほしい"
                "状態不良を外しとる)。本文1800字以上は業者の定型文が厚く keep率0%で −3点。  \n"
                "閾値4点で**精度70%**(較正前は25%)。既知の勝ち3本を全部拾えることも検定済み。"
                "⚠ この精度は較正に使った標本での in-sample。")
            st.dataframe(
                wins[["段", "win_score", "gross_hc", "price", "win_signals",
                      "family", "title", "url"]],
                hide_index=True, width="stretch", height=430,
                column_config={
                    "win_score": st.column_config.NumberColumn("勝ち語"),
                    "gross_hc": st.column_config.NumberColumn("粗利(保守)", format="¥%d"),
                    "price": st.column_config.NumberColumn("落札", format="¥%d"),
                    "url": st.column_config.LinkColumn("ヤフオク", display_text="開く"),
                })
        st.divider()

        judges = {cfg["label"]: S.judge_kind(k) for k, cfg in S.NICHES.items()}
        bad = [f"{lab}({kind})" for lab, kind in judges.items() if "regex" in kind]
        if bad:
            st.warning(
                "**等級の出所に注意** — " + " / ".join(bad) +
                "。regex判定は撃墜の再現率は高いが生存側の精度が低く、"
                "実際に勝てる型番を🔴に落とす(XF56mm・ES35100で実証済み)。"
                "`python src/verify_body.py --candidates data/<niche>/candidates.csv "
                "--out data/<niche>/candidates_llm.csv --llm` を回し直すこと。")
        st.caption("判定器: " + " ／ ".join(f"{k} = {v}" for k, v in judges.items()))
        st.subheader("実弾GO — ここだけ見ればええ")
        if go.empty:
            st.warning("本文検品を通った型番がまだ無い。まず候補CSVに verify_body を通すこと。")
        else:
            for _, r in go.iterrows():
                st.markdown(
                    f"### 🟢 {r['商品']}　`{r['family']}`\n"
                    f"買取 **{yen(r['買取'])}** ／ 上限入札 **{yen(r['上限入札'])}** ／ "
                    f"180日見込み **{yen(r['期待粗利180d'])}**  \n"
                    f"検品 {int(r['生存'])}/{int(r['検品n'])}件通過"
                    f"（生存率 {r['生存率']:.0%}）｜ {r['ニッチ']} ｜ {r['出口']}")
                st.caption(r["根拠"])
                st.divider()

    st.subheader("全型番")
    counts = master["等級"].value_counts()
    st.markdown("　".join(f"{W.GRADE_LABEL[g]} **{counts.get(g, 0)}**"
                          for g in W.GRADE_LABEL))
    st.caption(
        "「流動性180d」= **本体**の落札件数(部品・互換品・別世代は工場と同じフィルタで除外済み)。"
        "生ヒットとの差が大きい型番は、検索は当たるのに玉が無い。"
        "「期待粗利180d」= 検品を通った件数 × その粗利中央値。")
    show = view[["判定", "商品", "family", "ニッチ", "買取", "上限入札",
                 "流動性180d", "生ヒット", "落札中央",
                 "検品n", "生存", "生存率", "期待粗利180d",
                 "シグナル", "紙上勝", "稼働中", "根拠"]].copy()
    st.dataframe(
        show, hide_index=True, width="stretch", height=520,
        column_config={
            "買取": st.column_config.NumberColumn(format="¥%d"),
            "上限入札": st.column_config.NumberColumn("上限入札", format="¥%d"),
            "落札中央": st.column_config.NumberColumn("落札中央", format="¥%d"),
            "流動性180d": st.column_config.NumberColumn("玉/180日"),
            "生存率": st.column_config.NumberColumn(format="%.0f%%"),
            "期待粗利180d": st.column_config.NumberColumn("期待粗利/180日", format="¥%d"),
        })

    with st.expander("検品を通った個体そのもの(勝てた玉の実例)"):
        for niche, cfg in S.NICHES.items():
            k = W.keep_items(niche)
            if k.empty:
                continue
            st.markdown(f"**{cfg['label']}**")
            st.dataframe(
                k[["family", "title", "price", "buyback", "gross_hc", "bids",
                   "end_time", "body_hit"]],
                hide_index=True, width="stretch",
                column_config={
                    "price": st.column_config.NumberColumn("落札", format="¥%d"),
                    "buyback": st.column_config.NumberColumn("買取", format="¥%d"),
                    "gross_hc": st.column_config.NumberColumn("粗利(保守)", format="¥%d"),
                })

# ------------------------------------------------------------------ アラート
with tabs[1]:
    buy_tab, sell_tab = st.tabs(["🟩 買いアラート", "🟥 売りアラート"])

    with buy_tab:
        col_a, col_b = st.columns([3, 1])
        with col_b:
            include_dead = st.checkbox("🔴 死んだ型番も出す", value=False,
                                       help="母集団が腐っとると分かっとる型番。通常は握り潰す")
            use_llm = st.checkbox("検品にLLMを使う", value=True,
                                  help="Groq。生存側の精度が regex より高い実測あり")
        live = get_buy(include_dead)
        with col_a:
            st.caption(
                "工場(souba-league/factory.py)が発火した進行中の個体。"
                "**発火は「タイトルと価格が条件を満たした」だけ**で、状態は見とらん。"
                "検品ボタンで **欠陥語(殺す)と勝ち語(拾う)の両方**を採る。"
                "🏆5点以上=実弾GO ／ 👍3-4点=買える ／ 🤏2点以下=見送り。"
                "勝ち語は「返品保証・光学クリア明記・動作確認済・防湿庫・美品」——"
                "**出品者が状態を積極的に保証しとる語**や。"
                "とくに返品保証は外れても金が戻るから、状態を当てんでも勝てる。")
        if live.empty:
            st.info("いま出とる買いシグナルは無い。")
        else:
            cache = IL.load_cache()
            verdicts = dict(zip(cache["auction_id"], cache["verdict"])) if not cache.empty else {}
            hits = dict(zip(cache["auction_id"], cache["hit"])) if not cache.empty else {}
            wscore = (dict(zip(cache["auction_id"], cache.get("win_score", 0)))
                      if not cache.empty else {})
            wsig = (dict(zip(cache["auction_id"], cache.get("win_signals", "")))
                    if not cache.empty else {})
            VMARK = {"keep": "✅ 検品通過", "kill": "⛔ 検品で撃墜", "unknown": "❔ 判定不能"}

            def win_badge(aid):
                """勝ち語スコア。欠陥が無いことと良品であることは別やから、
                買う判断はこっちで決める。3点以上が実弾の目安。"""
                s = pd.to_numeric(wscore.get(aid), errors="coerce")
                if pd.isna(s):
                    return ""
                s = int(s)
                mark = "🏆" if s >= 5 else ("👍" if s >= 3 else "🤏")
                return f"{mark} 勝ち語 {s}点 ({wsig.get(aid) or '—'})"
            for _, r in live.iterrows():
                aid = r["auction_id"]
                v = verdicts.get(aid)
                head = (f"{r['判定']}　**{r['商品']}**　"
                        f"純利 **{yen(r['想定純利'])}**　"
                        f"現在 {yen(r['現在価格'])} / 上限 {yen(r['max_bid'])}　"
                        f"残 {r['残り時間h']:.1f}h")
                if v:
                    head += f"　→ {VMARK.get(v, v)}"
                    wb = win_badge(aid)
                    if wb:
                        head += f"　{wb}"
                with st.container(border=True):
                    st.markdown(head)
                    st.caption(f"{r['title'][:110]}")
                    cc1, cc2, cc3 = st.columns([1, 1, 4])
                    cc1.link_button("ヤフオクで開く", r["url"])
                    if cc2.button("本文を検品", key=f"insp_{aid}"):
                        with st.spinner("実物ページの説明文を読んどる…"):
                            res = IL.inspect_and_cache(aid, use_llm)
                        st.rerun()
                    if v:
                        wb = win_badge(aid)
                        cc3.markdown(f"**{VMARK.get(v, v)}** — "
                                     f"{hits.get(aid, '') or '欠陥語なし'}"
                                     + (f"　{wb}" if wb else ""))
                    else:
                        cc3.caption(f"未検品 ｜ {r['根拠']}")

    with sell_tab:
        d_old, d_new, hit = get_sell()
        st.caption(
            "買取表の日次差分。**下落は出口の悪化=保有分を急いで出す合図**、"
            "上昇はその型番の裁定窓が開いた合図(上限入札も自動で上がる)。")
        if not d_new:
            st.info("買取スナップショットが2枚以上要る。souba-league の kitamura_dump.py を回すこと。")
        else:
            st.markdown(f"**{d_old} → {d_new}** の差分")
            if hit.empty:
                st.success("監視中の型番に動きは無し。")
            else:
                st.dataframe(
                    hit[["向き", "商品", "family", "判定", "旧", "新", "差額",
                         "変化率", "含み"]],
                    hide_index=True, width="stretch",
                    column_config={
                        "旧": st.column_config.NumberColumn(format="¥%d"),
                        "新": st.column_config.NumberColumn(format="¥%d"),
                        "差額": st.column_config.NumberColumn(format="¥%d"),
                        "変化率": st.column_config.NumberColumn(format="%.1f%%"),
                    })
            _, _, moves = get_moves()
            with st.expander(f"監視外も含めた全変動({len(moves)}件)"):
                st.dataframe(
                    moves[["向き", "商品", "旧", "新", "差額", "変化率"]].head(300),
                    hide_index=True, width="stretch")

        st.divider()
        st.subheader("保有玉")
        h = A.holdings_pl(master)
        if h.empty:
            st.caption("`data/holdings.csv` に family / 商品 / 仕入日 / 仕入値 / 数量 を書けば、"
                       "最新の買取表で毎日評価して売り時を出す。")
        else:
            st.dataframe(h, hide_index=True, width="stretch")

# ------------------------------------------------------------------ 台帳
with tabs[2]:
    st.error(
        "**このROIを成績として読んだらあかん。** 2026-08-07に紙上で勝った6件を"
        "本文検品にかけたら **kill 6 / keep 0**(紙上純利¥73,895 → 検品通過¥0)。"
        "タイトルで自白しとる玉すら混じっとった"
        "(「SONY α7III ILCE-7M3 本体（動作不良品）」が+¥12,300に計上されとった)。  \n"
        "負けるときは**惜敗ゼロ**(カメラは上限を中央+28%超過)。つまり"
        "**勝てた玉は誰も競らんかった玉**や。安く落ちるのは壊れとるからで、"
        "これは教科書どおりの**逆選択**。ここは「max_bidで落札できたか」の的中率であって、"
        "**その玉が売れるかは一切見とらん**。")
    st.caption(
        "工場の紙上決済。「max_bid で入札しとったら勝てたか」を前向きに記帳した台帳や。"
        "**実弾の成績やない**し、勝った玉が良品やったかも見とらん。工場の照準の精度を測る道具。")
    for niche, cfg in S.NICHES.items():
        sig = W.load_signals(niche)
        if sig.empty:
            continue
        w = sig[sig["status"] == "settled_won"]
        l = sig[sig["status"] == "settled_lost"]
        cost = (w["final_price"] + w["ship"]).sum()
        net = w["realized_net"].sum()
        roi = (cost + net) / cost if cost else float("nan")
        st.subheader(f"{cfg['label']} — {cfg['channel']}")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("紙上勝敗", f"{len(w)}勝 {len(l)}敗")
        m2.metric("紙上純利", yen(net))
        m3.metric("紙上ROI", "—" if pd.isna(roi) else f"{roi:.3f}")
        m4.metric("稼働中", f"{int((sig['status'] == 'open').sum())} 件")
        st.dataframe(
            sig[["family", "title", "buyback_a", "max_bid", "last_price",
                 "final_price", "realized_net", "status", "end_time"]]
            .sort_values("end_time", ascending=False),
            hide_index=True, width="stretch", height=280,
            column_config={
                "buyback_a": st.column_config.NumberColumn("買取", format="¥%d"),
                "max_bid": st.column_config.NumberColumn("上限", format="¥%d"),
                "last_price": st.column_config.NumberColumn("最終観測", format="¥%d"),
                "final_price": st.column_config.NumberColumn("終値", format="¥%d"),
                "realized_net": st.column_config.NumberColumn("純利", format="¥%d"),
            })
        st.divider()

# ------------------------------------------------------------------ その他チャネル
with tabs[3]:
    st.subheader("越境 — 実弾GO(手で刻む)")
    st.caption("`data/manual_picks.csv` を編集すれば増える。"
               "生存しとるのは全て**工程のある出口**(委託審査・鑑定)で、"
               "フラット市場の素の出品は死んどる。")
    picks = S.read_csv(S.DATA / "manual_picks.csv")
    if not picks.empty:
        st.dataframe(picks, hide_index=True, width="stretch")

    st.subheader("fa-souba — ヤフオク → eBay(FA部品)")
    date, fa = S.fa_morning()
    if fa.empty:
        st.info("朝リストが見当たらん。fa-souba/run_morning.bat を回すこと。")
    else:
        st.caption(
            f"**{date} の朝リスト**。⚠ ここの差益は **eBay ask(出品額)ベース**で、"
            "sold やない。リールで BIN+109% → sold +18〜27% に潰れた前科があるので、"
            "この列は上限として読む。go/no-go は D2/C 個体の発見可能性割引が握っとる。")
        st.dataframe(fa, hide_index=True, width="stretch", height=520)

# ------------------------------------------------------------------ 墓場
with tabs[4]:
    st.caption("**二度と手を出さんための一覧**。ここに載っとるものを思いついたら、"
               "この行の死因を読んでから動くこと。")
    grave = S.read_csv(S.DATA / "graveyard.csv")
    if not grave.empty:
        st.dataframe(grave, hide_index=True, width="stretch", height=460)
    st.info(
        "**共通の死因**: ①買取窓口は転売マージンのため構造的に市場より下 "
        "②読みやすい市場ほど圧縮済み(トレカが教師) "
        "③出口を良くしても仕入側がパリティなら死ぬ。"
        "生き残るのは「買取マスタ横断アグリゲータが未産業化」かつ"
        "「状態が外から判る」カテゴリだけ。")

# ------------------------------------------------------------------ 稼働
with tabs[5]:
    st.caption("工場が止まっとらんか。ここが古い日付で止まっとったら、"
               "アラートが出んのは「玉が無い」やのうて「見とらん」からや。")
    st.dataframe(S.freshness(), hide_index=True, width="stretch")
    st.markdown(
        "```\n"
        "# カメラ工場を常駐(30分毎)\n"
        "cd C:\\dev\\souba-league && python src/factory.py --loop 30\n\n"
        "# 買取表スナップ(売りアラートの燃料。毎日回す)\n"
        "cd C:\\dev\\souba-league && python src/kitamura_dump.py\n\n"
        "# アラートをDiscordに飛ばす常駐\n"
        "cd C:\\dev\\sedori-board && python watch.py --loop 20\n"
        "```")
    st.caption("Discord webhook は `C:\\dev\\.env` の `FACTORY_WEBHOOK_URL=` を共用する。")
