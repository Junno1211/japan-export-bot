#!/usr/bin/env python3
"""
段階5（環境切り分け）用: 同一 URL セットに対し HTTP HEAD の結果だけを出す。
VPS / Mac / テザリングなど複数マシンで同じファイルを回し、差分を比較する。

  cd 海外輸出ボット
  cp scripts/mercari_v2_env_urls.example.txt urls.txt
  python3 scripts/mercari_v2_env_compare_head.py urls.txt
  echo "https://jp.mercari.com/item/m..." | python3 scripts/mercari_v2_env_compare_head.py -
  # zsh: 行頭の # をターミナルに貼るとコメントにならず command not found になることがある

ファイル引数を省略した場合、次の順で最初に見つかったファイルを使う:
  ./urls.txt → ./mercari_v2_env_urls.txt → run/mercari_v2_env_urls.txt（リポジトリ直下からの相対）

正本の判定ロジックは mercari_checker.mercari_head_stage1（プロキシは .env の MERCARI_PROXY_*）。
"""
from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _iter_url_lines(fp) -> list[str]:
    return [ln.strip() for ln in fp if ln.strip() and not ln.strip().startswith("#")]


def _resolve_input_path(given: str | None) -> str | None:
    if given is not None:
        return given
    candidates = [
        os.path.join(os.getcwd(), "urls.txt"),
        os.path.join(os.getcwd(), "mercari_v2_env_urls.txt"),
        os.path.join(ROOT, "run", "mercari_v2_env_urls.txt"),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def main() -> int:
    p = argparse.ArgumentParser(description="Mercari item URLs → mercari_head_stage1 (HEAD only)")
    p.add_argument(
        "file",
        nargs="?",
        default=None,
        help="1行1URLのテキスト、または - で標準入力。省略時は ./urls.txt 等を自動探索",
    )
    args = p.parse_args()
    from mercari_checker import mercari_head_stage1

    path = args.file
    if path == "-":
        lines = _iter_url_lines(sys.stdin)
        if not lines:
            print("stdin に URL が1行もありません。", file=sys.stderr)
            return 1
        for url in lines:
            r = mercari_head_stage1(url)
            print(f"{r.get('outcome')}\t{r.get('reason', '')}\t{url}")
        return 0

    path = _resolve_input_path(path)
    if path is None or not os.path.isfile(path):
        want = args.file or "（省略）"
        print(f"not found: {want}", file=sys.stderr)
        print(
            "次のいずれかで用意してください:\n"
            "  cp scripts/mercari_v2_env_urls.example.txt urls.txt\n"
            "  # urls.txt を編集後:\n"
            '  python3 scripts/mercari_v2_env_compare_head.py urls.txt\n'
            "  echo 'https://jp.mercari.com/item/m...' | python3 scripts/mercari_v2_env_compare_head.py -",
            file=sys.stderr,
        )
        return 1
    with open(path, encoding="utf-8") as f:
        lines = _iter_url_lines(f)
    if not lines:
        print(
            f"no URLs in file (comments only?): {path}\n"
            "  実メルカリURLを1行ずつ追記するか、雛形をやり直してください:\n"
            "  cp scripts/mercari_v2_env_urls.example.txt urls.txt",
            file=sys.stderr,
        )
        return 1
    for url in lines:
        r = mercari_head_stage1(url)
        print(f"{r.get('outcome')}\t{r.get('reason', '')}\t{url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
