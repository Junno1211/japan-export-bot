#!/usr/bin/env python3
"""
今回限りワンショット: eBay Active かつ quantity=0 を items.csv の SOLD（eBay ID）で除外し、
残りを set_quantity(1) にする。メルカリは見ない。

必須: --dry-run で確認してから本番。本番時は結果 CSV を logs/ に出力。

  cd /opt/export-bot
  ./venv/bin/python3 -u scripts/oneshot_force_restock_with_sold_exclusion.py --dry-run --limit 10
  ./venv/bin/python3 -u scripts/oneshot_force_restock_with_sold_exclusion.py --verbose --dry-run --limit 10
"""
from __future__ import annotations

import argparse
import csv
import logging
import os
import sys
import time
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("oneshot_force_restock")

from ebay_updater import get_all_active_list_items, set_quantity  # noqa: E402
from sold_tracker import get_sold_ebay_ids  # noqa: E402


def _parse_quantity(r: dict) -> int:
    """quantity が int の 0 のとき `0 or -1` にならないよう解釈する。"""
    v = r.get("quantity")
    if v is None:
        return -1
    try:
        return int(v)
    except (TypeError, ValueError):
        return -1


def _collect_active_zero_qty() -> list[dict]:
    rows = get_all_active_list_items()
    seen: set[str] = set()
    out: list[dict] = []
    for r in rows:
        eid = (r.get("item_id") or "").strip()
        if not eid or eid in seen:
            continue
        q = _parse_quantity(r)
        if q != 0:
            continue
        seen.add(eid)
        out.append(r)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(
        description="eBay Active qty=0 → 1（items.csv SOLD の eBay ID 除外・メルカリなし）",
    )
    ap.add_argument("--dry-run", action="store_true", help="set_quantity しない")
    ap.add_argument("--limit", type=int, default=0, help="本番時の処理上限。dry-run では表示行数の上限にも使う")
    ap.add_argument("--verbose", action="store_true", help="SOLD に該当した eBay ID を列挙")
    ap.add_argument("--delay", type=float, default=0.5, help="Revise 間の待ち秒（既定0.5）")
    args = ap.parse_args()

    sold_ids = get_sold_ebay_ids()
    n_sold_keys = len(sold_ids)
    logger.info("SOLD除外キー件数（items.csv status=SOLD の eBay ID）: %s 件", n_sold_keys)

    if args.verbose and sold_ids:
        sample = sorted(sold_ids)[:80]
        more = len(sold_ids) - len(sample)
        logger.info("SOLD eBay ID 一覧（先頭80件）: %s%s", ", ".join(sample), f" …他{more}件" if more > 0 else "")

    zeros = _collect_active_zero_qty()
    n_zero = len(zeros)
    logger.info("eBay Active かつ quantity=0（重複除去後）: %s 件", n_zero)

    skip_sold: list[str] = []
    eligible: list[dict] = []
    for r in zeros:
        eid = (r.get("item_id") or "").strip()
        if eid in sold_ids:
            skip_sold.append(eid)
        else:
            eligible.append(r)

    logger.info("SOLD除外（在庫0候補のうち）: %s 件", len(skip_sold))
    logger.info("除外後の最終対象（RESTORE 見込み）: %s 件", len(eligible))

    if args.verbose and skip_sold:
        logger.info("在庫0かつ SOLD 除外された ItemID: %s", ", ".join(skip_sold[:200]) + (" …" if len(skip_sold) > 200 else ""))

    disp_limit = args.limit if args.limit and args.limit > 0 else None
    if args.dry_run:
        if disp_limit is None and len(zeros) > 150:
            logger.warning(
                "--limit 未指定のため在庫0全 %s 件を表示します。件数を絞るには --dry-run --limit 10 など。",
                len(zeros),
            )
        logger.info(
            "--- dry-run 表示（%s・GetMyeBaySelling の在庫0順）---",
            f"最大 {disp_limit} 行" if disp_limit else "全行",
        )
        shown = 0
        for r in zeros:
            if disp_limit is not None and shown >= disp_limit:
                break
            eid = (r.get("item_id") or "").strip()
            q_raw = _parse_quantity(r)
            qty = q_raw if q_raw >= 0 else 0
            plan = "SKIP_SOLD" if eid in sold_ids else "RESTORE"
            sku = ((r.get("sku") or "")[:40] + "…") if len((r.get("sku") or "")) > 40 else (r.get("sku") or "")
            logger.info(
                "ItemID=%s qty=%s plan=%s sku=%s",
                eid,
                qty,
                plan,
                sku,
            )
            shown += 1
        if skip_sold and disp_limit is not None and shown > 0:
            head = zeros[:shown]
            n_skip_in_view = sum(
                1 for r in head if (r.get("item_id") or "").strip() in sold_ids
            )
            if n_skip_in_view == 0:
                logger.info(
                    "補足: 表示された %s 行に SKIP_SOLD は含まれません（在庫0の API 順で先頭が RESTORE のみ）。"
                    "SKIP_SOLD の例 ItemID=%s — items.csv で status=SOLD を確認してください。",
                    shown,
                    skip_sold[0],
                )
        logger.info(
            "dry-run サマリ: 表示行=%s / Active在庫0総数=%s / SOLDキー=%s / 0かつSOLD除外=%s / RESTORE見込み=%s",
            shown,
            n_zero,
            n_sold_keys,
            len(skip_sold),
            len(eligible),
        )
        return 0

    work = eligible
    if args.limit and args.limit > 0:
        work = eligible[: args.limit]

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    logdir = os.path.join(ROOT, "logs")
    os.makedirs(logdir, exist_ok=True)
    csv_path = os.path.join(logdir, f"oneshot_force_restock_result_{ts}.csv")

    ok = 0
    fail = 0
    with open(csv_path, "w", encoding="utf-8", newline="") as fp:
        w = csv.writer(fp)
        w.writerow(["ebay_item_id", "result", "message_or_reason"])

        for i, r in enumerate(work, start=1):
            eid = (r.get("item_id") or "").strip()
            res = set_quantity(eid, 1)
            if res.get("success"):
                ok += 1
                w.writerow([eid, "OK", res.get("message", "")])
            else:
                fail += 1
                w.writerow([eid, "FAIL", res.get("message", "")])
            if i % 25 == 0 or i == len(work):
                logger.info("進捗 %s/%s OK=%s FAIL=%s", i, len(work), ok, fail)
            time.sleep(args.delay)

    logger.info(
        "本番完了: 試行=%s 成功=%s 失敗=%s CSV=%s（SOLD除外は事前に %s 件）",
        len(work),
        ok,
        fail,
        csv_path,
        len(skip_sold),
    )
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
