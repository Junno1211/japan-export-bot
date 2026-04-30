# メルカリ向けトラフィック用プロキシ（VPN クライアントのローカル HTTP/SOCKS など）
# .env 例: MERCARI_PROXY_SERVER=socks5://127.0.0.1:1080
#        MERCARI_PROXY_SERVER=http://127.0.0.1:7890

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional
from urllib.parse import quote, urlparse

logger = logging.getLogger(__name__)


def _raw_server() -> str:
    s = (os.getenv("MERCARI_PROXY_SERVER") or "").strip()
    if s:
        return s
    return (os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY") or "").strip()


def playwright_proxy_config() -> Optional[Dict[str, str]]:
    """chromium.launch(proxy=...) 用。未設定なら None。"""
    raw = _raw_server()
    if not raw:
        return None
    server = raw.strip()
    if "://" not in server:
        server = "http://" + server

    u = (os.getenv("MERCARI_PROXY_USERNAME") or "").strip()
    pw = (os.getenv("MERCARI_PROXY_PASSWORD") or "").strip()
    parsed = urlparse(server)
    if parsed.username:
        return {"server": server}
    if u:
        return {"server": server, "username": u, "password": pw}
    return {"server": server}


def playwright_launch_kwargs() -> Dict[str, Any]:
    cfg = playwright_proxy_config()
    if not cfg:
        return {}
    srv = cfg.get("server", "")
    logger.info("🌐 メルカリ用プロキシ: %s", srv[:96] + ("…" if len(srv) > 96 else ""))
    return {"proxy": cfg}


def requests_proxies() -> Optional[Dict[str, str]]:
    """requests.get(..., proxies=...) 用。"""
    raw = _raw_server()
    if not raw:
        return None
    url = raw.strip()
    if "://" not in url:
        url = "http://" + url

    parsed = urlparse(url)
    u = (os.getenv("MERCARI_PROXY_USERNAME") or "").strip()
    pw = (os.getenv("MERCARI_PROXY_PASSWORD") or "").strip()
    if u and not parsed.username and parsed.hostname:
        auth = f"{quote(u, safe='')}:{quote(pw, safe='')}"
        port = parsed.port
        host = parsed.hostname
        scheme = parsed.scheme or "http"
        netloc = f"{auth}@{host}" + (f":{port}" if port else "")
        url = f"{scheme}://{netloc}"

    return {"http": url, "https": url}
