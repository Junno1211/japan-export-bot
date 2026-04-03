#!/usr/bin/env python3
"""
supervisor.py — 全操作の監視・検証・ブロック機構

全ての出品・リサーチ操作は必ずこの監視を通す。
ルール違反はブロック + Slack即時通報。
"""

import os
import re
import json
import csv
import logging
from datetime import datetime
from typing import Optional

from config import (
    SPREADSHEET_ID, SHEET_NAME, EXCHANGE_RATE,
    SLACK_WEBHOOK_URL, SLACK_WEBHOOK_URL_ORDERS
)

logger = logging.getLogger(__name__)

# ============================================================
#  ビジネスルール定数（変更禁止 — 変更はCEO承認必須）
# ============================================================
RULES = {
    "min_profit_jpy": 3000,         # 最低利益
    "min_roi_pct": 25,              # 最低ROI（利益¥3,000以上なら免除）
    "max_purchase_jpy": 250_000,    # 仕入れ上限
    "max_price_usd": 2500,          # 販売価格上限
    "min_purchase_jpy": 1000,       # 仕入れ下限
    "fee_total_pct": 19.6,          # 手数料合計
    "exchange_rate": 155.0,         # 為替
    "tax_refund_pct": 10,           # 消費税還付
}

# 絶対NG — 説明文に外部URLがあればブロック
URL_PATTERN = re.compile(
    r'https?://[^\s<>"\']+|www\.[^\s<>"\']+',
    re.IGNORECASE
)
# eBay自身のURLは許可
ALLOWED_URL_DOMAINS = {"ebay.com", "ebayimg.com", "ebaystatic.com"}

# NGキーワード（まとめ売り・ジャンク等）
NG_KEYWORDS = [
    "まとめ売り", "まとめて", "セット売り", "大量", "引退", "処分",
    "bulk", "lot", "枚セット", "枚まとめ",
    "100枚", "200枚", "300枚", "500枚", "1000枚",
    "ジャンク", "故障", "不動", "部品取り",
]

# 監査ログパス
AUDIT_LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
AUDIT_LOG_PATH = os.path.join(AUDIT_LOG_DIR, "supervisor_audit.log")


