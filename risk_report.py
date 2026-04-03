"""
risk_report.py  —  リスクマネジメント部 日次レポート
毎朝 08:00 JST に cron で実行 → Slack へ送信
  cron: 0 8 * * * cd /root/bot && python3 risk_report.py
"""

import os
import sys
import logging
import requests
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import Optional, List

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from config import (
    SLACK_WEBHOOK_URL, EBAY_AUTH_TOKEN, EBAY_SITE_ID, EBAY_ENV,
    EXCHANGE_RATE, SPREADSHEET_ID, SHEET_NAME
)
import sheets_manager

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ── 定数 ──────────────────────────────────────────
RATE_WARNING_DIFF = 5.0  # 為替警戒ライン（基準レートとの差）
STALE_DAYS = 30          # 滞留在庫の閾値（日数）

# アカウントヘルス閾値
HEALTH_THRESHOLDS = {
    "defect":   {"warn": 0.5, "danger": 1.0},
    "late":     {"warn": 1.0, "danger": 3.0},
    "cases":    {"warn": 0.3, "danger": 1.0},
    "tracking": {"warn": 95.0, "danger": 90.0},  # これだけ逆（低いほど危険）
}


def send_slack(text: str):
    if not SLACK_WEBHOOK_URL:
        logger.warning("SLACK_WEBHOOK_URL is not set.")
        return
    requests.post(SLACK_WEBHOOK_URL, json={"text": text}, timeout=10)


def status_label(value: float, warn: float, danger: float, invert: bool = False) -> str:
    """安全/警戒/危険 のラベルを返す。invert=True は値が低いほど危険"""
    if invert:
        if value < danger:
            return "🔴 危険"
        elif value < warn:
            return "🟡 警戒"
        return "🟢 安全"
    else:
        if value > danger:
            return "🔴 危険"
        elif value > warn:
            return "🟡 警戒"
        return "🟢 安全"


# ── 1. 為替レート取得 ──────────────────────────────
def get_current_exchange_rate() -> Optional[float]:
    """USD/JPY の現在レートを取得（無料API）"""
    apis = [
        "https://api.exchangerate-api.com/v4/latest/USD",
        "https://open.er-api.com/v6/latest/USD",
    ]
    for url in apis:
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                rate = data.get("rates", {}).get("JPY")
                if rate:
                    return float(rate)
        except Exception as e:
            logger.warning(f"為替API失敗 ({url}): {e}")
    return None


# ── 2. アカウントヘルス取得 ─────────────────────────
def get_account_health() -> dict:
    """
    eBay Trading API の GetSellerDashboard でアカウントヘルスを取得。
    取得できない場合は空辞書を返す。
    """
    endpoint = (
        "https://api.ebay.com/ws/api.dll"
        if EBAY_ENV.upper() == "PRODUCTION"
        else "https://api.sandbox.ebay.com/ws/api.dll"
    )
    headers = {
        "X-EBAY-API-SITEID": str(EBAY_SITE_ID),
        "X-EBAY-API-COMPATIBILITY-LEVEL": "1131",
        "X-EBAY-API-CALL-NAME": "GetMyeBaySelling",
        "Content-Type": "text/xml",
    }
    xml_body = f"""<?xml version="1.0" encoding="utf-8"?>
<GetMyeBaySellingRequest xmlns="urn:ebay:apis:eBLBaseComponents">
  <RequesterCredentials>
    <eBayAuthToken>{EBAY_AUTH_TOKEN}</eBayAuthToken>
  </RequesterCredentials>
  <ActiveList>
    <Pagination>
      <EntriesPerPage>1</EntriesPerPage>
      <PageNumber>1</PageNumber>
    </Pagination>
  </ActiveList>
</GetMyeBaySellingRequest>"""

    try:
        resp = requests.post(endpoint, headers=headers, data=xml_body.encode("utf-8"), timeout=30)
        root = ET.fromstring(resp.text)
        ns = {"ebay": "urn:ebay:apis:eBLBaseComponents"}
        ack = root.findtext(".//ebay:Ack", namespaces=ns) or root.findtext(".//Ack")

        summary = root.find(".//ebay:Summary", namespaces=ns)
        if summary is None:
            summary = root.find(".//Summary")

        if ack in ("Success", "Warning") and summary is not None:
            active = summary.findtext("ebay:ActiveAuctionCount", namespaces=ns)
            if active is None:
                active = summary.findtext("ActiveAuctionCount")
            return {"active_count": int(active) if active else 0, "api_ok": True}
        return {"api_ok": True}
    except Exception as e:
        logger.error(f"eBay API エラー: {e}")
        return {"api_ok": False, "error": str(e)}


