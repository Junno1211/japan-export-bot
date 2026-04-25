"""auto_lister が common_rules を参照していることのソース検証。"""

from __future__ import annotations

import pathlib


def _auto_lister_source() -> str:
    root = pathlib.Path(__file__).resolve().parents[2]
    return (root / "auto_lister.py").read_text(encoding="utf-8")


def test_default_promoted_rate_aliases_common_rules() -> None:
    assert "DEFAULT_PROMOTED_RATE = PROMOTED_LISTINGS_RATE" in _auto_lister_source()


def test_listing_shipping_note_uses_fstring_constants() -> None:
    text = _auto_lister_source()
    assert "within <strong>{HANDLING_DAYS} business days</strong> of cleared payment" in text
    assert "Shipped via <strong>{SHIPPING_METHOD}</strong>" in text


def test_listing_ai_prompt_built_from_common_rules_replacements() -> None:
    text = _auto_lister_source()
    assert "_LISTING_AI_QUALITY_RULES_RAW" in text
    assert "TITLE_MAX_LENGTH" in text


def test_no_title_slice_literal_80() -> None:
    assert "[:80]" not in _auto_lister_source()


def test_priority_only_run_skips_test_rules_gate() -> None:
    text = _auto_lister_source()
    assert "priority_only_run = max_auto_success == 0" in text
    assert "手動キュー単独実行のため test_rules.py をスキップ" in text
    assert "else:\n        # 既定120秒" in text
