# 自動コピー(原本: souba-league/src/verify_body.py)。直接編集するな。
"""候補の本文検品 — タイトルだけでは落とせん個体を、出品説明の本文で撃墜する。

2026-08-03の個体検証(楽器20件・カメラ20件)で判明したこと:

  * タイトルに不良語が無いのに本文でジャンク・割れ・カビを自白しとる出品が実在する。
    楽器は撃墜16件中9件、カメラは「★動作品★」と題して本文で内部カビを自白した実例あり。
  * yahoo_closed.py の収集列に本文が無いので、spread_*.py のタイトルフィルタでは構造的に届かん。

全件の本文を集める必要は無い。候補は数十本しか出んのやから、
**候補が出てから本文を引いて検品する**二段構えでええ。

    python src/verify_body.py --candidates data/gakki/candidates.csv
    python src/verify_body.py --candidates data/camera/candidates.csv --out data/camera/candidates_clean.csv

出力は入力に body_verdict / body_hit / body_chars を足したCSV。
--drop を付けると撃墜行を落とした版だけを書く。
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
ITEM_URL = "https://aucfree.com/items/{}"

# 本文で撃墜する語。タイトル用(spread_*.py の JUNK_RE)より広く取る——
# 本文は「無い」ことを述べる文脈が少なく、誤検出が起きにくいため。
BODY_NG = [
    ("ジャンク", r"ジャンク"),
    ("難あり", r"難あり|難有|訳あり|訳アリ|訳有|傷有|キズ有"),
    # 「未点検」「未清掃」は 動作未確認 と同じ意味やのに漏れとった。
    # 2026-08-07: 【未点検・未清掃】のSEL18200LEが生存判定で残り、
    # 盤の実弾GO筆頭(¥28,200/180日)に化けとった。買取は正常作動の良品前提や。
    # 2026-08-11: **「動作確認不可」が入っとらんかった。** D850の玉で
    # regexは別語(ジャンク)で撃墜したのに、LLMが「動作確認不可は欠陥の記述やない」と
    # 言うて撤回し、純利+26,545の生存に戻しとった。確認できんかったという申告は
    # 免責やのうて、その個体について分かっとることの全部や。
    # 2026-08-11、53本を人手で読んで分かった: **語形が助詞1つで外れとった。**
    # 「音出し未確認」は拾えるのに「音出し**は**未確認」は外す。
    # 「検品しておりません」は拾えるのに「検品**は行って**おりません」は外す。
    # 出品者の書き方の揺れを1個ずつ足すんやのうて、**助詞と語尾を許す形**にする。
    ("動作未確認",
     # ①「〜(は/も)未確認」。主語は動作・通電・音出し・試奏・検品・点検・機能など
     r"(?:動作|通電|音出し|試奏|検品|点検|撮影|機能|その他[^。]{0,8})"
     r"[はもをのやなど・、\s]{0,4}未確認|"
     # ②「確認して(は行って)おりません/できていません」
     r"確認(?:は|を|も)?(?:行って|でき[てず]?|して)?(?:おりま|いま|ま)せん|"
     r"検品(?:は|を)?(?:行って|して)?(?:おりま|いま)せん|詳細な検品|"
     # ③「通電確認のみ」「起動確認のみ」「短時間の〜のみ確認」= 検証しとらんのと同じ
     r"(?:通電|起動|点灯)(?:確認)?のみ|チェックのみ|短時間の[^。]{0,12}のみ確認|"
     # ④**「未確認」が単独で置かれる形**。主語語が直前に無いから①で拾えん。
     #   「長年保管されていたため、未確認。バッテリーなし。」で純利+34,310が
     #   生存に残っとった(2026-08-11)。句読点や行頭に続く「未確認」を拾う。
     #   「動作確認済」を食わんよう、直前が「確認」やないことだけ確かめる
     r"(?<![確済])未確認|"      # ←句読点を要求しとったせいで「ため未確認」を逃した
     r"未検品|未点検|未清掃|回数不明|ショット数不明|使用時間不明"),
    # 表示系の故障。「液晶が表示されません」で純利+13,947が通っとった
    ("表示・液晶不良",
     r"表示されません|表示されず|表示不良|映りません|点灯しません|"
     r"液晶[^。]{0,8}(?:不良|割れ|欠け)|ドット抜け|"
     r"(?:液晶|ファインダー)[^。]{0,10}不具合"),
    # 光学系の異物。**レンズ内**だけを見る——ファインダー内のチリは
    # 中古ボディでは普通で、写りに出んから殺したらあかん
    ("レンズ内異物", r"レンズ内[^。]{0,10}(?:ホコリ|ほこり|埃|ゴミ|ごみ|チリ|塵)|"
                     r"レンズ[^。]{0,4}(?:ごみ|ゴミ)|光学[^。]{0,8}チリがあります"),
    # 動きの異常。「Zoomから戻すとき異音あり」「MFのみ動作」「ビビリあり」
    ("動作異常", r"異音|ビビリ|びびり|MFのみ|マニュアルのみ|"
                 r"AF[^。]{0,6}(?:効かない|動作しません|不良)|"
                 r"読み込みが[^。]{0,6}(?:しづらい|悪い|できない)|固着|"
                 r"閉まらない|閉じない|開かない|外れない|入らない"),
    # 代理出品・買付代行。**個体を見た人間が出品者やない**
    ("代理出品", r"代理出品|代理での出品|Zenmarket|buying service|"
                 r"依頼を受けて出品|委託を受けて出品"),
    ("不動・故障", r"不動品|故障|通電しない|電源が入らない|動作しません|作動しません"),
    ("部品取り", r"部品取り|パーツ取り"),
    ("割れ・クラック", r"割れ|クラック|ヒビ|ひび"),
    ("カビ・くもり", r"カビ|かび|クモリ|くもり|曇り"),
    ("腐食", r"サビ|錆|腐食"),
    # 管楽器・フルートの外装。2026-08-11に人手で読んだら
    # 「頭部管に小さな凹み」「管体がとても黒く変色」「広い範囲でメッキが剥がれ」
    # 「ひどくメッキが剥がれており見た目がかなりわるい」で純利+27,150が生存しとった。
    # BODY_NG が**カメラの語彙しか持っとらんかった**。楽器の減額要因はこっちや。
    ("外装劣化", r"凹み|[ヘへ][コこ][ミみ]|メッキ[^。]{0,4}剥がれ|めっき[^。]{0,4}剥がれ|"
                 r"ラッカー[^。]{0,4}剥がれ|黒ずみ|硫化|変色して|退色|"
                 r"溶けて(?:い|お)|接着剤[^。]{0,10}固着"),
    # 出品者自身が機種を特定できとらん。**辞書のどの行と比べるべきかが決まらん**
    ("機種不明", r"型番[^。]{0,4}不明|機種[^。]{0,4}不明|[^。]{0,6}と?予測します|"
                 r"と思われます|保証書[^。]{0,10}付属していない|真贋[^。]{0,6}保証|"
                 # 2026-08-15: 「IM-75TM ? IM-95TM?」= 出品者が型番を特定できとらん。
                 # **どの型番の中央値と比べるべきか決まらん**
                 r"[A-Z]{1,4}-?\d{2,4}[A-Z]{0,3}\s*[?？]"),
    ("要修理・要調整", r"要修理|要調整|要オーバーホール|要OH|リペア前提|修理前提"),
    # 修理"跡"は現在の不具合ではないが、買取のオリジナル性評価を直撃する。
    # 実例: ネック折れ修理跡(ヘッド裏側) がタイトルにも「要修理」にも出ず見逃した。
    ("修理歴・折れ", r"修理跡|補修跡|リペア跡|修理歴|補修歴|リペア済|"
                    # **「折れ」は広すぎた。** 「爪折れ」(プラの爪)まで拾って
                    # 製氷機を撃墜しとった。ネック折れ・シャフト折れみたいな
                    # **本体の骨が折れとる**形だけに絞る
                    r"(?<!爪)(?<!ツメ)(?<!ピン)折れ(?!線|曲|り目)"),
    ("改造・非純正", r"改造|非純正|リフィニッシュ|リフィニッシュ済|社外品に交換"),
    # 「欠品」単独は出品者のテンプレ免責(「欠品につきましては全てを告知できない
    # 場合がございます」)に頻出して誤除外を生む。断定形だけを拾う。
    ("欠品", r"欠品(あり|有|して|:|:)|付属しません|付属品はありません|欠損|"
    # 「〇〇がありません」形。**「傷がありません」を食わんよう部品名を明示する**
    r"(?:ノブ|つまみ|キャップ|フタ|蓋|ストラップ|バッテリー|電池|充電器|"
    r"説明書|取説|元箱|リモコン|アダプタ|マウスピース|リード|ネジ|ビス|"
    r"アイカップ|フード|レンズキャップ|ケーブル)(?:が|は)?(?:あり|付いており)ませ"),
    # ノークレーム・ノーリターンは中古出品の常套句で欠陥情報を持たん。
    # カメラの人手検証(2026-08-03)で、生存3件を3件ともこれで誤除外した。外す。
    # 無在庫・併売の転売出品。**個体が特定できん**ので買取の前提が崩れる。
    # 2026-08-08に実測: GF35-70 が「動作確認済|美品|専門店」で勝ち語4点を取ったが、
    # 本文は「画像の商品はサンプル画像です。実際に届く商品と異なります」
    # 「他モールとの併売品」「海外在庫:2週間程度でお届け」+ AmazonのASIN。
    # 状態語は全部この業者のテンプレで、個体の話やない。
    # 🚨 2026-08-19、**併売 ≠ 無在庫**やと分かって「併売|他モール|在庫確認」を外した。
    # 業務用ビデオの撃墜9件を人手で読んだら、こういう玉が2本落ちとった:
    #   「通電時間 **2655h** Ver.4.21 …**専門店による動作チェック済み**です。
    #     …当商品は、**他モールとの併売**となっております。」
    # **通電時間という個体固有の数値**を書ける時点で実在庫や。実店舗が多重出品しとる
    # だけで、個体は特定できとる。本物の無在庫(#9)は
    #   「**画像の商品はサンプル画像です。実際に届く商品と異なります**」+ AmazonのASIN
    # と書く。**判別点はサンプル画像・在庫の素性であって、併売の有無やない。**
    # 2026-08-08 の GF35-70 は「サンプル画像」も「海外在庫」も持っとったので今も死ぬ。
    # (併売そのものは「買う前に売れてまうかも」いう約定リスクで、状態の欠陥やない)
    ("無在庫", r"サンプル画像|実際に届く商品と異な|"
               r"受注後に|入荷の度に異なり|お届けまで\s*\d+\s*[〜~-]|"
               r"海外在庫|取り寄せ|お取り寄せ|メーカー直送"),
    ("引取限定", r"引取限定|引取り限定|引き取り限定|引取品限定|店頭引取|直接引取|配送不可|発送不可"),
]
BODY_NG = [(name, re.compile(pat)) for name, pat in BODY_NG]

# **LLMに撤回させん category。**
# LLMを噛ませる理由は「この個体はカビがある」と「カビは保証対象外」の区別で、
# それは**状態を述べる語**にだけ要る区別や。下の6つは状態やのうて
# **等級・素性・物流の宣言**やから、免責定型として読みようがない:
#   ジャンク/部品取り = 出品者が付けた等級そのもの
#   動作未確認/不動・故障 = 検証状態の申告
#   無在庫 = そもそも個体が特定できん
#   引取限定 = 送れんので買えん
# 2026-08-11の実測: LLMは「ジャンク扱いという分類のみ」「動作確認不可は
# 欠陥の記述ではなく」と書いて撤回しとった。**分類そのものが判定材料や。**
NO_OVERTURN = {"ジャンク", "部品取り", "不動・故障", "動作未確認",
               "無在庫", "引取限定"}

# **後ろ向きの免責ゾーンで消したらあかん category。**
# 2026-08-11、後ろ向きマスクを入れた直後に見つかった見落とし:
#
#   「代理出品になりますので質問など遅れる事がありますのでご了承下さい。」
#     → 文末が「ご了承下さい」やから、文頭の「代理出品」まで消えとった
#
# 一方これは消して正しい:
#   「難あり品やジャンク品の返品はご容赦ください。」  ← 返品ポリシーの話
#
# 区別は**その語について定型文が存在するか**や。
# 「ジャンク品の返品は〜」は日常的に書かれるが、「代理出品の返品は〜」は無い。
# 取引の形を述べる3つは、文末が免責でも事実そのものやから残す。
STRUCTURAL = {"代理出品", "無在庫", "引取限定"}

# 免責・注意書きのゾーン。ここに並ぶ欠陥語は「この個体にある」やのうて
# 「保証しません」の列挙。実例(XF56mm): 「以下の事項は保証対象外となります。
# ・微細な傷、ゴミやカビ、くもり、サビ、埃、変色、経年劣化など。」
# **マーカーには向きがある。** 2026-08-11に人手で53本読んで分かった:
#
#   「…ご了承ください。 本商品は **ジャンク品**として1円スタートにて出品いたします。」
#   「…ご了承ください。 本商品は **動作未確認**の為、1円スタートにて出品いたします。」
#
# どっちも本文で自白しとるのに素通りしとった。原因は
# 「ご了承ください」から**後ろ120字**を盲点にしとったこと。
# 出品者は「ご了承ください」を文の終わりに何度も書くから、その直後に
# 本当の欠陥を書かれると全部消える。**免責の中身は「ご了承ください」の前にある。**
#
#   前向き(この後に免責の列挙が来る): 以下の事項/下記の事項/保証対象外/免責
#   後ろ向き(ここで免責の文が終わる):   ご了承ください/ご容赦ください/お控えください
#
# 前向きは今までどおり後ろを塞ぐ。後ろ向きは**その文の頭まで遡って**塞ぐ。
FORWARD_RE = re.compile(
    # 2026-08-19、業務用ビデオの撃墜9件を人手で読んだら**4件が誤爆**やった。
    # 主犯がこれ:
    #   「★**以下のもの**は初期不良の**対象外**ですのでご注意ください。
    #     ・通常使用による、チリやゴミ、**カビ、くもり、サビ**、磨耗、劣化など。」
    # 「以下の**事項**」は持っとったが「以下の**もの**」が抜けとって、前向きマスクが
    # 張られず直後の列挙を実在の欠陥として拾った。**同じ意味の言い換えを全部並べる。**
    r"以下のもの|下記のもの|以下の商品|以下の点|下記の点|初期不良の対象外|"
    r"保証対象外|保証の対象外|免責|以下の事項|下記の事項|"
    r"対象外となります|返品はお受けできません|返品・返金は")
CLOSING_RE = re.compile(
    r"ご了承ください|ご了承下さい|ご容赦ください|ご容赦下さい|"
    r"ご理解ください|ご理解の上|お控えください|お控え下さい|予めご了承|"
    # 「付属品・ジャンク品・動作未確認品は**対象外です**」= 返品規定の文や。
    # 2026-08-11、進行中の玉で「ジャンク」を誤検出しとった(実際の欠陥は別の文にあった)
    r"対象外です|対象外となります|は対象外|対象外とさせて|"
    # 2026-08-15、フリマ候補の追跡で分かった:
    #   「中古品なのでキズ、錆び、塗装剥げ、ステッカー剥げ**等あるので**、
    #    完璧を求める方は入札をお控えください」
    # これは**個体の状態やのうて一般的な注意書き**や。「〜等ある」「〜等ございます」
    # という**列挙の締め**が免責の合図になる。前も後ろも塞ぐ
    r"等[あご][るざ]|等ございます|等がございます|等あります|などございます")
DISCLAIMER_SPAN = 120  # 前向きマーカーから何字先までを免責ゾーンとみなすか
# **「・」を文の切れ目に入れとったのが失敗やった。** 箇条書きの記号でもあるが、
# 日本語では「付属品・ジャンク品・動作未確認品」みたいな**列挙の中黒**でもある。
# せやから「付属品・ジャンク品…は対象外です」の遡りが中黒で止まって、
# 返品規定の中の「ジャンク」を実在の欠陥として拾っとった(2026-08-11、進行中の玉で発覚)。
# 中黒は外して、代わりに遡り幅を短く切る(長い箇条書きを丸ごと消さんため)。
SENT_END = "。．\n■◆★●"      # 文の切れ目。後ろ向きマーカーはここまで遡る
# 6ケースで振ったら 20〜25字が全部通り、30字以上で
# 「・カビあり ・レンズ内にホコリ ・動作未確認 ですのでご了承ください」の
# **実在の欠陥を並べた箇条書きが丸ごと消えた**。免責の常套句は短い(20字前後)、
# 欠陥の列挙は長い、という差で切れる。
CLOSING_BACK = 25              # 後ろ向きに遡る上限字数

# 明示的な否定。「カビはありません」を欠陥として拾わんため。
# 「カビくもり**なく**クリアー」を欠陥として拾っとった(2026-08-07)。
# 人手で生存確定させた SAL70200G2 がこれで撃墜されとった。連用形の否定を足す。
NEGATION_RE = re.compile(
    r"(は|も)?(あり|御座い|ござい)?ませんが?|なし|無し|な[くき]|無[くき]|"
    r"ありま[せへ]ん|見られません|見当たりません|確認できません|"
    r"きれい|クリア|良好")
# 「〜はありますが、影響しません/気になりません」= 出品者が打ち消しとる
OFFSET_RE = re.compile(
    r"(?:が|けど|けれど|ものの)[^。]{0,30}?"
    r"(?:影響(?:は)?(?:あり|し)ませ|問題(?:は)?(?:あり|ござい)?ませ|"
    r"気になら|支障(?:は)?(?:あり|ござい)?ませ|使用(?:に|には)問題|"
    r"実用(?:に|には)問題|ほぼ気に|目立ちませ)")
NEGATION_SPAN = 16  # 語の直後この字数以内に否定があれば無視
# 「ジャンク品**と記載のある**もの」「難あり/ジャンク品**で出品されている**もの」=
# 品目クラスへの言及であって、この個体の申告やない。返品規定の常套句や。
REFERENCE_RE = re.compile(
    r"[^。]{0,14}?(?:[とで](?:記載|表記|明記|出品|され)|"
    r"扱いの(?:商品|もの)|品?(?:の|は)返品|品?(?:の|は)?ご返品)")
# 量を限定する語。単独では見逃さん——USABLE_RE と両方揃って初めて効かせる
MINOR_RE = re.compile(r"[^。]{0,4}(?:程度|レベル|ほど)")
# 出品者が可用を明言しとる語
USABLE_RE = re.compile(
    r"通常通り|問題なく|問題無く|支障(?:は)?(?:あり|ござい)?ませ|"
    r"使用(?:に|には)問題|ご使用いただけ|実用(?:上|に)問題|撮影(?:に|には)影響")
# 「カビ**や曇りは**ございません」形。欠陥語が列挙の1個目やと、否定が2語先に来る。
# 「や/、/と/・」で始まるときだけ先を見る——**「は行っておりません」まで
# 否定に数えたら、欠陥の申告そのものが消える**(2026-08-11に一度やらかした)。
LIST_NEG_RE = re.compile(
    # ①接続語つきの列挙: 「カビ**や曇りは**ございません」
    r"[や、と・][^。]{0,10}?(?:は|も)?(?:あり|ござい|御座い)?ま[せへ]ん|"
    # ②接続語なしの並び + 連用形否定: 「カビ**くもりなく**クリアー」
    #   短く切る(6字)。長く取ると「異音がしますが動作は問題なく」まで否定に化ける
    r"[^。]{0,6}?(?:な[くき]|無[くき]|なし|無し)")

# 逆に「これがあれば生存側に寄せる」語。撃墜語が無い場合の加点にのみ使う。
BODY_OK = re.compile(
    r"動作確認済|動作確認済み|全体調整済|調整済|オーバーホール済|OH済|"
    r"整備済|美品|目立った傷や汚れ(は)?(あり|あり)ません|防湿庫")

TAG_RE = re.compile(r"<script.*?</script>|<style.*?</style>", re.S)


def fetch_body(session: requests.Session, auction_id: str,
               retries: int = 1, wait: float = 6.0) -> str | None:
    """aucfree のアーカイブから本文テキストを取る。取れんかったら None。

    2026-08-07: sleep 0.7秒で数百件叩いたら一時的に弾かれて、
    241件中219件が unknown(取得不能) になった。aucfree は死んどらん
    (2秒間隔なら200)。一度は粘る。
    """
    r = None
    for attempt in range(retries + 1):
        if attempt:
            time.sleep(wait)
        try:
            r = session.get(ITEM_URL.format(auction_id), timeout=20)
        except requests.RequestException:
            continue
        if r.status_code == 200:
            break
    if r is None or r.status_code != 200:
        return None
    # ↓ 本体は下の clean_body で切り出す
    text = TAG_RE.sub("", r.text)
    text = re.sub(r"<[^>]+>", " ", text)
    return clean_body(re.sub(r"\s+", " ", text))


# ---------------------------------------------------- 本文の切り出し(2026-08-07)
# aucfree のページテキストには **他人の出品**が混ざる。
#   ・上: サイト全体のカテゴリナビ
#   ・下: 「関連商品」「似ているオークション」= 他の落札品のタイトル
# 実測(h1226150687): 全2,949字のうち商品説明は **409字だけ**。
# 残りの2,540字を判定に食わせとったせいで、両方向に汚染しとった——
#   偽keep: 隣の出品の「■美品■…【動作確認済】」を勝ち語として拾う
#   偽kill: 隣の出品の「ジャンク」「難あり」を欠陥として拾う
# 実際 ES35100 は本文に状態記述がゼロなのに「動作確認済|美品」で5点付いとった。
DESC_START = "商品説明"
DESC_END = ("▲ ページトップへ", "関連商品", "似ているオークション",
            "この商品と同じカテゴリ")


def clean_body(text: str) -> str:
    """ナビと関連商品を落として、出品説明の本体だけ返す。"""
    if not text:
        return text
    s = text.find(DESC_START)
    body = text[s + len(DESC_START):] if s >= 0 else text
    ends = [body.find(m) for m in DESC_END]
    ends = [e for e in ends if e > 0]
    if ends:
        body = body[:min(ends)]
    return body.strip() or text


# ---------------------------------------------------------------- LLM 判定
# 正規表現は「この個体に欠陥がある」と「欠陥を保証しません」を区別できん。
# 両者は文字列としてほぼ同じで、区別には意味の理解が要る。
# 2026-08-03の実測: 正規表現は撃墜の再現率は高い(15-16/17)が、
# 生存側の精度が悪い(カメラで3件中2件を誤除外)。生存率が1割の世界では
# 生存側の精度が命やから、ここはLLMに読ませるのが正しい。
LLM_PROMPT = """あなたは中古品の検品担当や。ヤフオクの出品説明を読んで、\
**この個体に実際の欠陥・不具合があるか**を判定してくれ。

