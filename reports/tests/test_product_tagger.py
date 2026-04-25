"""product_tagger の単体テスト。"""

from __future__ import annotations

import json
from pathlib import Path

from reports.product_tagger import (
    load_keyword_tags,
    load_price_bands,
    load_tag_dictionaries,
    tag_product,
)


def _dicts() -> dict:
    return {
        "character": ["Ohtani", "Shohei Ohtani", "Pikachu", "Luffy"],
        "condition": ["PSA10", "PSA 10", "Mint", "Near Mint", "Holo"],
        "series": ["BBM 2024", "Pokemon Carddass", "Topps"],
        "price_band": {
            "low": (0.0, 100.0),
            "mid": (100.0, 300.0),
            "high": (300.0, 1000.0),
            "premium": (1000.0, 999999.0),
        },
    }


def test_character_tag_case_insensitive_partial_match() -> None:
    tags = tag_product("shohei ohtani bbm card", 120.0, dictionaries=_dicts())
    assert "Ohtani" in tags["character"]
    assert "Shohei Ohtani" in tags["character"]


def test_character_tag_multiple_matches() -> None:
    tags = tag_product("Pikachu and Luffy crossover", 80.0, dictionaries=_dicts())
    assert tags["character"] == ["Pikachu", "Luffy"]


def test_condition_psa10_without_space() -> None:
    tags = tag_product("Ohtani PSA10 graded", 500.0, dictionaries=_dicts())
    assert "PSA10" in tags["condition"]


def test_condition_psa_10_with_space() -> None:
    tags = tag_product("Ohtani PSA 10 graded", 500.0, dictionaries=_dicts())
    assert "PSA 10" in tags["condition"]


def test_condition_near_mint_partial_match() -> None:
    tags = tag_product("Pokemon Holo Near Mint card", 150.0, dictionaries=_dicts())
    assert "Near Mint" in tags["condition"]
    assert "Mint" in tags["condition"]
    assert "Holo" in tags["condition"]


def test_series_tag_extraction() -> None:
    tags = tag_product("Shohei Ohtani BBM 2024 rare card", 350.0, dictionaries=_dicts())
    assert tags["series"] == ["BBM 2024"]


def test_series_tag_case_insensitive() -> None:
    tags = tag_product("pokemon carddass pikachu", 75.0, dictionaries=_dicts())
    assert tags["series"] == ["Pokemon Carddass"]


def test_price_band_low() -> None:
    assert tag_product("x", 99.99, dictionaries=_dicts())["price_band"] == ["low"]


def test_price_band_mid_boundary() -> None:
    assert tag_product("x", 100.0, dictionaries=_dicts())["price_band"] == ["mid"]


def test_price_band_high_boundary() -> None:
    assert tag_product("x", 300.0, dictionaries=_dicts())["price_band"] == ["high"]


def test_price_band_premium_boundary() -> None:
    assert tag_product("x", 1000.0, dictionaries=_dicts())["price_band"] == ["premium"]


def test_multiple_tag_categories_at_once() -> None:
    tags = tag_product("Shohei Ohtani BBM 2024 PSA10 Mint", 864.0, dictionaries=_dicts())
    assert "Ohtani" in tags["character"]
    assert "PSA10" in tags["condition"]
    assert "Mint" in tags["condition"]
    assert tags["series"] == ["BBM 2024"]
    assert tags["price_band"] == ["high"]


def test_no_matches_returns_empty_lists() -> None:
    tags = tag_product("Unknown plain item", 2_000_000.0, dictionaries=_dicts())
    assert tags == {
        "character": [],
        "condition": [],
        "series": [],
        "price_band": [],
    }


def test_load_keyword_tags_missing_file_returns_empty(tmp_path: Path) -> None:
    assert load_keyword_tags(tmp_path / "missing.json") == []


def test_load_price_bands_invalid_json_returns_empty(tmp_path: Path) -> None:
    p = tmp_path / "price_bands.json"
    p.write_text("{bad", encoding="utf-8")
    assert load_price_bands(p) == {}


def test_load_tag_dictionaries_reads_all_files(tmp_path: Path) -> None:
    (tmp_path / "characters.json").write_text(json.dumps(["Ichiro"]), encoding="utf-8")
    (tmp_path / "conditions.json").write_text(json.dumps(["Mint"]), encoding="utf-8")
    (tmp_path / "series.json").write_text(json.dumps(["Topps"]), encoding="utf-8")
    (tmp_path / "price_bands.json").write_text(json.dumps({"low": [0, 100]}), encoding="utf-8")
    d = load_tag_dictionaries(tmp_path)
    assert d["character"] == ["Ichiro"]
    assert d["condition"] == ["Mint"]
    assert d["series"] == ["Topps"]
    assert d["price_band"] == {"low": (0.0, 100.0)}
