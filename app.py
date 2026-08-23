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
from core import audit_gate as AG
from core import buylist as BL
from core import crossmarket as CM
from core import inspect_live as IL
from core import lanes as LN
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

# 紙上台帳(勝敗と紙上純利)は **KPI行から外した**。検品を通しとらん数字で、
# 実際に通した唯一の機会(2026-08-07・6件)は kill 6 / keep 0 やった。
# 3行の言い訳を添えんと誤読される数字を入口の一等地に置く理由が無い。
# 台帳そのものは 📒台帳タブに残しとる(照準の後追いとしては意味がある)。
c1, c2, c3 = st.columns(3)
c1.metric("実弾GOの型番", f"{len(go)} 件",
          help="本文検品を通った実績があり、180日で1万円以上見込める型番")
c2.metric("いま出とる買い", f"{len(buy_live)} 件",
          f"うち🟢 {n_a_alert} 件" if len(buy_live) else None)
c3.metric("期待粗利 / 180日", yen(go["期待粗利180d"].sum()),
          help="実弾GOの型番だけの合計。keep件数 × keep時の粗利中央値")
# **想定純利の逆選別**。この盤の一番大事な規律やから、常時いちばん上に出す。
# 詳しい理屈と実例は core/audit_gate.py に書いた。
st.warning(AG.AUDIT_NOTE, icon="🔍")

tabs = st.tabs(["🛒 いま買える", "🎯 勝てる商品", "🌏 レーン比較", "🔔 アラート",
                "📒 台帳", "🌏 その他チャネル", "💀 墓場", "🏭 稼働"])

# ------------------------------------------------------------------ いま買える
with tabs[0]:
    bl = BL.load()
    if bl.empty:
        st.warning("買い目がまだ無い。ローカルで "
                   "`python src/flea_scan.py` → `python export_snapshot.py` を回す。")
    else:
        live = BL.live(bl)
        c1, c2, c3 = st.columns(3)
        c1.metric("いま買える玉", f"{len(live)} 件")
        c2.metric("純利の合計", yen(live["net"].sum()) if len(live) else "—")
        if "市場" in live:
            for mk, n in live["市場"].value_counts().items():
                st.caption(f"　{mk}: {n}件")
        c3.metric("既に売れた", f"{len(bl) - len(live)} 件",
                  help="走査から数時間で6割が消える。速い者勝ちや")
        st.caption(
            "**Yahoo!フリマの固定価格。出とる値でそのまま買える。** "
            "ヤフオクは競りやから良い玉は中央値まで競り上がって買い線に届かん"
            "(実測: 宣言した上限で勝てたのは決済8件中2件=**25%**)。"
            "フリマは逆で、**相場を知らん人が普通の玉を安く出す**——"
            "人手で60件読んだら上位は「買い替えたため出品」「動作に問題なし」"
            "という職人の出品やった。"
            "**純利2万超は追跡した10件が10件とも売れとる**=市場も安いと認めとる。")
        st.info(
            "**「検品」欄は買ってええかの判定やない。** "
            "本文に欠陥の自白があるかだけを見とる。"
            "実測では keep 62% / kill 61% と**売れ方に差が無かった**——"
            "「売れた=良品」やないからや(部品取りでも売れる)。"
            "**買う前に必ずリンクを開いて写真と本文を読むこと。**", icon="🔍")
        st.caption(
            "**面には順位がある**(2026-08-17に経過時間を揃えて実測): "
            + " / ".join(f"**{k}** {v}" for k, v in CM.MARKET_NOTE.items())
            + "。原因は**同じ型番でも面によって値段が違う**こと"
            "(`HN-65N4` はラクマ¥39,800 vs フリマ¥22,000 = 1.81倍)。"
            "**買い線を割っとっても、他の面にもっと安い玉があったら買われん。**")
        c_a, c_b = st.columns(2)
        only_live = c_a.checkbox("まだ買える玉だけ", value=True)
        only_lo = c_b.checkbox("**全面で最安の玉だけ**", value=True,
                               help="同じ型番が複数の面に出とるとき、"
                                    "実際に買われるのは最安の1つや")
        view = live if only_live else bl
        view = CM.rank(view)
        if only_lo:
            view = CM.only_cheapest(view)
        show = view.rename(columns=BL.COLS)
        cols = [c for c in ["純利", "いま", "相場", "市場", "最安か",
                            "他面との差", "出とる面数", "型番", "商品",
                            "状態", "判定", "売切", "リンク"] if c in show]
        st.dataframe(
            show[cols], hide_index=True, width="stretch", height=560,
            column_config={
                "純利": st.column_config.NumberColumn(format="¥%d"),
                "いま": st.column_config.NumberColumn("いくら", format="¥%d"),
                "相場": st.column_config.NumberColumn("落札中央", format="¥%d"),
                "リンク": st.column_config.LinkColumn("開く", display_text="見る"),
            })
        if "scanned_at" in view:
            st.caption(f"走査時刻: {view['scanned_at'].max()}")

