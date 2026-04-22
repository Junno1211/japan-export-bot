# ============================================================
#  phase0_guards.py — Phase 0: retry / 二系統一致 / HTTP 記録 / 429 停止
# ============================================================

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class MercariPipelineStopped(RuntimeError):
    """メルカリ側でレート制限等 — 当該パイプラインを安全側で中断する。"""


def with_retry(
    func: Callable[[], T],
    *,
    retries: int = 1,
    backoff: float = 1.0,
    retry_on: Callable[[BaseException], bool] | None = None,
) -> T:
    """
    最低 1 回の再試行 = 合計 (retries+1) 回まで func を呼ぶ。
    retry_on が None のときは任意の Exception でリトライする。
    """
    last: BaseException | None = None
    attempts = max(0, int(retries)) + 1
    for i in range(attempts):
        try:
            return func()
        except Exception as e:
            last = e
            if i + 1 >= attempts:
                raise
            if retry_on is not None and not retry_on(e):
                raise
            wait = backoff * (i + 1)
            logger.warning(
                "with_retry: attempt %s/%s failed (%s). sleep %.2fs",
                i + 1,
                attempts,
                type(e).__name__,
                wait,
            )
            time.sleep(wait)
    assert last is not None
    raise last


def verify_independent(source_a: Any, source_b: Any) -> bool:
    """
    二系統の「確定用シグナル」が同一方向かを判定する汎用ヘルパ。
    文字列・bool・タプル等、== で比較できる値を想定。
    """
    return source_a == source_b


def log_http_status(url: str, status_code: int | None, context: str) -> None:
    """deleted / HEAD 検証など HTTP ステータスを追跡可能にする。"""
    logger.info(
        "[Phase0 HTTP] context=%s url=%s status=%s",
        context,
        (url or "")[:200],
        status_code if status_code is not None else "None",
    )


def rate_limit_guard(response: Any, service: str) -> None:
    """
    HTTP 429 を検知したら Slack に 1 通出して例外で停止（Phase 0: リトライしない）。
    response: requests.Response 互換（.status_code を持つ）
    """
    code = getattr(response, "status_code", None)
    if code != 429:
        return
    try:
        from notifier import notify_slack

        msg = (
            f"🛑 **[{service}] HTTP 429 (rate limit)** — Phase 0 方針により処理を停止しました。\n"
            "手動で間隔を空けたうえ再実行するか、Phase 0.5 で指数バックオフを検討してください。"
        )
        notify_slack(msg)
    except Exception as e:
        logger.warning("rate_limit_guard: Slack 通知失敗: %s", e)
    raise RuntimeError(f"{service}: HTTP 429 — pipeline stopped (Phase 0)")


def playwright_goto_with_retry(
    page,
    url: str,
    *,
    wait_until: str,
    timeout_ms: int,
    attempts: int = 2,
    sleep_between: float = 1.0,
) -> None:
    """
    Page.goto に最低 1 回分の再試行を付与（attempts=2 → 最大 2 回）。
    タイムアウト / ネットワーク系のみ再試行し、それ以外は即再送出。
    """
    last: BaseException | None = None
    n = max(1, int(attempts))
    for i in range(n):
        try:
            page.goto(url, wait_until=wait_until, timeout=timeout_ms)
            return
        except Exception as e:
            last = e
            err = str(e).lower()
            transient = any(
                x in err
                for x in (
                    "timeout",
                    "navigation",
                    "net::",
                    "econnrefused",
                    "econnreset",
                    "enotfound",
                    "eof",
                )
            )
            if not transient or i + 1 >= n:
                raise
            logger.warning(
                "playwright_goto_with_retry: transient %s (%s/%s) url=%s",
                type(e).__name__,
                i + 1,
                n,
                url[:120],
            )
            time.sleep(sleep_between * (i + 1))
    assert last is not None
    raise last
