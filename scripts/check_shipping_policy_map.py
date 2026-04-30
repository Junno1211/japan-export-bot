#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""デプロイ前チェック: config.SHIPPING_POLICY_MAP の欠落・空 ID・非数値を検出する。

同一 Profile ID が複数 bracket に付いている場合は WARNING を出す（前方埋めの継ぎ足しの可能性）。
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from shipping_policy_select import collect_shipping_policy_map_issues  # noqa: E402


def main() -> int:
    msgs = collect_shipping_policy_map_issues()
    err_n = warn_n = 0
    for m in msgs:
        print(m)
        if m.startswith("ERROR:"):
            err_n += 1
        elif m.startswith("WARNING:"):
            warn_n += 1
    if err_n:
        print(f"--- 終了: ERROR {err_n} 件（要修正） WARNING {warn_n} 件 ---", file=sys.stderr)
        return 1
    print(f"--- OK: ERROR 0 件、WARNING {warn_n} 件 ---")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
