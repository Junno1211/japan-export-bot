"""ebay_lister が TITLE_MAX_LENGTH でタイトルを切ることのスモーク。"""

from __future__ import annotations

import pathlib

from common_rules import TITLE_MAX_LENGTH


def test_ebay_lister_xml_uses_title_max_length_not_literal_80() -> None:
    root = pathlib.Path(__file__).resolve().parents[2]
    text = (root / "ebay_lister.py").read_text(encoding="utf-8")
    assert "title[:80]" not in text
    assert "title[:TITLE_MAX_LENGTH]" in text


def test_title_slice_equivalence_for_ebay() -> None:
    title = "Z" * 200
    assert title[:TITLE_MAX_LENGTH] == "Z" * TITLE_MAX_LENGTH