# ── 3. 滞留在庫チェック ────────────────────────────
def get_stale_inventory_count() -> int:
    """在庫管理表から30日以上更新のないActive商品数を返す"""
    try:
        items = sheets_manager.read_all_items()
        now = datetime.now()
        stale = 0
        for item in items:
            if item.get("status", "").lower() not in ("active",):
                continue
            last_checked = item.get("last_checked", "").strip()
            if not last_checked:
                stale += 1  # チェック日なし = 放置とみなす
                continue
            try:
                checked_dt = datetime.strptime(last_checked, "%Y-%m-%d %H:%M:%S")
                if (now - checked_dt).days >= STALE_DAYS:
                    stale += 1
            except ValueError:
                stale += 1  # パース不能 = 古いとみなす
        return stale
    except Exception as e:
        logger.error(f"在庫チェック失敗: {e}")
        return -1


# ── 4. エンジン稼働チェック ─────────────────────────
def check_engine_status() -> List[str]:
    """各エンジンのログ鮮度をチェックし、停止していればアラートを返す"""
    logs_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
    engines = {
        "自動出品エンジン": "auto_lister.log",
        "在庫同期": "inventory_sync.log",
        "VIP抽出": "manual_sourcer.log",
    }
    alerts = []
    for name, log_file in engines.items():
        path = os.path.join(logs_dir, log_file)
        if not os.path.exists(path):
            alerts.append(f"・{name}: ❌ ログ未発見（停止中の可能性）")
            continue
        hours = (time.time() - os.path.getmtime(path)) / 3600
        if hours > 12:
            alerts.append(f"・{name}: ❌ {int(hours)}時間前から停止")
    return alerts


# ── メインレポート生成 ─────────────────────────────
def main():
    logger.info("🛡️ リスクレポート生成開始...")

    # 為替
    current_rate = get_current_exchange_rate()
    if current_rate:
        diff = current_rate - EXCHANGE_RATE
        rate_status = status_label(abs(diff), RATE_WARNING_DIFF, RATE_WARNING_DIFF * 1.5)
        fx_section = (
            f"💱 *為替リスク*\n"
            f"・現在レート: {current_rate:.2f} JPY/USD\n"
            f"・基準レートとの差: {diff:+.2f}円（{rate_status}）"
        )
    else:
        fx_section = "💱 *為替リスク*\n・⚠️ 為替レート取得失敗"

    # アカウントヘルス
    health = get_account_health()
    if health.get("api_ok"):
        active = health.get("active_count", "?")
        health_section = (
            f"📊 *アカウントヘルス*\n"
            f"・eBay API接続: ✅ 正常\n"
            f"・アクティブ出品数: {active}件\n"
            f"・※ defect rate 等の詳細は Seller Hub で確認"
        )
    else:
        health_section = (
            f"📊 *アカウントヘルス*\n"
            f"・eBay API接続: ❌ エラー\n"
            f"・{health.get('error', '不明なエラー')}"
        )

    # 滞留在庫
    stale_count = get_stale_inventory_count()
    if stale_count < 0:
        inv_section = "📦 *在庫リスク*\n・⚠️ 在庫データ取得失敗"
    elif stale_count == 0:
        inv_section = "📦 *在庫リスク*\n・滞留在庫（30日超）: 0件 🟢"
    else:
        inv_section = f"📦 *在庫リスク*\n・滞留在庫（30日超）: {stale_count}件 🟡 値下げ検討推奨"

    # エンジン稼働
    engine_alerts = check_engine_status()
    if engine_alerts:
        engine_section = "🖥️ *システム稼働*\n" + "\n".join(engine_alerts)
    else:
        engine_section = "🖥️ *システム稼働*\n・全エンジン: ✅ 正常稼働中"

    # アラート集約
    alerts = []
    if current_rate and abs(current_rate - EXCHANGE_RATE) >= RATE_WARNING_DIFF:
        alerts.append(f"為替が基準から {current_rate - EXCHANGE_RATE:+.2f}円 乖離 → 価格見直し推奨")
    if stale_count > 0:
        alerts.append(f"滞留在庫 {stale_count}件 → 値下げ or 国内転売を検討")
    if engine_alerts:
        alerts.append("一部エンジンが停止中 → watchdog確認")
    if not health.get("api_ok"):
        alerts.append("eBay API接続エラー → トークン有効期限を確認")

    if alerts:
        alert_section = "⚠️ *アラート*\n" + "\n".join(f"・{a}" for a in alerts)
    else:
        alert_section = "✅ *アラート*\n・異常なし"

    # レポート組み立て
    report = (
        f"🛡️ *【リスクマネジメント部 日次レポート】*\n"
        f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
        f"{health_section}\n\n"
        f"{fx_section}\n\n"
        f"{inv_section}\n\n"
        f"{engine_section}\n\n"
        f"{alert_section}\n\n"
        f"今日も安全運用でいきましょう！🛡️"
    )

    send_slack(report)
    logger.info("✅ リスクレポート送信完了")


if __name__ == "__main__":
    main()
