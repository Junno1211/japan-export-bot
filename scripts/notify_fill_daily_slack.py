#!/usr/bin/env python3
"""fill_daily_until_done の終了時に Slack へ1通送る（成功 / 未達・中断）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests

from config import SLACK_WEBHOOK_URL


def main() -> None:
    argv = sys.argv[1:]
    if not SLACK_WEBHOOK_URL:
        print("SLACK_WEBHOOK_URL 未設定 — スキップ", file=sys.stderr)
        return

    if len(argv) >= 1 and argv[0] == "abort":
        # abort <target> <count> <reason ...>
        if len(argv) < 4:
            print(
                "usage: notify_fill_daily_slack.py abort <target> <count> <reason>",
                file=sys.stderr,
            )
            sys.exit(2)
        target, count, reason = argv[1], argv[2], " ".join(argv[3:])
        msg = (
            f"⚠️ *朝の出品バッチが目標に届かず終了*\n"
            f"• 本日の出品開始件数（GetSellerList）: *{count}* / 目標 *{target}*\n"
            f"• 理由: `{reason}`\n"
            f"• 詳細: `logs/fill_daily_ABORT.txt` / 当日の `logs/fill_daily_loop_*.log`"
        )
        requests.post(SLACK_WEBHOOK_URL, json={"text": msg}, timeout=20)
        return

    # 成功: <target> <count>
    if len(argv) < 2:
        print(
            "usage: notify_fill_daily_slack.py <target> <count>",
            file=sys.stderr,
        )
        print(
            "       notify_fill_daily_slack.py abort <target> <count> <reason>",
            file=sys.stderr,
        )
        sys.exit(2)
    target, count = argv[0], argv[1]
    msg = (
        f"☀️ *朝の出品バッチ完了*（fill_daily / JST 当日カウント）\n"
        f"• 本日の出品開始件数（GetSellerList）: *{count}* / 目標 *{target}*\n"
        f"• ログ: `logs/fill_daily_RESULT.txt` に最終件数を記録済み"
    )
    requests.post(SLACK_WEBHOOK_URL, json={"text": msg}, timeout=20)


if __name__ == "__main__":
    main()