最重要の区別:
- 「この個体はカビがあります」→ 欠陥あり
- 「以下は保証対象外です: 傷、カビ、くもり…」→ **免責の定型文であって欠陥やない**
- 「中古品なのでノークレーム・ノーリターンで」→ **常套句であって欠陥やない**
- 「カビはありません」→ 欠陥やない

欠陥とみなすもの: ジャンク/難あり表記、動作不良・未確認、割れ・クラック、\
カビ・くもり、サビ・腐食、要修理・要調整、修理跡・折れの履歴、改造・非純正部品、\
重要付属品の欠品、店頭引取限定(宅配で送れん)。

手順(必ずこの順で考えてくれ):
1. 欠陥を示しそうな文を**原文のまま**抜き出す(最大3つ)。
2. その1文ずつについて、**主語がこの個体か、それとも一般的な免責・注意書きか**を判定する。
   「〜は保証対象外」「〜の場合がございます」「〜はご了承ください」「ノークレーム」は
   **すべて免責であって、この個体の状態を述べたものやない**。
3. 免責を全部除いたあとに、**この個体の実際の欠陥を述べた文が1つでも残るか**で defect を決める。

出品説明:
---
{body}
---

JSONだけで答えてくれ。他は書かんといて。
{{"quotes": [{{"text": "抜き出した原文", "is_disclaimer": true or false}}, ...],
  "defect": true or false, "reasons": ["短い理由", ...], "confidence": 0.0-1.0}}"""

# 抜粋版。正規表現が撃墜語を見つけた箇所だけを渡して、
# 「この個体の欠陥」か「免責の定型文」かだけを裁かせる。本文を丸ごと送らんので
# 1件あたり約1,900→400トークンに落ちる(TPD 10万で52件→250件)。
SNIPPET_PROMPT = """あなたは中古品の検品担当や。ヤフオクの出品説明から、\
欠陥を示しそうな語の周辺だけを抜き出した。各抜粋について\
**この個体に実際の欠陥があると述べとるか**を判定してくれ。

