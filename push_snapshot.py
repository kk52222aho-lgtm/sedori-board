# -*- coding: utf-8 -*-
"""**家で叩いたら、盤を今の断面に入れ替えるやつ。** `run_snapshot.bat` の中身。

## なんで要るか
2026-09-21、盤を3日ぶりに開いたら **89時間前の写真**を出しとった。
`export_snapshot.py` が9/17から回っとらんかったからや。盤はクラウドに
`data/snapshot/` しか持っとらんので、**ここを push せん限り盤は過去のまま**や。

手順は README に書いてあった(export して commit して push)。書いてあっても
3日飛んだんやから、**手順やのうて1個のボタンにする**のが正しい向きや。

## やること(この順番でないとあかん)
1. **先に pull。** クラウド側の直しが master に入っとると、こっちは遅れとる。
   遅れたまま commit したら push が弾かれて、原因が分からんまま止まる
2. `export_snapshot.py` を回す
3. **鮮度を出す。** ここが一番大事や——export は「souba-league が今持っとる
   もん」を写すだけで、**工場が止まっとったら古い数字をそのまま写す**。
   写した直後に何が死んどるかを名指しせんと、「push したのに🚨のまま」で
   また悩むことになる
4. 変わっとったら commit して push

## やらんこと
**走査・検品(souba-league側)はここでは回さん。** あれは工場の仕事で、
このリポジトリからは触らん(台帳の「収集も採点もせん」の線や)。
工場が古いときは 3. がそう言うから、そっちを回してからもう一回叩く。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SNAP_DIR = "data/snapshot"


def run(args: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=ROOT, text=True, encoding="utf-8",
                          errors="replace", **kw)


def say(msg: str = "") -> None:
    print(msg, flush=True)


def step(n: int, title: str) -> None:
    say(f"\n=== {n}. {title} " + "=" * max(0, 46 - len(title)))


def git(*args: str, capture: bool = True) -> subprocess.CompletedProcess:
    return run(["git", *args],
               stdout=subprocess.PIPE if capture else None,
               stderr=subprocess.STDOUT if capture else None)


def main() -> int:
    say("せどり盤 スナップショット更新")
    say(f"  {ROOT}")

    # --- 0. master に居るか ---------------------------------------------
    branch = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    if branch != "master":
        say(f"\n🚨 いま `{branch}` に居る。**master やないと動かさん。**")
        say("   盤が見とるのは master や。ここで master を引っ張り込んだら"
            "枝が汚れる。\n   git checkout master してからもう一回。")
        return 1

    # --- 1. 先に pull ---------------------------------------------------
    step(1, "先に pull する")
    dirty = git("status", "--porcelain", "--", SNAP_DIR).stdout.strip()
    other = [ln for ln in git("status", "--porcelain").stdout.splitlines()
             if ln[3:] and not ln[3:].startswith(SNAP_DIR)]
    if other:
        say("⚠ snapshot 以外に未コミットの変更がある:")
        for ln in other[:10]:
            say("    " + ln)
        say("  そのまま進む(このスクリプトは data/snapshot しか commit せん)")
    r = git("pull", "--ff-only", "origin", "master")
    say(r.stdout.strip() or "(変化なし)")
    if r.returncode:
        say("\n🚨 pull が通らんかった。**ここで止める。**")
        say("   早送りできん = ローカルとリモートが分かれとる、"
            "か data/snapshot に未コミットの変更がある。")
        if dirty:
            say(f"   data/snapshot に未コミットの変更あり:\n     {dirty}")
            say("   捨ててええなら: git checkout -- data/snapshot")
        return 1

    # --- 2. export ------------------------------------------------------
    step(2, "export_snapshot.py を回す")
    r = run([sys.executable, "export_snapshot.py"])
    if r.returncode:
        say("\n🚨 export が失敗した。**push はせん。**")
        say("   souba-league(C:\\dev\\souba-league)が見えとるか確かめる。")
        return r.returncode

    # --- 3. 鮮度 --------------------------------------------------------
    step(3, "写した中身の鮮度")
    try:
        sys.path.insert(0, str(ROOT))
        from core import sources as S
        bad = S.stalled()
        if bad.empty:
            say("✅ 土台は全部生きとる。盤の数字はそのまま信用してええ。")
        else:
            say("🚨 **写したが、土台のうちこれが止まっとる:**")
            for _, x in bad.iterrows():
                say(f"    {x['データ源']} … {x['経過']}前 ({x['状態']})")
            say("\n   export は souba-league が今持っとるもんを写すだけや。")
            say("   **上のが古い間は、push しても盤は古い数字のままやで。**")
            say("   工場を回してから、もう一回これを叩く。")
    except Exception as exc:                      # noqa: BLE001
        say(f"⚠ 鮮度を読めんかった: {exc}(push は続ける)")

    # --- 4. commit & push -----------------------------------------------
    step(4, "commit して push")
    git("add", "--", SNAP_DIR)
    if not git("diff", "--cached", "--stat").stdout.strip():
        say("変わっとらんので commit せん(工場も止まっとるんちゃうか)。")
        return 0
    say(git("diff", "--cached", "--stat").stdout.strip())
    r = git("commit", "-m", "買い目を更新(自動: export_snapshot → push)")
    say(r.stdout.strip())
    if r.returncode:
        say("🚨 commit が失敗した。")
        return r.returncode
    for i in range(4):                            # 回線が細いとよく落ちる
        r = git("push", "origin", "master")
        say(r.stdout.strip() or "push した")
        if r.returncode == 0:
            break
        wait = 2 ** (i + 1)
        say(f"⚠ push が失敗。{wait}秒待って{i + 2}回目…")
        import time
        time.sleep(wait)
    else:
        say("🚨 push が4回とも通らんかった。回線か認証を見る。")
        return 1

    say("\n✅ 盤を今の断面に入れ替えた。streamlit.app は数分で入れ替わる。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