# ============================================================
#  監査ログ
# ============================================================
def _audit_log(action: str, result: str, details: str = ""):
    """全操作を監査ログに記録（改ざん検知用タイムスタンプ付き）"""
    os.makedirs(AUDIT_LOG_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{ts} | {action} | {result} | {details}\n"
    with open(AUDIT_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line)


def _alert_slack(message: str):
    """違反をSlackに即時通報"""
    import requests
    webhook = SLACK_WEBHOOK_URL_ORDERS or SLACK_WEBHOOK_URL
    if not webhook:
        return
    try:
        requests.post(webhook, json={"text": f"[SUPERVISOR BLOCK] {message}"}, timeout=10)
    except Exception as e:
        logger.error(f"Supervisor Slack通報失敗: {e}")


# ============================================================
#  検証関数群
# ============================================================
class SupervisorViolation(Exception):
    """ルール違反で処理をブロックする例外"""
    pass


def validate_listing(
    mercari_url: str,
    mercari_price_jpy: int,
    ebay_price_usd: float,
    profit_jpy: float,
    roi_pct: float,
    title: str,
    description_html: str,
    is_priority: bool = False,
    existing_urls: set = None,
) -> dict:
    """
    出品前の全項目検証。
    違反があれば即ブロック + Slack通報。

    Returns: {"approved": True/False, "violations": [...], "warnings": [...]}
    """
    violations = []
    warnings = []

    # --- 1. 重複チェック ---
    if existing_urls and mercari_url.strip() in existing_urls:
        violations.append(f"重複出品: {mercari_url}")

    # --- 2. 仕入価格の範囲チェック ---
    if not is_priority:
        if mercari_price_jpy < RULES["min_purchase_jpy"]:
            violations.append(f"仕入価格が下限以下: ¥{mercari_price_jpy:,} < ¥{RULES['min_purchase_jpy']:,}")
        if mercari_price_jpy > RULES["max_purchase_jpy"]:
            violations.append(f"仕入価格が上限超過: ¥{mercari_price_jpy:,} > ¥{RULES['max_purchase_jpy']:,}")

    # --- 3. 販売価格の範囲チェック ---
    if ebay_price_usd > RULES["max_price_usd"]:
        violations.append(f"販売価格が上限超過: ${ebay_price_usd} > ${RULES['max_price_usd']}")
    if ebay_price_usd < 1.0:
        violations.append(f"販売価格が異常: ${ebay_price_usd}")

    # --- 4. 利益チェック（¥3,000以上ならROI低くてもOK） ---
    if profit_jpy < RULES["min_profit_jpy"] and roi_pct < RULES["min_roi_pct"]:
        violations.append(
            f"利益不足: ¥{int(profit_jpy):,} (ROI {roi_pct:.0f}%) — "
            f"最低¥{RULES['min_profit_jpy']:,} or ROI {RULES['min_roi_pct']}%必要"
        )

    # --- 5. 説明文に外部URLがないか ---
    urls_found = URL_PATTERN.findall(description_html)
    for u in urls_found:
        domain = u.split("/")[2] if "//" in u else u.split("/")[0]
        domain = domain.lower().replace("www.", "")
        if not any(domain.endswith(allowed) for allowed in ALLOWED_URL_DOMAINS):
            violations.append(f"説明文に外部URL検出（eBayポリシー違反）: {u[:80]}")

    # --- 6. オークション商品ブロック（経営破綻防止） ---
    # 注意: 「入札」は説明文に自然に出現するため使わない（偽陽性防止）
    title_lower = title.lower()
    auction_title_signals = ["オークション", "auction"]
    for signal in auction_title_signals:
        if signal in title_lower:
            violations.append(f"オークション商品検出(タイトル): '{signal}'")

    # --- 7. NGキーワード ---
    for ng in NG_KEYWORDS:
        if ng in title_lower:
            violations.append(f"NGキーワード検出: '{ng}' in title")

    # --- 7. タイトル長 ---
    if len(title) > 80:
        warnings.append(f"タイトル80文字超過: {len(title)}文字")

    # --- 8. 画像なし出品の防止（呼び出し側で画像URLを渡す場合） ---
    # ※画像チェックは呼び出し側で行う

    # --- 結果判定 ---
    approved = len(violations) == 0

    # 監査ログ記録
    status = "APPROVED" if approved else "BLOCKED"
    violation_detail = (" | reasons=" + "; ".join(violations)) if violations else ""
    _audit_log(
        action="LISTING_CHECK",
        result=status,
        details=f"url={mercari_url} price=${ebay_price_usd} profit=¥{int(profit_jpy):,} violations={len(violations)}{violation_detail}"
    )

    # 違反があればSlack通報
    if not approved:
        alert_msg = f"出品ブロック\n" + "\n".join(f"  - {v}" for v in violations)
        _alert_slack(alert_msg)
        logger.warning(f"[SUPERVISOR] BLOCKED: {violations}")

    return {
        "approved": approved,
        "violations": violations,
        "warnings": warnings,
    }


def validate_sourcing(
    mercari_url: str,
    mercari_price_jpy: int,
    profit_jpy: int,
    title: str,
    existing_urls: set = None,
) -> dict:
    """
    リサーチ結果をシートに書き込む前の検証。
    """
    violations = []
    warnings = []

    # 重複
    if existing_urls and mercari_url.strip() in existing_urls:
        violations.append(f"重複: {mercari_url}")

    # 仕入価格
    if mercari_price_jpy < RULES["min_purchase_jpy"]:
        violations.append(f"仕入価格¥{mercari_price_jpy:,} < 下限¥{RULES['min_purchase_jpy']:,}")
    if mercari_price_jpy > RULES["max_purchase_jpy"]:
        violations.append(f"仕入価格¥{mercari_price_jpy:,} > 上限¥{RULES['max_purchase_jpy']:,}")

    # 利益
    roi = (profit_jpy / mercari_price_jpy * 100) if mercari_price_jpy > 0 else 0
    if profit_jpy < RULES["min_profit_jpy"] and roi < RULES["min_roi_pct"]:
        violations.append(f"利益¥{profit_jpy:,} / ROI{roi:.0f}% — 基準未達")

    # NGキーワード
    title_lower = title.lower()
    for ng in NG_KEYWORDS:
        if ng in title_lower:
            violations.append(f"NGキーワード: '{ng}'")

    # オークション除外
    if "オークション" in title_lower or "auction" in title_lower:
        violations.append("オークション形式は対象外")

    approved = len(violations) == 0

    _audit_log(
        action="SOURCING_CHECK",
        result="APPROVED" if approved else "BLOCKED",
        details=f"url={mercari_url} price=¥{mercari_price_jpy:,} profit=¥{profit_jpy:,} violations={len(violations)}"
    )

    if not approved:
        logger.info(f"[SUPERVISOR] Sourcing BLOCKED: {violations}")

    return {
        "approved": approved,
        "violations": violations,
        "warnings": warnings,
    }


def validate_description(html: str) -> dict:
    """出品説明文の安全性チェック"""
    violations = []

    urls_found = URL_PATTERN.findall(html)
    for u in urls_found:
        domain = u.split("/")[2] if "//" in u else u.split("/")[0]
        domain = domain.lower().replace("www.", "")
        if not any(domain.endswith(allowed) for allowed in ALLOWED_URL_DOMAINS):
            violations.append(f"外部URL: {u[:100]}")

    approved = len(violations) == 0

    if not approved:
        _audit_log("DESC_CHECK", "BLOCKED", f"外部URL {len(violations)}件検出")
        _alert_slack(f"説明文に外部URL検出（eBayポリシー違反）: {violations}")

    return {"approved": approved, "violations": violations}


def validate_config_unchanged() -> dict:
    """
    config.pyのビジネスルール定数が改ざんされていないか検証。
    ※ 起動時に1回呼ぶ
    """
    from config import EXCHANGE_RATE as current_rate
    violations = []

    if current_rate != RULES["exchange_rate"]:
        violations.append(f"為替レート改ざん: {current_rate} (正: {RULES['exchange_rate']})")

    approved = len(violations) == 0
    if not approved:
        _alert_slack(f"設定改ざん検出: {violations}")
        _audit_log("CONFIG_CHECK", "ALERT", str(violations))

    return {"approved": approved, "violations": violations}


# ============================================================
#  日次レポート
# ============================================================
def generate_daily_report() -> str:
    """監査ログから日次サマリーを生成"""
    if not os.path.exists(AUDIT_LOG_PATH):
        return "監査ログなし"

    today = datetime.now().strftime("%Y-%m-%d")
    approved = 0
    blocked = 0
    block_reasons = []

    with open(AUDIT_LOG_PATH, "r", encoding="utf-8") as f:
        for line in f:
            if not line.startswith(today):
                continue
            if "| APPROVED |" in line:
                approved += 1
            elif "| BLOCKED |" in line:
                blocked += 1
                block_reasons.append(line.strip())

    total = approved + blocked
    block_rate = (blocked / total * 100) if total > 0 else 0

    report = (
        f"[Supervisor日次レポート {today}]\n"
        f"検証: {total}件 | 承認: {approved}件 | ブロック: {blocked}件 ({block_rate:.0f}%)\n"
    )
    if block_reasons:
        report += "直近のブロック:\n"
        for r in block_reasons[-5:]:
            report += f"  {r}\n"

    return report


if __name__ == "__main__":
    # テスト実行
    result = validate_listing(
        mercari_url="https://jp.mercari.com/item/test123",
        mercari_price_jpy=5000,
        ebay_price_usd=99.0,
        profit_jpy=4500,
        roi_pct=90,
        title="Test Pokemon Card PSA10",
        description_html="<p>Great card from Japan</p>",
    )
    print(f"Test result: {result}")

    config_check = validate_config_unchanged()
    print(f"Config check: {config_check}")

    print(generate_daily_report())
