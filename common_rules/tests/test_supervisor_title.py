"""supervisor が common_rules のタイトル長を参照していることのソース検証。

supervisor は config に依存するため、config 不在環境では import テストをしない。
"""

from __future__ import annotations

import pathlib


def test_supervisor_uses_validate_title_length_and_max_length() -> None:
    root = pathlib.Path(__file__).resolve().parents[2]
    text = (root / "supervisor.py").read_text(encoding="utf-8")
    assert "from common_rules import TITLE_MAX_LENGTH, validate_title_length" in text
    assert "if not validate_title_length(title):" in text
    assert "タイトル{TITLE_MAX_LENGTH}文字超過" in text
    assert "u[:TITLE_MAX_LENGTH]" in text or "{u[:TITLE_MAX_LENGTH]}" in text


def test_supervisor_manual_sheet_wraps_auction_and_ng() -> None:
    root = pathlib.Path(__file__).resolve().parents[2]
    text = (root / "supervisor.py").read_text(encoding="utf-8")
    assert "manual_sheet: bool = False" in text
    assert "if not manual_sheet:" in text
