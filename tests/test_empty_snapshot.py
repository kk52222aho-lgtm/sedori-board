# -*- coding: utf-8 -*-
r"""**断面が空の日に、サイトが開くか。** python tests/test_empty_snapshot.py

2026-09-30、公開サイトが落ちた:

    app.py:1063  moves[["向き","商品","旧","新","差額","変化率"]] → KeyError

`moves.csv` が**BOMだけの空ファイル**で、読むと列が0本の枠になる。
買取表に差分が無い日は普通に来る——**「空」は事故やのうて正常な測定結果**や。

## なんで注入して試すか
「空の日」は**めったに来ん枝**や。これで4回目:

  * `export_snapshot.py`  🚨警告の行だけ cp932 で死ぬ
  * `claim.py`            「他人が持っとる」時だけ🚨を印字して落ちる
  * `app.py` の `yen`     旗が立った日だけ TypeError
  * **`moves.csv`**       **買取表に差分が無い日だけ KeyError**

めったに来ん枝は、**来るのを待たずに注入して通す**。
([[insight_idle_daemon_never_tested]]: 建てたら事象が来る前に注入して通す)

## 2つの形を注入する
    列は在るが行が0     ← `dump()` を直した後の正しい形
    列も行も無い(空)    ← 直す前の形。**古い断面を読む日もある**

## 遅い
1断面につき app.py を1回流すんで、全部で数分かかる。commit ごとには
回さん。**断面の作りを触った時と、落ちた後に回す。**
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SNAP = ROOT / "data" / "snapshot"

RUN = (
    "import sys, runpy; sys.path.insert(0, '.')" + chr(10)
    + "from core import sources as S" + chr(10)
    + "assert S.CLOUD, 'CLOUD が立っとらん'" + chr(10)
    + "sys.argv = ['app.py']" + chr(10)
    + "runpy.run_path('app.py', run_name='__main__')" + chr(10)
)


def run_app() -> tuple[int, str]:
    """クラウドと同じ経路で app.py を頭から最後まで流す。

    🚨 **環境変数で立てる。**`app.py` の `_refresh_core()` が起動時に
    core を無条件で貼り直すんで、`S.CLOUD = True` を立てても戻される。
    2026-09-30に、それで門がローカルの経路を試しとったのが分かった。
    """
    env = dict(os.environ, PYTHONIOENCODING="utf-8", SEDORI_FORCE_CLOUD="1")
    r = subprocess.run([sys.executable, "-c", RUN], cwd=ROOT, env=env,
                       text=True, encoding="utf-8", errors="replace",
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       timeout=600)
    return r.returncode, (r.stdout or "")


def test_断面を1つずつ空にしても開く():
    names = sorted(p.stem for p in SNAP.glob("*.csv"))
    assert names, f"断面が無い: {SNAP}"
    base_rc, base_out = run_app()
    assert base_rc == 0, ("素の断面でもう落ちとる:" + chr(10)
                          + chr(10).join(base_out.splitlines()[-12:]))
    print(f"OK 素の断面: app.py が最後まで開いた({len(names)}本の断面)")

    bad = []
    with tempfile.TemporaryDirectory() as d:
        backup = Path(d)
        for n in names:
            src = SNAP / f"{n}.csv"
            shutil.copy(src, backup / f"{n}.csv")
            head = src.read_text(encoding="utf-8-sig").splitlines()[:1]
            for form, text in (("列だけ", (head[0] if head else "") + chr(10)),
                               ("丸ごと空", "")):
                src.write_text(text, encoding="utf-8-sig")
                rc, out = run_app()
                if rc != 0:
                    tail = [x for x in out.splitlines()
                            if "Error" in x or ", in " in x][-3:]
                    bad.append(f"{n}.csv を{form}にしたら落ちる: "
                               + " / ".join(x.strip() for x in tail))
                    print(f"  🚨 {n:<16}{form:<8}落ちる")
                else:
                    print(f"     {n:<16}{form:<8}開く")
            shutil.copy(backup / f"{n}.csv", src)
    assert not bad, ("空の断面で落ちる:" + chr(10) + "  "
                     + (chr(10) + "  ").join(bad))
    print(f"OK 空の注入: {len(names)}本 × 2形 = {len(names) * 2}通り、全部開いた")


if __name__ == "__main__":
    test_断面を1つずつ空にしても開く()
    print("")
    print("検定ぜんぶ通った")
