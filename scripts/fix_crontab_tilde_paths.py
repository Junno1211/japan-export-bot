#!/usr/bin/env python3
"""
Mac ユーザ crontab を正規化する。
1) ~/Downloads/eBay/海外輸出ボット → 絶対パス（~ 非展開対策）
2) 当該プロジェクト行の && python3 → && /usr/bin/python3（cron の狭い PATH 対策）

再実行しても冪等。
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

HOME = os.path.expanduser("~")
PROJECT = os.path.join(HOME, "Downloads", "eBay", "海外輸出ボット")
TILDE_PREFIX = "~/Downloads/eBay/海外輸出ボット"


def _crontab_list() -> str:
    r = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    if r.returncode != 0:
        if not (r.stdout or "").strip():
            return ""
        print(f"crontab -l 失敗 (exit {r.returncode}): {r.stderr}", file=sys.stderr)
        raise SystemExit(1)
    return r.stdout


def _install_crontab(content: str) -> None:
    fd, name = tempfile.mkstemp(suffix=".crontab", text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        subprocess.run(["crontab", name], check=True)
    finally:
        try:
            os.unlink(name)
        except OSError:
            pass


def main() -> int:
    try:
        orig = _crontab_list()
    except SystemExit as e:
        return int(e.code)

    if not orig.strip():
        print("crontab が空です。変更なし。")
        return 0

    lines = orig.rstrip("\n").split("\n")
    out: list[str] = []
    changed = False
    for line in lines:
        nl = line
        if not nl.startswith("#"):
            if TILDE_PREFIX in nl:
                n2 = nl.replace(TILDE_PREFIX, PROJECT)
                if n2 != nl:
                    changed = True
                nl = n2
            if PROJECT in nl and "&& python3 " in nl and "/usr/bin/python3" not in nl:
                n2 = nl.replace("&& python3 ", "&& /usr/bin/python3 ", 1)
                if n2 != nl:
                    changed = True
                nl = n2
        out.append(nl)

    new_crontab = "\n".join(out) + "\n"
    if not changed:
        print("crontab: 変更なし（既に正規化済み）。")
        return 0

    _install_crontab(new_crontab)
    print("crontab 更新: パス・python コマンドを正規化しました。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
