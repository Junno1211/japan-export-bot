# ============================================================
#  heartbeat.py — Phase 0: 稼働監視（15分 cron 想定）
# ============================================================

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone

import requests

logger = logging.getLogger(__name__)

ROOT = os.path.dirname(os.path.abspath(__file__))


def _read_v3_state() -> dict:
    p = os.path.join(ROOT, "logs", "v3_heartbeat_state.json")
    if not os.path.isfile(p):
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning("v3 state read failed: %s", e)
        return {}


def _check_sheets_ping() -> str:
    try:
        from config import SPREADSHEET_ID, SHEET_NAME
        from sheets_manager import _get_service

        service = _get_service()
        service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=f"{SHEET_NAME}!A1",
        ).execute()
        return "Sheets:OK"
    except Exception as e:
        return f"Sheets:FAIL({type(e).__name__})"


def _check_slack_ping() -> str:
    try:
        from config import SLACK_WEBHOOK_URL

        if not SLACK_WEBHOOK_URL:
            return "Slack:SKIP(no_webhook)"
        requests.post(
            SLACK_WEBHOOK_URL,
            json={"text": f"💓 heartbeat ping {datetime.now(timezone.utc).isoformat()}"},
            timeout=8,
        )
        return "Slack:OK"
    except Exception as e:
        return f"Slack:FAIL({type(e).__name__})"


def _v3_summary_line(st: dict) -> str:
    if not st:
        return "v3_last_run: (no state file)"
    iso = st.get("last_run_iso", "?")
    c = st.get("counts") or {}
    to = c.get("active_timeout", 0)
    dr = c.get("active_dual_reject", 0)
    pe = c.get("process_error", 0)
    return f"v3_last={iso} timeouts={to} dual_reject={dr} proc_err={pe}"


def update_heartbeat(status_text: str) -> None:
    """スプレッドシート「自動出品」タブ H1 にステータスを書き込む。"""
    try:
        from config import AUTO_SHEET_NAME, SPREADSHEET_ID
        from sheets_manager import _get_service

        service = _get_service()
        now_str = time.strftime("%Y-%m-%d %H:%M:%S")
        full_status = f"🕒 Last Heartbeat: {now_str} | {status_text}"

        service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=f"{AUTO_SHEET_NAME}!H1",
            valueInputOption="USER_ENTERED",
            body={"values": [[full_status]]},
        ).execute()
    except Exception as e:
        logger.warning("Heartbeat update failed: %s", e)


def run_phase0_heartbeat() -> None:
    """
    4 項目: v3 最終実行 / 直近カウント / Slack 到達性 / Sheets 読取。
    """
    parts = [_v3_summary_line(_read_v3_state()), _check_slack_ping(), _check_sheets_ping()]
    update_heartbeat(" | ".join(parts))


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    run_phase0_heartbeat()
