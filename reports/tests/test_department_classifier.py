"""department_classifier の単体テスト。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from reports.department_classifier import (
    DepartmentProfile,
    classify_title,
    load_department_profiles,
    score_department,
)


@pytest.fixture()
def tmp_sourcing(tmp_path: Path) -> Path:
    root = tmp_path / "sourcing"
    # dept A
    a = root / "alpha"
    a.mkdir(parents=True)
    (a / "keywords.json").write_text(
        json.dumps(
            {
                "card_keywords": ["AlphaCard", "Rare Alpha"],
                "ebay_keywords": ["ALPHA-EBAY"],
                "ng_keywords": ["blocked-a"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    # dept B — alpha と重複しうるキーワード数で負ける
    b = root / "beta"
    b.mkdir(parents=True)
    (b / "keywords.json").write_text(
        json.dumps(
            {
                "card_keywords": ["BetaOnly"],
                "ng_keywords": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return root


def test_load_department_profiles_discovers_json(tmp_sourcing: Path) -> None:
    profiles = load_department_profiles(tmp_sourcing)
    folders = {p.folder for p in profiles}
    assert folders == {"alpha", "beta"}


def test_single_keyword_match(tmp_sourcing: Path) -> None:
    profiles = load_department_profiles(tmp_sourcing)
    key, label = classify_title("My ALPHA-EBAY listing", profiles)
    assert key == "alpha"


def test_multiple_departments_highest_score_wins(tmp_sourcing: Path) -> None:
    profiles = load_department_profiles(tmp_sourcing)
    title = "AlphaCard BetaOnly Rare Alpha"  # alpha:3, beta:1
    key, _ = classify_title(title, profiles)
    assert key == "alpha"


def test_unclassified_when_no_match(tmp_sourcing: Path) -> None:
    profiles = load_department_profiles(tmp_sourcing)
    key, label = classify_title("Completely unrelated title", profiles)
    assert key == "未分類"
    assert label == "未分類"


def test_case_insensitive(tmp_sourcing: Path) -> None:
    profiles = load_department_profiles(tmp_sourcing)
    key, _ = classify_title("alpha-ebay is here", profiles)
    assert key == "alpha"


def test_ng_keyword_zeroes_score(tmp_sourcing: Path) -> None:
    profiles = load_department_profiles(tmp_sourcing)
    title = "AlphaCard blocked-a Rare Alpha"
    p_alpha = next(p for p in profiles if p.folder == "alpha")
    assert score_department(title.lower(), p_alpha) == 0


def test_tie_breaker_stable_order(tmp_path: Path) -> None:
    """同点ならフォルダ名の辞書順で先勝ち。"""
    root = tmp_path / "sourcing"
    for name, kw in (("m_dept", "sharedkw"), ("a_dept", "sharedkw")):
        d = root / name
        d.mkdir(parents=True)
        (d / "keywords.json").write_text(
            json.dumps({"card_keywords": [kw]}, ensure_ascii=False),
            encoding="utf-8",
        )
    profiles = load_department_profiles(root)
    key, _ = classify_title("prefix sharedkw suffix", profiles)
    assert key == "a_dept"


def test_score_department_counts_distinct_keywords() -> None:
    p = DepartmentProfile(
        folder="x",
        display_name="X",
        keywords=("a", "b"),
        ng_keywords=(),
    )
    assert score_department("a and b here", p) == 2
