# ============================================================
#  notifier.py  —  Slack通知（任意）
# ============================================================

import logging
import requests
from config import SLACK_WEBHOOK_URL

logger = logging.getLogger(__name__)


def notify_slack(message: str) -> None:
    """Slack Webhookにメッセージを送信（設定なければスキップ）"""
    if not SLACK_WEBHOOK_URL:
        return
    try:
        requests.post(SLACK_WEBHOOK_URL, json={"text": message}, timeout=10)
    except Exception as e:
        logger.warning(f"Slack通知失敗: {e}")
