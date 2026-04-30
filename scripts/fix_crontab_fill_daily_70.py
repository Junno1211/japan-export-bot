#!/usr/bin/env python3
"""
root の crontab を標準入力から読み、次を行って標準出力へ出す（パイプで crontab - に渡す）。
- fill_daily_until_done.sh の 45 → 70
- コメント内の「45 に達する」「※45品」→ 70 表記
- 壊れた行（先頭が '<' で daily 系の断片）を削除
- 0 4 * * * の fill_daily 行が複数あれば最初の 1 本だけ残す
"""
from __future__ import annotations

import re
import sys

FILL_RE = re.compile(
    r"(scripts/fill_daily_until_done\.sh)\s+45(\s|$)",
)


def main() -> int:
    raw = sys.stdin.read()
    lines = raw.splitlines()

    out: list[str] = []
    seen_4am_fill = False

    for line in lines:
        s = line.rstrip("\n")
        stripped = s.strip()

        # 貼り付けミス等の断片行を捨てる
        if stripped.startswith("<") and (
            "l_daily" in stripped
            or "daily_until" in stripped
            or stripped.startswith("<l_")
        ):
            continue

        # 0 4 の fill_daily 重複は 1 本だけ
        if (
            stripped.startswith("0 4 * * *")
            and "fill_daily_until_done.sh" in stripped
        ):
            if seen_4am_fill:
                continue
            seen_4am_fill = True

        s = FILL_RE.sub(r"\g<1> 70\2", s)
        s = s.replace("出品開始件数が 45 に達する", "出品開始件数が 70 に達する")
        s = s.replace("※45品は", "※70品は")
        out.append(s)

    sys.stdout.write("\n".join(out))
    if out and not raw.endswith("\n") and raw:
        pass
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
