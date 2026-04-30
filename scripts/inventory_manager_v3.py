#!/usr/bin/env python3
"""
inventory_manager_v3.py — メルカリ照合（純之介3条件ルールのみで eBay OOS）

- OOS 化のきっかけは Playwright が sold / auction / deleted と判定したときのみ。
  sold・deleted は **API が error でも OOS**（削除・売切りの二重販売防止）。auction だけ API と突合する。
- deleted(url_notfound) 時の HEAD はログ用（OOS 判定には用いない）。
- pending 二段ロジックなし。
- mercari_checker.check_mercari_status は auction 突合・ログ用（在庫本流の inventory_manager.py は変更しない）。

  cd /opt/export-bot
  ./venv/bin/python3 -u scripts/inventory_manager_v3.py --dry-run --limit 10 --verbose

Playwright: load + 主要 DOM 待ち + 短い描画安定待ち（旧 networkidle+10s から縮小）。まず dry-run で確認すること。
"""
from __future__ import annotations

import argparse
import csv
import fcntl
import json
import logging
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import requests
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Any
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

os.makedirs(os.path.join(ROOT, "logs"), exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("inventory_v3")

from config import (  # noqa: E402
    MERCARI_PAGE_GOTO_TIMEOUT_MS,
    SHEET_NAME,
    SLACK_WEBHOOK_URL_ORDERS,
)
from ebay_updater import get_all_active_list_items, set_quantity  # noqa: E402
from feature_a import extract_mercari_item_id  # noqa: E402
from mercari_checker import (  # noqa: E402
    _mercari_api_item_snapshot_no_html,
    check_mercari_status,
)
from mercari_proxy import playwright_launch_kwargs  # noqa: E402
from sheets_manager import map_ebay_item_id_to_row_and_url  # noqa: E402
from v3_dual_reject_invariant import assert_dual_reject_detail_matches_counts  # noqa: E402

LOCK_FILE = "/tmp/inventory_manager_v3.lock"

# v3 専用: デスクトップ Chrome 相当（商品詳細・checkout-button 取得用）
_V3_DESKTOP_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_V3_EXTRA_HTTP_HEADERS = {
    "Accept-Language": "ja-JP,ja;q=0.9,en-US;q=0.8,en;q=0.7",
}
_V3_INIT_SCRIPT = (
    "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"
)


def notify_slack(text: str) -> None:
    """inventory_manager.notify_slack と同系（Webhook: SLACK_WEBHOOK_URL_ORDERS）。"""
    try:
        requests.post(SLACK_WEBHOOK_URL_ORDERS, json={"text": text}, timeout=10)
    except Exception as e:
        logger.warning("Slack通知失敗: %s", e)


def _merge_daily_oos_history(
    hist: Any, day_iso: str, oos_total: int
) -> list[dict[str, Any]]:
    """v3_heartbeat_state の日次 OOS 合計履歴をマージ（同一日は max）。"""
    rows: list[dict[str, Any]] = []
    if isinstance(hist, list):
        for item in hist:
            if isinstance(item, dict) and item.get("d"):
                rows.append(
                    {"d": str(item["d"]), "oos": int(item.get("oos") or 0)}
                )
    merged_today = False
    for row in rows:
        if row["d"] == day_iso:
            row["oos"] = max(row["oos"], oos_total)
            merged_today = True
            break
    if not merged_today:
        rows.append({"d": day_iso, "oos": oos_total})
    rows.sort(key=lambda x: x["d"])
    return rows[-62:]


def _seven_consecutive_days_all_oos_zero(
    hist: list[dict[str, Any]], end: date
) -> bool:
    """end を含む直近7暦日がすべて daily_oos に存在し、いずれも OOS 合計=0。"""
    m = {str(row["d"]): int(row.get("oos", 0)) for row in hist}
    for i in range(7):
        d = end - timedelta(days=i)
        key = d.isoformat()
        if key not in m:
            return False
        if m[key] != 0:
            return False
    return True


def _self_check_and_alert(counts: dict[str, int], total: int, txt_path: str) -> None:
    """巡回完了後のセルフチェック。異常パターンなら Slack（ORDERS webhook）へ警告1通。"""
    oos_total = counts["oos_sold"] + counts["oos_auction"] + counts["oos_deleted"]
    dual = counts.get("active_dual_reject", 0)
    timeout_n = counts["active_timeout"]
    exception_n = counts["active_exception"]
    html_fail = counts["active_empty_html"]
    triggers: list[str] = []

    if total >= 20 and oos_total == 0 and dual == 0:
        triggers.append(
            "条件A: 全件active・不一致ゼロ。判定ロジック異常の可能性。4/25と同パターン"
        )
    if total >= 20 and oos_total == 0 and dual >= 1:
        triggers.append(
            f"条件A': OOS=0だがdual_reject={dual}件あり。削除/SOLD見送り疑い、即時確認推奨"
        )
    if total >= 10 and total > 0 and (dual / float(total)) >= 0.20:
        triggers.append("条件B: 二系統不一致が20%超")
    env_n = timeout_n + exception_n + html_fail
    if total >= 10 and total > 0 and (env_n / float(total)) >= 0.10:
        triggers.append("条件C: 環境エラー10%超")

    state_path = os.path.join(ROOT, "logs", "v3_heartbeat_state.json")
    if os.path.isfile(state_path):
        try:
            with open(state_path, encoding="utf-8") as fp:
                prev = json.load(fp)
            tz = ZoneInfo("Asia/Tokyo")
            day_iso = datetime.now(tz).date().isoformat()
            merged = _merge_daily_oos_history(
                prev.get("daily_oos"), day_iso, oos_total
            )
            end_d = datetime.now(tz).date()
            if _seven_consecutive_days_all_oos_zero(merged, end_d):
                triggers.append("条件D: OOS化が7日連続ゼロ")
        except Exception as e:
            logger.warning("v3 self-check: v3_heartbeat_state 読込失敗: %s", e)

    if not triggers:
        return

    tz = ZoneInfo("Asia/Tokyo")
    now_jst = datetime.now(tz).strftime("%Y-%m-%d %H:%M")
    active_indet = (
        counts["active_timeout"]
        + counts["active_exception"]
        + counts["active_empty_html"]
        + counts["active_other"]
        + counts.get("active_dual_reject", 0)
    )
    active_total = counts["active_in_stock"] + active_indet

    cond = " | ".join(triggers)
    lines = [
        "🚨 inventory_v3 セルフチェック警告",
        f"- 検出条件: {cond}",
        f"- 内訳: 総対象={total} / OOS={oos_total} / dual_reject={dual} / "
        f"timeout={timeout_n} / Active={active_total}",
        f"- 時刻: {now_jst} JST",
        f"- レポート: {txt_path}",
    ]
    notify_slack("\n".join(lines))


def _slack_v3_cycle_done(
    *,
    dry_run: bool,
    total: int,
    elapsed_sec: int,
    counts: dict[str, int],
) -> None:
    """在庫管理 v3 が 1 周したとき 1 通送る（inventory_manager._slack_inventory_cycle_done に準拠）。"""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    oos_del = counts["oos_deleted"]
    oos_sold = counts["oos_sold"]
    oos_auc = counts["oos_auction"]
    oos_total = oos_del + oos_sold + oos_auc
    active_stock = counts["active_in_stock"]
    indet = (
        counts["active_timeout"]
        + counts["active_exception"]
        + counts["active_empty_html"]
        + counts["active_other"]
        + counts.get("active_dual_reject", 0)
    )
    err_n = counts["process_error"]
    em = elapsed_sec // 60
    es = elapsed_sec % 60

    anomalies: list[str] = []
    if total > 0:
        pct_other = 100.0 * counts["active_other"] / total
        if pct_other > 5.0:
            anomalies.append(f"判定不能率: {pct_other:.1f}% (基準値5%超)")
    if counts["active_timeout"] > 10:
        anomalies.append(f"タイムアウト: {counts['active_timeout']}件")
    if counts["process_error"] > 0:
        anomalies.append(f"処理エラー: {counts['process_error']}件")
    if oos_total > 50:
        anomalies.append(f"OOS化件数異常: {oos_total}件 (基準値50件超)")
    if counts["active_exception"] > 0:
        anomalies.append(f"例外発生: {counts['active_exception']}件")

    lines: list[str] = []
    if anomalies:
        lines.append(f"🚨 要確認: 在庫管理v3・1周終了 ({ts})")
        lines.extend(anomalies)
        lines.append("")
    else:
        lines.append(f"📦 在庫管理v3・1周終了 ({ts})")

    lines.append(
        f"**Phase0 メトリクス**: Playwrightタイムアウト={counts.get('active_timeout', 0)}件 / "
        f"二系統不一致でOOS見送り={counts.get('active_dual_reject', 0)}件"
    )
    lines.append("")

    lines.extend(
        [
            f"対象: {total}件 | 処理時間: {em}分{es}秒",
            "",
            "OOS化:",
            f"  削除検出: {oos_del}件",
            f"  SOLD検出: {oos_sold}件",
            f"  オークション検出: {oos_auc}件",
            f"  合計: {oos_total}件",
            "",
            "Active維持:",
            f"  販売中: {active_stock}件",
            f"  判定不能: {indet}件",
            "",
            f"エラー: {err_n}件",
        ]
    )
    if dry_run:
        lines.append("")
        lines.append("※dry-runモード（実OOS化なし）")

    notify_slack("\n".join(lines))


def _parse_quantity(r: dict, key: str = "quantity") -> int:
    v = r.get(key)
    if v is None:
        return -1
    try:
        return int(v)
    except (TypeError, ValueError):
        return -1


def _mercari_url_from_sku(sku: str) -> str:
    s = (sku or "").strip()
    if not s:
        return ""
    sl = s.lower()
    if "mercari" in sl and (s.startswith("http://") or s.startswith("https://")):
        return s
    if re.match(r"^m\d+$", s, re.I):
        return f"https://jp.mercari.com/item/{s}"
    return ""


def _url_suggests_deleted_notfound(page_url: str) -> bool:
    u = (page_url or "").strip().lower()
    if not u:
        return False
    try:
        p = urlparse(u).path.lower()
    except Exception:
        return False
    markers = (
        "/notfound",
        "/jp/notfound",
        "/items/notfound",
        "/error",
        "/404",
        "notfound",
    )
    return any(m in p for m in markers)


def _classify_mercari_dom() -> str:
    """page.evaluate に渡す IIFE ソース（HEAD 不使用・DOM のみ）。

    優先順: (1) checkout-button 販売中 (2) 削除文言 (3) item-detail-container 内 SOLD/売り切れ
    (4) auction JSON。いずれも非該当なら Active 維持（indeterminate_other）。
    """
    return r"""() => {
        const html = (document.documentElement && document.documentElement.innerHTML)
            ? document.documentElement.innerHTML : '';
        const bodyText = (document.body && document.body.innerText)
            ? document.body.innerText : '';
        if (!html || html.length < 80) {
            return { kind: 'empty_html', reason: 'short_or_empty_html' };
        }

        const checkout = document.querySelector('[data-testid="checkout-button"]');
        if (checkout) {
            const mer = checkout.closest ? checkout.closest('mer-button') : null;
            const dis = checkout.disabled || checkout.getAttribute('aria-disabled') === 'true'
                || (mer && mer.hasAttribute && mer.hasAttribute('disabled'));
            if (!dis) {
                return { kind: 'active', reason: '販売中(checkout-button検出)', sub: 'in_stock' };
            }
        }

        const deletePhrases = [
            '商品が見つかりません',
            'ページが見つかりません',
            '該当する商品はありません',
            '該当する商品は削除されています',
            '該当する商品は削除されました',
            'この商品は削除されました',
            'この商品は販売者により削除されました',
            '出品が見つかりませんでした',
            'お探しのページは見つかりません',
            'アクセスしようとしたページは表示できませんでした',
        ];
        for (const ph of deletePhrases) {
            if (bodyText.includes(ph)) {
                return { kind: 'deleted', reason: 'phrase:' + ph };
            }
        }

        const detail = document.querySelector('[data-testid="item-detail-container"]');
        if (detail) {
            const t = (detail.innerText || '').trim();
            const up = t.toUpperCase();
            if (up.includes('SOLD') || t.includes('売り切れ')) {
                return { kind: 'sold', reason: 'item-detail:SOLDまたは売り切れ' };
            }
        }

        if (html.includes('"item_trading_format":"auction"') ||
            html.includes('"item_type":"auction"')) {
            return { kind: 'auction', reason: 'json_auction_marker' };
        }

        return { kind: 'active', reason: 'OOS3条件に非該当', sub: 'indeterminate_other' };
    }"""


def _inspect_mercari_url(url: str, page) -> dict[str, Any]:
    """
    Playwright page で 1 URL を判定。戻り値:
      verdict: deleted | auction | sold | active
      reason: str
      maintain_sub: in_stock | indeterminate_timeout | indeterminate_exception
                  | indeterminate_empty_html | indeterminate_other | None
    """
    # networkidle は SPA で長時間ブロックしやすい。load + 主要 UI 待ち + 短い安定待ちに変更。
    # goto タイムアウト: config を尊重しつつ 55s〜120s（旧 180s 下限は廃止）。
    _cfg = int(MERCARI_PAGE_GOTO_TIMEOUT_MS)
    goto_ms = min(120_000, max(55_000, _cfg))
    try:
        from utils.phase0_guards import playwright_goto_with_retry

        playwright_goto_with_retry(
            page,
            url,
            wait_until="load",
            timeout_ms=goto_ms,
            attempts=2,
            sleep_between=0.5,
        )
        try:
            page.wait_for_selector(
                '[data-testid="checkout-button"], [data-testid="item-detail-container"], '
                '[data-testid="item-name"], [data-testid="item-price"]',
                timeout=12_000,
            )
        except Exception:
            pass
        time.sleep(2.5)
    except Exception as e:
        err = str(e).lower()
        if "timeout" in err:
            return {
                "verdict": "active",
                "reason": f"Playwrightタイムアウト: {e!s}"[:500],
                "maintain_sub": "indeterminate_timeout",
            }
        return {
            "verdict": "active",
            "reason": f"Playwright例外: {e!s}"[:500],
            "maintain_sub": "indeterminate_exception",
        }

    final_url = ""
    try:
        final_url = page.url or ""
    except Exception:
        final_url = ""

    if _url_suggests_deleted_notfound(final_url):
        return {
            "verdict": "deleted",
            "reason": f"url_notfound:{final_url[:200]}",
            "maintain_sub": None,
        }

    try:
        from utils.phase0_guards import with_retry

        data = with_retry(
            lambda: page.evaluate(_classify_mercari_dom()),
            retries=1,
            backoff=0.5,
        )
    except Exception as e:
        return {
            "verdict": "active",
            "reason": f"DOM評価失敗: {e!s}"[:500],
            "maintain_sub": "indeterminate_exception",
        }

    if not isinstance(data, dict):
        return {
            "verdict": "active",
            "reason": "DOM評価結果が非dict",
            "maintain_sub": "indeterminate_other",
        }

    kind = (data.get("kind") or "").strip()
    reason = (data.get("reason") or "").strip() or kind
    sub = data.get("sub")

    if kind == "empty_html":
        return {
            "verdict": "active",
            "reason": reason,
            "maintain_sub": "indeterminate_empty_html",
        }
    if kind == "deleted":
        return {"verdict": "deleted", "reason": reason, "maintain_sub": None}
    if kind == "auction":
        return {"verdict": "auction", "reason": reason, "maintain_sub": None}
    if kind == "sold":
        return {"verdict": "sold", "reason": reason, "maintain_sub": None}
    if kind == "active":
        ms = sub if sub in ("in_stock", "indeterminate_other") else "indeterminate_other"
        return {"verdict": "active", "reason": reason, "maintain_sub": ms}
    return {
        "verdict": "active",
        "reason": f"未知kind={kind}:{reason}",
        "maintain_sub": "indeterminate_other",
    }


def _head_status_for_deleted_confirm(url: str) -> int | None:
    """deleted(url_notfound) の第2系統: HTTP HEAD のステータス（ログ用）。"""
    try:
        r = requests.head(
            url,
            timeout=15,
            allow_redirects=True,
            headers={"User-Agent": _V3_DESKTOP_UA},
        )
        try:
            from utils.phase0_guards import log_http_status

            log_http_status(url, int(r.status_code), "inventory_v3_deleted_HEAD")
        except Exception:
            pass
        return int(r.status_code)
    except Exception:
        return None


def _v3_dual_confirm_oos(
    mercari_url: str,
    verdict: str,
    reason: str,
    *,
    api_snap: dict[str, Any] | None = None,
) -> tuple[bool, str, dict]:
    """
    OOS 前の突合（auction のみ API と整合必須）。

    - Playwright が sold / deleted を確定したら、API が error でも OOS する（二重販売防止）。
    - auction は従来どおり API が auction と一致するときのみ OOS。
    api_snap: item_id がある場合に Playwright と並走で取得した API 結果。
    """
    if verdict not in ("sold", "auction", "deleted"):
        return False, "not_oos_verdict", {}
    if api_snap is not None:
        api = api_snap
    else:
        api = check_mercari_status(mercari_url, delay=0.15)
    ast = api.get("status", "error")
    snap: dict[str, Any] = {"api_status": ast}

    if verdict == "sold":
        return True, "scraping_sold_force_oos", snap
    if verdict == "deleted":
        if "url_notfound" in (reason or ""):
            snap["head_status_deleted_confirm"] = _head_status_for_deleted_confirm(mercari_url)
        return True, "scraping_deleted_force_oos", snap

    if ast in ("error", "html_error"):
        return False, f"api_indeterminate:{ast}", snap
    if verdict == "auction":
        if ast != "auction":
            return False, f"auction_mismatch_api={ast}", snap
        return True, "dual_ok_auction", snap
    return False, f"unexpected_verdict:{verdict}", snap


def _mark_oos_v3(ebay_id: str, verdict: str, reason: str, *, dry_run: bool) -> bool:
    """3条件（sold / auction / deleted）のみ受け付ける。それ以外は例外。API 失敗時は False。"""
    if verdict not in ("sold", "auction", "deleted"):
        raise ValueError(
            f"不正な verdict: {verdict!r}（許可: sold/auction/deleted のみ）"
        )
    logger.info(
        "🚫 OOS化: ItemID=%s verdict=%s reason=%s dry_run=%s",
        ebay_id,
        verdict,
        reason[:300],
        dry_run,
    )
    if dry_run:
        return True
    res = set_quantity(ebay_id, 0)
    if not res.get("success"):
        logger.error(
            "set_quantity(0) 失敗: ebay_id=%s msg=%s",
            ebay_id,
            (res.get("message") or "")[:400],
        )
        return False
    return True


def _release_lock(lock_file) -> None:
    try:
        fcntl.flock(lock_file, fcntl.LOCK_UN)
    except OSError:
        pass
    try:
        lock_file.close()
    except OSError:
        pass


def _build_targets(
    active_list: list[dict],
    sheet_map: dict,
    limit: int,
) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for r in active_list:
        q = _parse_quantity(r)
        if q < 1:
            continue
        eid = (r.get("item_id") or "").strip()
        if not eid or eid in seen:
            continue
        seen.add(eid)
        sku = (r.get("sku") or "").strip()
        url = _mercari_url_from_sku(sku)
        if not url or "mercari" not in url.lower():
            info = sheet_map.get(eid)
            if info:
                cand = (info.get("mercari_url") or "").strip()
                if cand and "mercari" in cand.lower():
                    url = cand
        if not url:
            continue
        out.append({"ebay_id": eid, "mercari_url": url.strip(), "sku": sku})
        if limit and len(out) >= limit:
            break
    return out


def run_inventory_check_v3(
    dry_run: bool = False,
    limit: int = 0,
    verbose: bool = False,
) -> dict[str, Any]:
    """純之介3条件ルールで在庫チェック。dry_run=True なら OOS 化せずログのみ。"""
    start = datetime.now()
    start_s = start.strftime("%Y-%m-%d %H:%M:%S")
    ts = start.strftime("%Y%m%d_%H%M%S")

    lock_f = open(LOCK_FILE, "w")
    try:
        fcntl.flock(lock_f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        logger.info("別の inventory_manager_v3 が実行中。スキップ。")
        try:
            lock_f.close()
        except OSError:
            pass
        return {"skipped": True, "reason": "lock_busy"}

    counts: dict[str, int] = {
        "oos_sold": 0,
        "oos_auction": 0,
        "oos_deleted": 0,
        "active_in_stock": 0,
        "active_timeout": 0,
        "active_exception": 0,
        "active_empty_html": 0,
        "active_other": 0,
        "active_dual_reject": 0,
        "process_error": 0,
    }
    detail_rows: list[dict[str, str]] = []

    try:
        sheet_map = map_ebay_item_id_to_row_and_url(SHEET_NAME)
        active_list = get_all_active_list_items()
        targets = _build_targets(active_list, sheet_map, limit)
        total = len(targets)
        logger.info(
            "inventory_v3: 対象 %s 件（eBay Active qty>=1 かつメルカリURL解決済・limit=%s）",
            total,
            limit or "なし",
        )

        if not targets:
            logger.info("inventory_v3: 対象0件で終了")

        if targets:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as p:
                launch_kw = dict(
                    headless=True,
                    args=["--no-sandbox", "--disable-dev-shm-usage"],
                )
                launch_kw.update(playwright_launch_kwargs())
                browser = p.chromium.launch(**launch_kw)
                ctx = browser.new_context(
                    user_agent=_V3_DESKTOP_UA,
                    viewport={"width": 1920, "height": 1080},
                    locale="ja-JP",
                    timezone_id="Asia/Tokyo",
                    extra_http_headers=dict(_V3_EXTRA_HTTP_HEADERS),
                )
                page = ctx.new_page()
                page.add_init_script(_V3_INIT_SCRIPT)
                api_pool = ThreadPoolExecutor(
                    max_workers=1, thread_name_prefix="v3_mercapi"
                )
                try:
                    for i, row in enumerate(targets, start=1):
                        ebay_id = row["ebay_id"]
                        murl = row["mercari_url"]
                        action_taken = "MAINTAINED"
                        verdict = "active"
                        reason = ""
                        api_future = None
                        try:
                            mid = extract_mercari_item_id(murl)
                            if mid:
                                api_future = api_pool.submit(
                                    _mercari_api_item_snapshot_no_html, mid
                                )
                            info = _inspect_mercari_url(murl, page)
                            verdict = info["verdict"]
                            reason = info.get("reason") or ""
                            sub = info.get("maintain_sub")

                            api_snap_for_dual: dict[str, Any] | None = None
                            if api_future is not None:
                                if verdict in ("sold", "auction", "deleted"):
                                    try:
                                        api_snap_for_dual = api_future.result(
                                            timeout=22
                                        )
                                    except Exception as ex:
                                        api_snap_for_dual = {
                                            "status": "error",
                                            "title": "",
                                            "price": "",
                                            "error": str(ex),
                                        }
                                else:
                                    if not api_future.cancel():
                                        try:
                                            api_future.result(timeout=25)
                                        except Exception:
                                            pass

                            if verdict == "sold":
                                dual_ok, dual_note, _snap = _v3_dual_confirm_oos(
                                    murl,
                                    verdict,
                                    reason,
                                    api_snap=api_snap_for_dual if mid else None,
                                )
                                if not dual_ok:
                                    counts["active_dual_reject"] += 1
                                    logger.warning(
                                        "v3 Phase0二系統不一致→OOS見送り ebay=%s note=%s",
                                        ebay_id,
                                        dual_note,
                                    )
                                    action_taken = "MAINTAINED_DUAL_REJECT"
                                    detail_rows.append(
                                        {
                                            "ebay_item_id": ebay_id,
                                            "mercari_url": murl,
                                            "verdict": verdict,
                                            "reason": dual_note or reason,
                                            "action_taken": action_taken,
                                        }
                                    )
                                    continue
                                assert dual_ok
                                ok_oos = _mark_oos_v3(
                                    ebay_id, "sold", reason, dry_run=dry_run
                                )
                                if dry_run or ok_oos:
                                    counts["oos_sold"] += 1
                                if not dry_run and not ok_oos:
                                    counts["process_error"] += 1
                                action_taken = (
                                    "OOS_WOULD_APPLY"
                                    if dry_run
                                    else ("OOS_APPLIED" if ok_oos else "OOS_API_FAIL")
                                )
                            elif verdict == "auction":
                                dual_ok, dual_note, _snap = _v3_dual_confirm_oos(
                                    murl,
                                    verdict,
                                    reason,
                                    api_snap=api_snap_for_dual if mid else None,
                                )
                                if not dual_ok:
                                    counts["active_dual_reject"] += 1
                                    logger.warning(
                                        "v3 Phase0二系統不一致→OOS見送り ebay=%s note=%s",
                                        ebay_id,
                                        dual_note,
                                    )
                                    action_taken = "MAINTAINED_DUAL_REJECT"
                                    detail_rows.append(
                                        {
                                            "ebay_item_id": ebay_id,
                                            "mercari_url": murl,
                                            "verdict": verdict,
                                            "reason": dual_note or reason,
                                            "action_taken": action_taken,
                                        }
                                    )
                                    continue
                                assert dual_ok
                                ok_oos = _mark_oos_v3(
                                    ebay_id, "auction", reason, dry_run=dry_run
                                )
                                if dry_run or ok_oos:
                                    counts["oos_auction"] += 1
                                if not dry_run and not ok_oos:
                                    counts["process_error"] += 1
                                action_taken = (
                                    "OOS_WOULD_APPLY"
                                    if dry_run
                                    else ("OOS_APPLIED" if ok_oos else "OOS_API_FAIL")
                                )
                            elif verdict == "deleted":
                                dual_ok, dual_note, _snap = _v3_dual_confirm_oos(
                                    murl,
                                    verdict,
                                    reason,
                                    api_snap=api_snap_for_dual if mid else None,
                                )
                                if not dual_ok:
                                    counts["active_dual_reject"] += 1
                                    logger.warning(
                                        "v3 Phase0二系統不一致→OOS見送り ebay=%s note=%s",
                                        ebay_id,
                                        dual_note,
                                    )
                                    action_taken = "MAINTAINED_DUAL_REJECT"
                                    detail_rows.append(
                                        {
                                            "ebay_item_id": ebay_id,
                                            "mercari_url": murl,
                                            "verdict": verdict,
                                            "reason": dual_note or reason,
                                            "action_taken": action_taken,
                                        }
                                    )
                                    continue
                                assert dual_ok
                                ok_oos = _mark_oos_v3(
                                    ebay_id, "deleted", reason, dry_run=dry_run
                                )
                                if dry_run or ok_oos:
                                    counts["oos_deleted"] += 1
                                if not dry_run and not ok_oos:
                                    counts["process_error"] += 1
                                action_taken = (
                                    "OOS_WOULD_APPLY"
                                    if dry_run
                                    else ("OOS_APPLIED" if ok_oos else "OOS_API_FAIL")
                                )
                            else:
                                if sub == "in_stock":
                                    counts["active_in_stock"] += 1
                                elif sub == "indeterminate_timeout":
                                    counts["active_timeout"] += 1
                                elif sub == "indeterminate_exception":
                                    counts["active_exception"] += 1
                                elif sub == "indeterminate_empty_html":
                                    counts["active_empty_html"] += 1
                                else:
                                    counts["active_other"] += 1
                                action_taken = "MAINTAINED"

                            if verbose:
                                logger.info(
                                    "[%s/%s] ebay=%s verdict=%s action=%s url=%s reason=%s",
                                    i,
                                    total,
                                    ebay_id,
                                    verdict,
                                    action_taken,
                                    murl[:80],
                                    reason[:200],
                                )
                        except Exception as ex:
                            if api_future is not None:
                                try:
                                    if not api_future.cancel():
                                        api_future.result(timeout=25)
                                except Exception:
                                    pass
                            counts["process_error"] += 1
                            action_taken = "ERROR"
                            verdict = "error"
                            reason = f"{type(ex).__name__}: {ex}"[:500]
                            logger.exception(
                                "inventory_v3: 個別エラー ebay=%s url=%s",
                                ebay_id,
                                murl[:120],
                            )
                        detail_rows.append(
                            {
                                "ebay_item_id": ebay_id,
                                "mercari_url": murl,
                                "verdict": verdict,
                                "reason": reason,
                                "action_taken": action_taken,
                            }
                        )
                        time.sleep(0.12)
                finally:
                    api_pool.shutdown(wait=True)
                    try:
                        page.close()
                    except Exception:
                        pass
                    try:
                        ctx.close()
                    except Exception:
                        pass
                    try:
                        browser.close()
                    except Exception:
                        pass

        assert_dual_reject_detail_matches_counts(counts, detail_rows)

        end = datetime.now()
        end_s = end.strftime("%Y-%m-%d %H:%M:%S")
        elapsed = int((end - start).total_seconds())

        oos_total = (
            counts["oos_sold"] + counts["oos_auction"] + counts["oos_deleted"]
        )
        active_indet = (
            counts["active_timeout"]
            + counts["active_exception"]
            + counts["active_empty_html"]
            + counts["active_other"]
            + counts.get("active_dual_reject", 0)
        )
        active_total = counts["active_in_stock"] + active_indet

        report_lines = [
            "",
            f"巡回完了レポート [開始: {start_s} / 終了: {end_s} / 所要: {elapsed}秒]",
            "========================================",
            f"総対象件数: {total} 件",
            "",
            "OOS化内訳:",
            f"  - SOLD検出 → OOS化:       {counts['oos_sold']} 件",
            f"  - オークション検出 → OOS化:  {counts['oos_auction']} 件",
            f"  - 削除検出 → OOS化:          {counts['oos_deleted']} 件",
            f"  OOS化合計:                   {oos_total} 件",
            "",
            "Active維持内訳:",
            f"  - 販売中と判定:              {counts['active_in_stock']} 件",
            f"  - 判定不能（Active維持）:    {active_indet} 件",
            "    内訳:",
            f"      - Playwrightタイムアウト:  {counts['active_timeout']} 件",
            f"      - Playwright例外:          {counts['active_exception']} 件",
            f"      - HTML取得失敗:             {counts['active_empty_html']} 件",
            f"      - 二系統不一致(OOS見送り):   {counts.get('active_dual_reject', 0)} 件",
            f"      - その他:                   {counts['active_other']} 件",
            f"  Active維持合計:              {active_total} 件",
            "",
            f"処理エラー（スキップ）: {counts['process_error']} 件",
            "========================================",
            "",
        ]
        report_body = "\n".join(report_lines)
        logger.info(report_body)

        txt_path = os.path.join(ROOT, "logs", f"inventory_v3_report_{ts}.txt")
        csv_path = os.path.join(ROOT, "logs", f"inventory_v3_detail_{ts}.csv")
        with open(txt_path, "w", encoding="utf-8") as fp:
            fp.write(report_body)
        with open(csv_path, "w", encoding="utf-8", newline="") as fp:
            w = csv.DictWriter(
                fp,
                fieldnames=[
                    "ebay_item_id",
                    "mercari_url",
                    "verdict",
                    "reason",
                    "action_taken",
                ],
            )
            w.writeheader()
            for dr in detail_rows:
                w.writerow(dr)
        logger.info("inventory_v3: 報告書 TXT=%s CSV=%s", txt_path, csv_path)

        state_path = os.path.join(ROOT, "logs", "v3_heartbeat_state.json")
        prev_state: dict[str, Any] = {}
        if os.path.isfile(state_path):
            try:
                with open(state_path, encoding="utf-8") as sfp:
                    prev_state = json.load(sfp)
            except Exception as ex:
                logger.warning("v3 heartbeat state read failed: %s", ex)
                prev_state = {}
        _tz_jst = ZoneInfo("Asia/Tokyo")
        day_jst_iso = datetime.now(_tz_jst).date().isoformat()
        daily_oos = _merge_daily_oos_history(
            prev_state.get("daily_oos"), day_jst_iso, oos_total
        )

        _self_check_and_alert(counts, total, txt_path)

        try:
            with open(state_path, "w", encoding="utf-8") as sfp:
                json.dump(
                    {
                        "last_run_iso": end.isoformat(),
                        "elapsed_sec": elapsed,
                        "total_targets": total,
                        "counts": dict(counts),
                        "daily_oos": daily_oos,
                    },
                    sfp,
                    ensure_ascii=False,
                    indent=2,
                )
        except Exception as ex:
            logger.warning("v3 heartbeat state write failed: %s", ex)

        _slack_v3_cycle_done(
            dry_run=dry_run,
            total=total,
            elapsed_sec=elapsed,
            counts=counts,
        )

        return {
            "skipped": False,
            "txt_path": txt_path,
            "csv_path": csv_path,
            "counts": dict(counts),
            "total_targets": total,
            "elapsed_sec": elapsed,
        }
    finally:
        _release_lock(lock_f)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="inventory_manager v3（純之介3条件のみで OOS）",
    )
    ap.add_argument("--dry-run", action="store_true", help="OOS せずログとレポートのみ")
    ap.add_argument("--limit", type=int, default=0, help="処理件数上限（0=全件）")
    ap.add_argument("--verbose", action="store_true", help="各商品の判定ログ")
    args = ap.parse_args()
    try:
        run_inventory_check_v3(
            dry_run=args.dry_run,
            limit=max(0, args.limit),
            verbose=args.verbose,
        )
    except Exception:
        logger.exception("inventory_manager_v3 異常終了")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
