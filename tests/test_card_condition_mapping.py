import ast
import logging
import re
from pathlib import Path
from typing import Optional, Tuple


ROOT = Path(__file__).resolve().parents[1]


def _load_condition_namespace():
    source = (ROOT / "auto_lister.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    wanted_names = {
        "EBAY_CARD_GRADED_CONDITION_ID",
        "EBAY_CARD_UNGRADED_CONDITION_ID",
        "EBAY_CARD_CONDITION_DESCRIPTOR_NAME_ID",
        "EBAY_CARD_UNGRADED_DESCRIPTOR_VALUE",
        "EBAY_CARD_EXCELLENT_DESCRIPTOR_VALUE",
        "EBAY_CARD_VERY_GOOD_DESCRIPTOR_VALUE",
        "EBAY_CARD_POOR_DESCRIPTOR_VALUE",
        "EBAY_CARD_GRADER_DESCRIPTOR_NAME_ID",
        "EBAY_CARD_GRADE_DESCRIPTOR_NAME_ID",
        "MERCARI_CARD_CONDITION_DESCRIPTOR_BY_LABEL",
        "EBAY_CARD_GRADER_DESCRIPTOR_VALUE_BY_NAME",
        "EBAY_CARD_GRADE_DESCRIPTOR_VALUE_BY_GRADE",
        "_GRADED_CARD_RE",
    }
    wanted_functions = {
        "_normalize_card_grade",
        "_detect_graded_card",
        "_map_mercari_label_to_ebay_card_descriptor_value",
        "map_mercari_label_to_ebay_condition_id",
        "_build_graded_card_condition_descriptors_xml",
    }

    nodes = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            target_names = {target.id for target in node.targets if isinstance(target, ast.Name)}
            if target_names & wanted_names:
                nodes.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in wanted_functions:
            nodes.append(node)

    module = ast.Module(body=nodes, type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {
        "re": re,
        "logger": logging.getLogger("test_card_condition_mapping"),
        "Optional": Optional,
        "Tuple": Tuple,
    }
    exec(compile(module, str(ROOT / "auto_lister.py"), "exec"), namespace)
    return namespace


NS = _load_condition_namespace()
map_condition = NS["map_mercari_label_to_ebay_condition_id"]


def test_new_unused_maps_to_near_mint_or_better():
    assert map_condition("新品、未使用", "", "") == "400010"


def test_like_new_maps_to_near_mint_or_better():
    assert map_condition("未使用に近い", "", "") == "400010"


def test_no_obvious_damage_maps_to_near_mint_or_better():
    assert map_condition("目立った傷や汚れなし", "", "") == "400010"


def test_slight_damage_maps_to_excellent():
    assert map_condition("やや傷や汚れあり", "", "") == "400011"


def test_damage_maps_to_very_good():
    assert map_condition("傷や汚れあり", "", "") == "400012"


def test_bad_condition_maps_to_poor():
    assert map_condition("全体的に状態が悪い", "", "") == "400013"


def test_psa10_title_maps_to_graded():
    assert map_condition("全体的に状態が悪い", "PSA10 Pikachu", "") == "2750"


def test_bgs95_description_maps_to_graded():
    assert map_condition("新品、未使用", "", "BGS 9.5 certified card") == "2750"


def test_cgc9_title_maps_to_graded():
    assert map_condition("目立った傷や汚れなし", "CGC9 One Piece", "") == "2750"


def test_graded_detection_is_case_insensitive():
    assert map_condition("傷や汚れあり", "psa 10 charizard", "") == "2750"


def test_empty_label_falls_back_to_excellent(caplog):
    with caplog.at_level(logging.WARNING, logger="test_card_condition_mapping"):
        assert map_condition("", "", "") == "400011"
    assert "メルカリラベル不明のためデフォルト Excellent を使用" in caplog.text


def test_unknown_label_falls_back_to_excellent(caplog):
    with caplog.at_level(logging.WARNING, logger="test_card_condition_mapping"):
        assert map_condition("状態未設定", "", "") == "400011"
    assert "メルカリラベル不明のためデフォルト Excellent を使用" in caplog.text


def test_graded_descriptor_xml_contains_grader_and_grade_values():
    xml = NS["_build_graded_card_condition_descriptors_xml"]("CGC 9 card", "")
    assert "<Name>27501</Name>" in xml
    assert "<Value>275015</Value>" in xml
    assert "<Name>27502</Name>" in xml
    assert "<Value>275022</Value>" in xml


def test_grade_five_uses_official_ebay_descriptor_value():
    xml = NS["_build_graded_card_condition_descriptors_xml"]("PSA 5 card", "")
    assert "<Value>2750210</Value>" in xml


def test_dot_zero_grade_normalizes_to_integer_grade():
    xml = NS["_build_graded_card_condition_descriptors_xml"]("BGS 8.0 card", "")
    assert "<Value>275024</Value>" in xml