# ------------------------------------------------------------------ 勝てる商品
with tabs[1]:
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
        # ---- いま買える玉(進行中) ----
        lw = W.live_winners()
        st.subheader("🏆 いま買える玉 — 進行中ヤフオク × 勝ち語")
        if lw.empty:
            st.warning(
                "進行中の該当玉なし。ローカルで "
                "`python src/live_winners.py --hours 36`"
                " を回すと更新される。")
        else:
            buyable = lw[lw["勝ち語"] >= 4]
            now_ok = int((lw.get("いま買える", "○") == "○").sum()) if "いま買える" in lw else len(lw)
            st.markdown(f"**質が合格 {len(buyable)}件**(うち今すぐ買える {int((buyable.get('いま買える','○')=='○').sum()) if 'いま買える' in buyable else len(buyable)}件)"
                        f" / 走査した玉 {len(lw)}件・価格圏内 {now_ok}件")
            st.caption(
                "工場は**安さ**で撃つ。ここは**質**で選ぶ。"
                "紙上勝ちを検品したら0/6やった(逆選択= 安く落ちるのは壊れとるから)ので、"
                "価格条件を満たした玉に勝ち語を重ねとる。"
                "勝ち語4点以上が実弾の目安(人手ラベル44件で精度70%)。 "
                "**「監視」は今の価格が上限を超えとる玉。** 質はええので終盤に張る用や。"
                "工場の12時間窓やと『終了間際なのに誰も入札しとらん玉』=逆選択しか"
                "拾えんかったので、7日先まで見て**早いうちに良い玉を見つける**作りに変えた。")
            show = lw if st.checkbox("見送り(3点以下)も出す", value=False) else buyable
            if show.empty:
                st.info("価格は合っとるが質が足りん玉ばかり。下のチェックで中身を見れる。")
            else:
                st.dataframe(
                    show[[c for c in ["段", "いま買える", "勝ち語", "想定純利",
                                      "現在価格", "上限まで", "残り時間h",
                                      "勝ち語の中身", "欠陥", "title", "url"]
                          if c in show]],
                    hide_index=True, width="stretch", height=380,
                    column_config={
                        "想定純利": st.column_config.NumberColumn(format="¥%d"),
                        "現在価格": st.column_config.NumberColumn(format="¥%d"),
                        "上限まで": st.column_config.NumberColumn(
                            "上限まで", format="¥%d",
                            help="max_bid − 現在価格。マイナスなら今は高すぎる=監視"),
                        "残り時間h": st.column_config.NumberColumn("残り", format="%.1fh"),
                        "url": st.column_config.LinkColumn("ヤフオク", display_text="入札"),
                    })
            if not lw.empty and "scanned_at" in lw:
                st.caption(f"走査時刻: {lw['scanned_at'].max()}")
        st.divider()

        # ---- 過去の実績サンプル(買えん) ----
        wins = W.winners()
        with st.expander(f"📚 過去に勝てた玉の実績サンプル({len(wins)}件) — **買えません**"):
            st.caption(
                "**これは落札済みの回顧や。**元は180日ぶんの落札データで、"
                "全部もう終わっとる。載せとるのは「勝つ玉はこういう顔をしとる」の"
                "見本のためだけ。**ここから買えると思わせる作りにしとったのは間違いやった**"
                "(2026-08-08にリンクを開いて発覚)。 "
                "勝ち語の重みは人手ラベル44件で較正済み——効いたのは "
                "光学クリア明記(+61%) / 防湿庫(+50%) / 低使用(+32%) / 動作確認済(+30%)。"
                "**返品保証(−14%)と専門店(−21%)は逆に効かんかった**(どっちも「店の方針」で"
                "玉の質と無関係)。本文1800字以上は業者の定型文が厚く keep率0%で −3点。")
            if not wins.empty:
                st.dataframe(
                    wins[["勝ち語" if "勝ち語" in wins else "win_score",
                          "gross_hc", "price", "win_signals", "family", "title"]],
                    hide_index=True, width="stretch",
                    column_config={
                        "win_score": st.column_config.NumberColumn("勝ち語"),
                        "gross_hc": st.column_config.NumberColumn("粗利(保守)", format="¥%d"),
                        "price": st.column_config.NumberColumn("落札", format="¥%d"),
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

# ------------------------------------------------------------------ レーン比較
with tabs[2]:
    lanes = LN.load()
    if lanes.empty:
        st.info("レーンの計測がまだ無い。ローカルで `python export_snapshot.py` を回して"
                "`data/snapshot/lanes.csv` を作ること。")
    else:
        c1, c2, c3 = st.columns([1, 1, 2])
        ratio = c1.slider("入口が売値のこれ未満なら旗", 0.0, 0.30,
                          LN.MIN_BUY_RATIO, 0.01, format="%.2f",
                          help="仕入と売値の桁が違う行は、引き算の左右がズレとる疑いや")
        dirty = c2.slider("汚染率がこれ以上なら旗", 0.0, 0.50, LN.DIRTY, 0.05)
        kinds = c3.multiselect("見るレーン", ["輸出(相場)", "国内(現物)"],
                               default=["輸出(相場)", "国内(現物)"])

        view = lanes[lanes["種別"].isin(kinds)] if kinds else lanes.iloc[0:0]
        view = LN.flags(view, ratio=ratio, dirty=dirty)
        clean_all = LN.clean(view)
        ok = LN.profitable(clean_all)            # 買い候補 = 旗なし かつ 粗利プラス
        dead = clean_all[~clean_all.index.isin(ok.index)]   # きれいに測れた死
        ng = view[view["要注意"] != ""]

        # 実績は保有玉から。**holdings.csv は .gitignore しとるのでクラウドには無い**
        real, has_real = 0.0, False
        try:
            h = A.holdings_pl(master)
            if h is not None and not h.empty and "純利" in h:
                real = float(pd.to_numeric(h["純利"], errors="coerce").fillna(0).sum())
                has_real = True
        except Exception:
            pass

        m1, m2, m3 = st.columns(3)
        m1.metric("机上 年間粗利(旗なし)", yen(LN.paper_total(ok)))
        m2.metric("机上 年間粗利(全部)", yen(LN.paper_total(view)))
        m3.metric("実績(手元の確定)", yen(real) if has_real else "—")
        if not has_real:
            st.warning(
                f"🧮 **左の数字は全部まだ机上や。** 盤の上では年 {yen(LN.paper_total(ok))} "
                "と出とるが、実際に売れて手に入った金はここに映っとらん"
                "(`data/holdings.csv` は個人の財務情報やから公開せん＝クラウドには無い)。"
                "**紙上で勝った6件を検品したら生存0やった前例がある。**", icon="🧮")
        elif LN.paper_total(ok) > 0:
            st.success(f"実績 {yen(real)} / 机上(旗なし) {yen(LN.paper_total(ok))} = "
                       f"**{real / LN.paper_total(ok) * 100:.1f}%** が現実になった。")

        st.divider()
        st.subheader(f"✅ 旗の立っとらんレーン({len(ok)}本)")
        st.caption("**ここが「今の盤で信用できる買い方・売り方」**や。"
                   "輸出は年台数×粗利、国内は目の前の1個の粗利で並べとる。")
        st.caption("出口の内訳: **eBay US** は実売中央から手数料16%・国際送料・"
                   "関税を引いた後。**ヤフオク再出品**は落札中央 "
                   "×(1−IQRマージン)×(1−落札手数料10%)− 送料¥1,000 で、"
                   "買取店に売る話やのうて**自分が売り手に回る**。")
        st.caption("🛒 は仕入れ側(輸出=ヤフオク検索・国内=その出品そのもの)、"
                   "💴 は出口側(輸出=eBayの実売検索・国内=落札相場)へ飛ぶ。"
                   "検索語は souba-league が測るのに使ったやつと同じやから、"
                   "**盤で見た母集団と飛んだ先が一致する**。")
        CFG = {
            "仕入値": st.column_config.NumberColumn("仕入", format="¥%d"),
            "売値": st.column_config.NumberColumn(format="¥%d"),
            "引かれ": st.column_config.NumberColumn("手数料+送料+関税", format="¥%d"),
            "純利": st.column_config.NumberColumn("1台の純利", format="¥%d"),
            "年間粗利": st.column_config.NumberColumn(format="¥%d"),
            "年台数": st.column_config.NumberColumn(format="%.1f 台"),
            "url": st.column_config.LinkColumn("玉", display_text="開く"),
            "買いに行く": st.column_config.LinkColumn("買いに行く", display_text="🛒"),
            "売りに行く": st.column_config.LinkColumn("売りに行く", display_text="💴"),
        }
        # **一番左に「どこで買ってどこで売るか」を置く。** これが見出しや
        SHOW = ["レーン", "品", "仕入面", "仕入値", "買いに行く",
                "売面", "売値", "売りに行く", "引かれ", "純利",
                "年台数", "年間粗利", "帯"]
        for kind, sort_by in (("輸出(相場)", "年間粗利"), ("国内(現物)", "純利")):
            part = ok[ok["種別"] == kind]
            if part.empty:
                continue
            st.markdown(f"**{kind}** — {len(part)}本")
            cols = [c for c in SHOW if c in part.columns]
            st.dataframe(part.sort_values(sort_by, ascending=False)[cols],
                         hide_index=True, width="stretch", height=300,
                         column_config=CFG)

        if len(dead):
            with st.expander(f"⚰️ きれいに測れた死({len(dead)}本) — "
                             "データは信用できるが、粗利がマイナス"):
                st.caption("**旗なし = きれい、であって儲かるとは限らん。** "
                           "ここは「ちゃんと測った上で駄目やと分かった」レーンや。"
                           "買い候補と混ぜたらあかんが、消したら同じ検討を繰り返す。")
                dcols = [c for c in ["品", "仕入面", "仕入値", "売面", "売値",
                                     "引かれ", "純利", "年台数"] if c in dead.columns]
                st.dataframe(dead.sort_values("純利")[dcols], hide_index=True,
                             width="stretch", column_config=CFG)

        st.subheader(f"⚠️ 監査キュー({len(ng)}本)")
        st.caption("**買いキューやない。** 推定利益の降順は上ほど誤りが濃いので、"
                   "旗が立った行はここに落とす。人が実物を読んでから昇格させる。")
        if len(ng):
            ncols = [c for c in ["レーン", "品", "仕入値", "売値", "純利",
                                 "年台数", "要注意", "買いに行く"] if c in ng.columns]
            st.dataframe(ng.sort_values("純利", ascending=False)[ncols],
                         hide_index=True, width="stretch", height=320,
                         column_config=CFG)

# ------------------------------------------------------------------ アラート
with tabs[3]:
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
with tabs[4]:
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
with tabs[5]:
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
with tabs[6]:
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
with tabs[7]:
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