最重要の区別:
- 「この個体はカビがあります」→ 欠陥あり
- 「以下は保証対象外です: 傷、カビ、くもり…」→ **免責の定型文であって欠陥やない**
- 「中古品なのでノークレーム・ノーリターン」→ **常套句であって欠陥やない**
- 「カビはありません」→ 欠陥やない
- 「〜の場合がございます」「〜はご了承ください」→ **注意書きであって欠陥やない**

抜粋(先頭の[]は引っかかった語の種類):
---
{snippets}
---

免責・注意書きを全部除いたあと、**この個体の実際の欠陥を述べた抜粋が
1つでも残るか**で defect を決める。JSONだけで答えてくれ。
{{"defect": true or false, "reasons": ["短い理由", ...]}}"""


def _load_env(path: str = r"C:\dev\.env") -> dict:
    env = {}
    p = Path(path)
    if p.exists():
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


# プロバイダの序列。魚プロジェクト(aichi-fishing-analysis)で確立済みの cascade を
# そのまま借りる: **Cerebras が主・Groq が控え**。無料枠は Cerebras 1M tokens/日 に対し
# Groq は 10万/日 = 10倍差。2026-08-07に Groq だけで回して1日枠を焼いた反省。
PROVIDERS = {
    "cerebras": dict(url="https://api.cerebras.ai/v1/chat/completions",
                     model="gpt-oss-120b", env="CEREBRAS_API_KEY"),
    "groq": dict(url="https://api.groq.com/openai/v1/chat/completions",
                 model="llama-3.3-70b-versatile", env="GROQ_API_KEY"),
}
PROVIDER_ORDER = ["cerebras", "groq"]


def _as_int(v, default=1):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def judge_llm(session: requests.Session, body: str, api_key: str,
              model: str | None = None,
              snippets: list[str] | None = None,
              provider: str = "groq") -> tuple[str, str]:
    """LLMに読ませて (verdict, hit) を返す。失敗したら ('error', 理由)。

    snippets を渡すと抜粋モード(トークンが1/5で済む)。
    """
    if body is None and not snippets:
        return "unknown", "取得不能"
    import json as _json
    cfg = PROVIDERS[provider]
    prompt = (SNIPPET_PROMPT.format(snippets="\n".join(snippets)) if snippets
              else LLM_PROMPT.format(body=body[:2500]))
    try:
        r = session.post(
            cfg["url"],
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": model or cfg["model"], "temperature": 0,
                  "response_format": {"type": "json_object"},
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=60)
        if r.status_code != 200:
            if r.status_code == 429:
                # 日次枠が本当に尽きたか。ヘッダがあればそれが最優先
                low = [h for h in REMAIN_HEADERS
                       if h in r.headers and _as_int(r.headers[h]) <= 0]
                if low or any(m in r.text for m in EXHAUST_MARKS):
                    return "exhausted", f"{provider}: 1日の枠を使い切った"
                return "throttled", f"{provider}: 分/時の制限"
            return "error", f"HTTP{r.status_code}"
        obj = _json.loads(r.json()["choices"][0]["message"]["content"])
    except Exception as exc:  # noqa: BLE001 — 何で落ちても regex に退避したい
        return "error", type(exc).__name__
    if obj.get("defect"):
        return "kill", "|".join(obj.get("reasons") or ["欠陥あり"])[:120]
    return "keep", "|".join(obj.get("reasons") or [])[:120]


# ------------------------------------------------- トークン予算(2026-08-07に実測)
# Groq無料枠の効いとる壁は TPM やのうて **TPD(1日あたり10万トークン)**。
# 実レスポンス: "on tokens per day (TPD): Limit 100000, Used 98040"。
# 本文2,500字を丸ごと送ると1件約1,900トークン → **1日52件で枯れる**。
# 2026-08-07はこれを知らずに390件ぶん叩いて、**枯れたあと黙って正規表現に
# 退避しとった**(退避率 59〜79%)。正規表現は生存側の精度が低いので、
# 退避したぶんは生存を取りこぼしとる = 数字が過少になる。
#
# 対策は3つ。全部入れる:
#  1) **LLMは正規表現が kill と言うたときだけ呼ぶ。** 正規表現の弱点は
#     「免責の定型文を欠陥と読む」= 偽kill であって、偽keepやない。
#     keep はそのまま信じてええから、その分のトークンが丸ごと浮く。
#  2) **本文を丸ごと送らん。** 撃墜語の周辺だけ切り出して送る。判定に要るのは
#     「その語が この個体の欠陥か、免責の列挙か」だけやから、周辺120字あれば足る。
#  3) **TPDで枯れたら黙って退避せず止まる。** --resume で翌日続きから。
SNIPPET_SPAN = 120
MAX_SNIPPETS = 6
# 「待っても回復せん」= **日次**枠の枯渇だけをこう呼ぶ。
# 分・時間単位の 429 は待てば戻るので、これに混ぜたらあかん。
# 2026-08-07にやらかした: "quota"/"daily" まで拾ったせいで、Cerebras の
# 分単位 429 を日次枯渇と誤判定して5件目でプロバイダを捨てとった
# (実際の残枠は tokens 994,960 / requests 2,394 やった)。
EXHAUST_MARKS = ("tokens per day", "per day (TPD)", "requests per day")
# 残枠はヘッダで分かる。文言の推測より確実
REMAIN_HEADERS = ("x-ratelimit-remaining-tokens-day",
                  "x-ratelimit-remaining-requests-day")
RETRY_WAITS = (5, 15, 40)   # 分・時間単位の429はこれで待つ


def defect_snippets(body: str) -> list[str]:
    """撃墜語の周辺だけを切り出す。LLMに送るのはこれだけでええ。"""
    out, seen = [], set()
    for name, pat in BODY_NG:
        for m in pat.finditer(body):
            a = max(0, m.start() - SNIPPET_SPAN)
            b = min(len(body), m.end() + SNIPPET_SPAN)
            key = a // SNIPPET_SPAN
            if key in seen:
                continue
            seen.add(key)
            out.append(f"[{name}] …{body[a:b]}…")
            if len(out) >= MAX_SNIPPETS:
                return out
    return out


def _disclaimer_zones(body: str, closing: bool = True) -> list[tuple[int, int]]:
    """免責ゾーン。前向きマーカーは後ろを、後ろ向きマーカーは**前**を塞ぐ。

    closing=False にすると後ろ向きマーカーを無視する。取引の形を述べる
    category(STRUCTURAL)はこっちで判定する——文末が「ご了承ください」でも
    「代理出品です」は事実やから消したらあかん。
    """
    zones = [(m.start(), m.start() + DISCLAIMER_SPAN)
             for m in FORWARD_RE.finditer(body)]
    if not closing:
        return zones
    for m in CLOSING_RE.finditer(body):
        # その文の頭まで遡る(最大120字)。文をまたいで塞がん
        lo = m.start()
        stop = max(0, lo - CLOSING_BACK)
        while lo > stop and body[lo - 1] not in SENT_END:
            lo -= 1
        zones.append((lo, m.end()))
    return zones


def _is_live_hit(body: str, m: re.Match, zones: list[tuple[int, int]]) -> bool:
    """その一致が本当に「この個体の欠陥」か。免責ゾーン内と否定形は除く。

    否定は**直後に接しとるとは限らん**。2026-08-11に実測:

        「カビや曇りはございません。」  ← カビの直後は「や曇りは…」

    NEGATION_RE.match(直後12字) やと外れて、この個体にカビがある扱いになる。
    **同じ文の中**を探す形にする(。をまたいだら別の話やから見に行かん)。
    """
    i = m.start()
    if any(a <= i < b for a, b in zones):
        return False
    # **「〜はありますが問題ない」形。** 出品者が「あるが影響せん」と説明しとるのに
    # 欠陥ありと判定しとった(2026-08-15、フリマ候補の追跡で発覚):
    #   「凹みは所々ありますが、管が半分以上潰れたような大きな凹みは無く支障ありません」
    #   「ヒビのようなものがありますが撮影時にはほぼ気にならない程度です」
    # どっちも**売れた**。市場は減点しとらん。同じ文の中で「が/けど」のあとに
    # 打ち消しが来るなら、その語では撃墜せん。
    same = body[m.end(): m.end() + 60]
    cut2 = same.find("。")
    if cut2 >= 0:
        same = same[:cut2]
    if OFFSET_RE.search(same):
        return False
    # **品目クラスへの言及は、この個体の申告やない。** 2026-08-19に実測:
    #   「★難あり/ジャンク品**で出品されているもの**は返品不可です」
    #   「**ジャンク品と記載のあるもの**や、説明文に記載のある不備は対応できません」
    # どっちも「そう表示されとる商品は」という条件節で、この玉の話やない。
    # 後ろ向きマスク(CLOSING_BACK=25字)では「対応できません」まで35字あって届かん。
    # **語の直後に「と記載/と表記/で出品/と明記」が来たら参照や**という形で拾う。
    if REFERENCE_RE.match(same):
        return False
    # **「小チリ**程度**で…**通常通りご使用いただけます**」形。**
    # OFFSET_RE は「〜がありますが問題ない」いう**逆接**を要求するので、
    # 逆接を使わず「程度で、〜使えます」と続ける書き方に届かんかった
    # (2026-08-19、撃墜9件の人手読み返しで残った最後の2件がこれ)。
    # **限定語と可用の明言が両方揃ったときだけ**見逃す。片方だけでは落とす——
    # 「小カビ小クモリがあります」(限定語のみ)は今までどおり撃墜する。
    if MINOR_RE.match(same) and USABLE_RE.search(same):
        return False
    tail = body[m.end(): m.end() + NEGATION_SPAN]
    if NEGATION_RE.match(tail):
        return False
    # 列挙の橋渡しだけ許す。「カビ**や曇りは**ございません」は否定やが、
    # 「詳細な検品**は行っており**ません」は否定やのうて欠陥の申告そのものや。
    # tail のどこでも「ません」を探す形にすると後者まで否定に化けるので、
    # **「や・、・と・・」で始まる列挙のときだけ**先を見る。
    return not LIST_NEG_RE.match(tail)


def judge(body: str) -> tuple[str, str]:
    """(verdict, hit) を返す。verdict は kill / keep / unknown。"""
    if body is None:
        return "unknown", "取得不能"
    zones = _disclaimer_zones(body)
    zones_fwd = _disclaimer_zones(body, closing=False)
    hits = []
    for name, pat in BODY_NG:
        z = zones_fwd if name in STRUCTURAL else zones
        if any(_is_live_hit(body, m, z) for m in pat.finditer(body)):
            hits.append(name)
    if hits:
        return "kill", "|".join(hits)
    return "keep", ("良好語あり" if BODY_OK.search(body) else "")


def _load_done(out_path, src_path) -> dict:
    """既存の出力から、正規表現に退避しとらん検品結果だけを引き継ぐ。"""
    p = Path(out_path) if out_path else src_path.with_name(
        src_path.stem + "_verified.csv")
    if not p.exists():
        return {}
    done = {}
    for r in csv.DictReader(p.open(encoding="utf-8-sig")):
        hit = r.get("body_hit") or ""
        # 退避した行と、本文が取れんかった行(unknown)はやり直す対象。
        # aucfree は叩きすぎると一時的に落ちるだけで、翌回は取れることが多い。
        if (not r.get("body_verdict") or "regex退避" in hit
                or r["body_verdict"] == "unknown"):
            continue
        done[r["auction_id"]] = {"body_verdict": r["body_verdict"],
                                 "body_hit": hit,
                                 "body_chars": r.get("body_chars", "")}
    return done


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidates", required=True)
    ap.add_argument("--out", default=None, help="既定は <入力>_verified.csv")
    ap.add_argument("--drop", action="store_true", help="撃墜行を落とした版を書く")
    ap.add_argument("--sleep", type=float, default=0.7)
    ap.add_argument("--limit", type=int, default=0, help="先頭N件だけ(検証用)")
    ap.add_argument("--resume", action="store_true",
                    help="出力CSVに既にある検品結果を再利用する。Groqの1日枠"
                         "(TPD 10万トークン)で途中で止まったとき、翌日これで続ける")
    ap.add_argument("--llm", action="store_true",
                    help="本文の判定をLLM(Groq)にやらせる。免責の定型文と実際の欠陥を"
                         "区別できるので生存側の精度が上がる。失敗時は正規表現に退避")
    ap.add_argument("--llm-sleep", type=float, default=7.0,
                    help="Groq TPM 12k 対策。本文2.5k字≒1.3kトークンで毎分9本が上限"
                         "やから6.7秒が下限。2.5秒やと429だらけになる(実測)")
    args = ap.parse_args()

    env = _load_env()
    providers = []
    if args.llm:
        for name in PROVIDER_ORDER:
            if env.get(PROVIDERS[name]["env"]):
                providers.append((name, env[PROVIDERS[name]["env"]]))
        if not providers:
            print("LLMのキーが C:\\dev\\.env に無い。正規表現で続行する。",
                  file=sys.stderr)
        else:
            print("LLM: " + " → ".join(n for n, _ in providers)
                  + " (枯れたら次へ落ちる)")

    src = Path(args.candidates)
    rows = list(csv.DictReader(src.open(encoding="utf-8-sig")))
    if args.limit:
        rows = rows[: args.limit]
    if not rows:
        print("候補が無い", file=sys.stderr)
        return 1

    session = requests.Session()
    session.headers["User-Agent"] = UA

    n_kill = n_keep = n_unknown = n_fallback = n_llm = n_overturn = 0
    n_locked = 0
    exhausted = False
    done = _load_done(args.out, src) if args.resume else {}
    for i, row in enumerate(rows, 1):
        prev = done.get(row["auction_id"])
        if prev:                            # --resume: 検品済みは触らん
            row.update(prev)
            n_kill += prev["body_verdict"] == "kill"
            n_keep += prev["body_verdict"] == "keep"
            n_unknown += prev["body_verdict"] == "unknown"
            continue
        body = fetch_body(session, row["auction_id"])
        verdict, hit = judge(body)
        # 等級・素性の宣言で撃墜したときは、LLMに諮らんとそのまま確定させる。
        # ここを諮ると「分類のみで具体的な欠陥の記述がない」と言うて撤回してまう。
        locked = verdict == "kill" and (set(hit.split("|")) & NO_OVERTURN)
        if locked:
            hit = f"(確定) {hit}"
            n_locked += 1
        # LLMは正規表現が kill と言うたときだけ呼ぶ。正規表現の弱点は偽killで、
        # keep はそのまま信じてええから、その分のトークンが浮く。
        if providers and body and verdict == "kill" and not locked and not exhausted:
            snips = defect_snippets(body)
            lv, lh = "", ""
            while providers:
                name, key = providers[0]
                for wait in (0,) + RETRY_WAITS:
                    if wait:
                        time.sleep(wait)
                    lv, lh = judge_llm(session, body, key, snippets=snips,
                                       provider=name)
                    if lv != "throttled":
                        break
                if lv == "throttled":       # 粘っても駄目なら次のプロバイダへ
                    print(f"! {name} が詰まっとる。次へ", flush=True)
                    providers.pop(0)
                    continue
                if lv != "exhausted":
                    break
                print(f"! {name} の1日枠が尽きた({i}/{len(rows)}件目)", flush=True)
                providers.pop(0)
            if lv == "exhausted" or not providers:
                exhausted = True
                print(f"! 全プロバイダの枠が尽きた。ここから先は正規表現で続ける。"
                      f"翌日 --resume で続きを。", flush=True)
                hit = f"(regex退避) {hit}"
                n_fallback += 1
            elif lv == "error":
                hit = f"(regex退避) {hit}"
                n_fallback += 1
            else:
                n_llm += 1
                if lv == "keep":
                    n_overturn += 1
                    hit = f"(LLMが撤回: {hit}) {lh}"[:140]
                else:
                    hit = lh
                verdict = lv
            time.sleep(max(0.0, args.llm_sleep - args.sleep))
        elif exhausted and verdict == "kill" and not locked:
            hit = f"(regex退避) {hit}"
            n_fallback += 1
        row["body_verdict"] = verdict
        row["body_hit"] = hit
        row["body_chars"] = len(body) if body else 0
        n_kill += verdict == "kill"
        n_keep += verdict == "keep"
        n_unknown += verdict == "unknown"
        line = f"[{i}/{len(rows)}] {verdict:7s} {hit[:40]:40s} {row.get('title','')[:40]}"
        # Windows コンソールは cp932 で、CJK拡張や中文字が混じると落ちる
        enc = sys.stdout.encoding or "utf-8"
        sys.stdout.buffer.write(line.encode(enc, "replace") + b"\n")
        sys.stdout.flush()
        time.sleep(args.sleep)

    out = Path(args.out) if args.out else src.with_name(src.stem + "_verified.csv")
    keep_rows = [r for r in rows if r["body_verdict"] != "kill"] if args.drop else rows
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(keep_rows)

    print()
    print(f"kill={n_kill}  keep={n_keep}  unknown={n_unknown}  ({len(rows)}件)")
    print(f"うち {n_locked}件は等級・素性の宣言でLLMに諮らず確定")
    if n_llm:
        print(f"LLMが裁いた撃墜候補: {n_llm}件 / うち {n_overturn}件を撤回(=生存に戻した)")
    if n_fallback:
        print(f"! LLMが使えず正規表現に退避: {n_fallback}件 "
              f"({n_fallback / len(rows):.0%})。正規表現は偽killを出すので、"
              f"この分は生存を取りこぼしとる。翌日 --resume で回し直せ")
    print(f"-> {out}")
    if n_unknown:
        print("※ unknown は aucfree のインデックス漏れ。人手で確認するか、撃墜扱いが保守側や。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
