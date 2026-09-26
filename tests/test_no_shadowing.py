# -*- coding: utf-8 -*-
"""**モジュールの関数名を、あとから変数で上書きしとらんか。** python tests/test_no_shadowing.py

2026-09-26。公開サイトが落ちとった。原因は `app.py` の1行:

    143行目  def yen(v) -> str:            ← 円の整形関数
    514行目  yen = int(...)                ← **同じ名前に int を代入**
    587行目  f"… {yen(real_yen)}"          ← TypeError: 'int' object is not callable

🚨 **落ちる条件がデータ次第やった。**514行目は

    if not _thin.empty:        # 競り無し/単発の旗が立っとる玉が在る時だけ

の内側や。旗が立たん日は素通りして、**立った日だけサイトが落ちる**。
入れたんは2026-09-22で、4日間そのまま走っとった。

これは3回目の形や:

  * `export_snapshot.py` の 🚨 警告の行だけ cp932 で死ぬ
    → **警告が引き金になって、警告を運ぶ道が壊れる**
  * `claim.py` の check が「他人が持っとる」時だけ 🚨 を印字して落ちる
    → **名乗り板が一番仕事せなあかん瞬間に黙る**
  * これ: **旗が立った時だけサイトが落ちる**

「めったに通らん枝」に印字を足す時は、その枝を1回通してから入れる。
この検定は**通さんでも見つける**静的な門や。
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = ["app.py"] + sorted(str(p.relative_to(ROOT)) for p in
                              (ROOT / "core").glob("*.py"))


def shadowed(path: Path) -> list[tuple[int, str, int]]:
    """(上書きした行, 名前, 元の定義行) を返す。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    top = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            top[node.name] = node.lineno
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for a in node.names:
                imported.add((a.asname or a.name).split(".")[0])
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for t in targets:
            if not isinstance(t, ast.Name):
                continue
            if t.id in top and node.lineno != top[t.id]:
                out.append((node.lineno, t.id, top[t.id]))
            elif t.id in imported:
                out.append((node.lineno, t.id, 0))
    return sorted(out)


def test_関数名もimport名も上書きされとらん():
    bad = []
    for rel in TARGETS:
        p = ROOT / rel
        if not p.exists():
            continue
        for ln, name, orig in shadowed(p):
            where = f"{rel}:{ln}" + (f" (定義は{orig}行目)" if orig else " (import)")
            bad.append(f"{name!r} を上書き — {where}")
    assert not bad, ("モジュール直下の名前を変数で上書きしとる:\n  "
                     + "\n  ".join(bad))
    print(f"OK 上書き: {len(TARGETS)}ファイルに上書きゼロ")


def test_見つける力が在るか():
    """**偽の入力で、門がほんまに鳴るか確かめる。**

    鳴らん門は無いのと同じや。実際に落ちた形をそのまま食わせる。
    """
    import tempfile
    src = ("def yen(v):\n"
           "    return str(v)\n"
           "\n"
           "if True:\n"
           "    yen = int(3)\n"
           "print(yen(1))\n")
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "fake.py"
        p.write_text(src, encoding="utf-8")
        got = shadowed(p)
    assert got and got[0][1] == "yen", got
    print(f"OK 受け入れ試験: 実際に落ちた形({got[0][1]!r} を{got[0][0]}行目で上書き)を捕まえた")


if __name__ == "__main__":
    test_見つける力が在るか()
    test_関数名もimport名も上書きされとらん()
    print("")
    print("検定ぜんぶ通った")
