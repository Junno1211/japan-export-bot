#!/usr/bin/env python3
"""
GetMyeBaySelling の Active のうち、残在庫が 0 と判定された出品をすべて quantity=1 にする。
メルカリは見ない（二重販売リスクは利用者負担）。誤 OOS の一掃・緊急用。

  cd /opt/export-bot
  ./venv/bin/python3 -u scripts/force_ebay_active_zero_to_qty1.py --dry-run
  ./venv/bin/python3 -u scripts/force_ebay_active_zero_to_qty1.py
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("force_ebay_qty1")

from ebay_updater import get_all_active_list_items, set_quantity  # noqa: E402


# quantity は 0 が有効値のため `int(x.get("quantity") or -1)` は禁止（0 or -1 → -1）。
def _parse_quantity(r: dict, key: str = "quantity") -> int:
    v = r.get(key)
    if v is None:
        return -1
    try:
        return int(v)
    except (TypeError, ValueError):
        return -1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--delay", type=float, default=0.2, help="Revise 間隔秒（既定0.2）")
    ap.add_argument("--limit", type=int, default=0, help="0=無制限")
    args = ap.parse_args()

    rows = get_all_active_list_items()
    seen: set[str] = set()
    zeros: list[dict] = []
    for r in rows:
        eid = (r.get("item_id") or "").strip()
        if not eid or eid in seen:
            continue
        q = _parse_quantity(r)
        if q != 0:
            continue
        seen.add(eid)
        zeros.append(r)

    nlim = args.limit if args.limit and args.limit > 0 else len(zeros)
    work = zeros[:nlim]
    logger.warning(
        "eBay Active 在庫0: 全 %s 件 → 本処理 %s 件（メルカリ未確認で quantity=1）",
        len(zeros),
        len(work),
    )
    ok = 0
    fail = 0
    for i, r in enumerate(work, start=1):
        eid = r["item_id"]
        sku = (r.get("sku") or "")[:50]
        if args.dry_run:
            logger.info("[dry-run] %s/%s %s sku=%s", i, len(work), eid, sku)
            continue
        res = set_quantity(eid, 1)
        if res.get("success"):
            ok += 1
            if i % 50 == 0 or i == len(work):
                logger.info("進捗 %s/%s OK累計=%s", i, len(work), ok)
        else:
            fail += 1
            logger.warning("失敗 %s: %s", eid, res.get("message", "")[:200])
        time.sleep(args.delay)

    logger.info("完了: 成功=%s 失敗=%s dry_run=%s", ok, fail, args.dry_run)
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
