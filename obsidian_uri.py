"""
Obsidian URI（obsidian://action?param=value）で開く。

仕様: https://help.obsidian.md/Advanced+topics/Using+obsidian+URI
- 値は必ず URI エンコード（/ → %2F など）。urllib.parse.urlencode(quote_via=quote) を使用。
- vault は保管庫名または Vault ID のどちらか。
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import Dict, Optional
from urllib.parse import quote, urlencode

_OPEN_PANE_TYPES = frozenset({"tab", "split", "window"})


def _uri_file_path(relative_to_kv: str) -> str:
    """knowledge_vault 基準の相対パスを、Obsidian Vault ルート基準に変換する。"""
    rel = (relative_to_kv or "").replace("\\", "/").lstrip("/")
    try:
        from config import OBSIDIAN_URI_PATH_PREFIX
    except ImportError:
        return rel
    pre = (OBSIDIAN_URI_PATH_PREFIX or "").strip().replace("\\", "/").strip("/")
    if not pre:
        return rel
    return f"{pre}/{rel}".replace("//", "/")


def _vault_query_value() -> Optional[str]:
    """config の Vault ID があれば優先、なければ Vault 名。"""
    try:
        from config import OBSIDIAN_VAULT_ID, OBSIDIAN_VAULT_NAME, OBSIDIAN_VAULT_PATH
    except ImportError:
        return None
    root = os.path.abspath(OBSIDIAN_VAULT_PATH)
    if not os.path.isdir(root):
        return None
    vid = (OBSIDIAN_VAULT_ID or "").strip()
    if vid:
        return vid
    return (OBSIDIAN_VAULT_NAME or "").strip() or None


def build_obsidian_uri(action: str, query: Dict[str, str]) -> str:
    """obsidian://{action}?... を組み立てる。空の値は含めない。"""
    a = (action or "").strip()
    if not a:
        raise ValueError("action が空です")
    items = [(k, v) for k, v in query.items() if v is not None and str(v) != ""]
    q = urlencode(items, quote_via=quote)
    return f"obsidian://{a}?{q}"


def build_open_uri(
    vault: str,
    file_relative: str,
    *,
    pane_type: Optional[str] = None,
) -> str:
    """open: 保管庫内のノートを開く。file は Vault ルートからの相対パス（.md 省略可）。"""
    v = (vault or "").strip()
    rel = (file_relative or "").replace("\\", "/").lstrip("/")
    if not v or not rel:
        raise ValueError("vault と file_relative が必要です")
    q: Dict[str, str] = {"vault": v, "file": rel}
    if pane_type:
        pt = pane_type.strip().lower()
        if pt not in _OPEN_PANE_TYPES:
            raise ValueError(f"paneType は {sorted(_OPEN_PANE_TYPES)} のいずれか")
        q["paneType"] = pt
    return build_obsidian_uri("open", q)


def build_daily_uri(vault: str, **extra: str) -> str:
    """daily: デイリーノートを作成または開く（デイリーノート系プラグイン要）。"""
    v = (vault or "").strip()
    if not v:
        raise ValueError("vault が必要です")
    q: Dict[str, str] = {"vault": v}
    q.update({k: v2 for k, v2 in extra.items() if v2})
    return build_obsidian_uri("daily", q)


def build_search_uri(vault: str, query: Optional[str] = None) -> str:
    """search: 検索を開き、任意で query を実行。"""
    v = (vault or "").strip()
    if not v:
        raise ValueError("vault が必要です")
    q: Dict[str, str] = {"vault": v}
    if query is not None and query != "":
        q["query"] = query
    return build_obsidian_uri("search", q)


def open_uri(uri: str) -> bool:
    """OS に応じて URI を開く。"""
    try:
        if sys.platform == "darwin":
            subprocess.run(["open", uri], check=False)
            return True
        if sys.platform.startswith("linux"):
            subprocess.run(["xdg-open", uri], check=False)
            return True
        if sys.platform == "win32":
            os.startfile(uri)  # type: ignore[attr-defined]
            return True
    except OSError:
        pass
    return False


def open_file_in_vault(
    file_relative: str,
    vault_name: Optional[str] = None,
    *,
    pane_type: Optional[str] = None,
) -> bool:
    """設定の Vault で file_relative を開く（open）。"""
    vault = vault_name or _vault_query_value()
    if not vault:
        return False
    uri = build_open_uri(vault, _uri_file_path(file_relative), pane_type=pane_type)
    return open_uri(uri)


def open_daily_note(vault_name: Optional[str] = None) -> bool:
    """daily アクション（デイリーノート）。"""
    vault = vault_name or _vault_query_value()
    if not vault:
        return False
    return open_uri(build_daily_uri(vault))


def open_search(query: Optional[str] = None, vault_name: Optional[str] = None) -> bool:
    """search アクション。"""
    vault = vault_name or _vault_query_value()
    if not vault:
        return False
    return open_uri(build_search_uri(vault, query=query))
