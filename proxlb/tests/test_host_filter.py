"""
Unit-testing utils.host_filter placement helpers.
"""

__author__ = "Peter Dreuw <archandha>"
__copyright__ = "Copyright (C) 2026 Peter Dreuw (@archandha) for credativ GmbH"
__license__ = "GPL-3.0"

import pytest

from utils.host_filter import (
    collect_matching_tag_rules,
    merge_pin_ignore,
    filter_candidate_nodes,
    any_pin_rule_strict,
)


def test_merge_pin_ignore_no_pins() -> None:
    pin, ign = merge_pin_ignore([], [["a", "b"]])
    assert pin is None
    assert ign == {"a", "b"}


def test_merge_pin_ignore_intersection() -> None:
    pin, ign = merge_pin_ignore([["a", "b"], ["b", "c"]], [])
    assert pin == {"b"}
    assert ign == set()


def test_merge_pin_ignore_empty_intersection() -> None:
    pin, ign = merge_pin_ignore([["a"], ["b"]], [])
    assert pin == set()
    assert ign == set()


def test_merge_pin_ignore_single_pin_list() -> None:
    pin, ign = merge_pin_ignore([["x", "y"]], [])
    assert pin == {"x", "y"}
    assert ign == set()


def test_merge_pin_ignore_combined_ignore_lists() -> None:
    pin, ign = merge_pin_ignore([["n1", "n2"], ["n2"]], [["n3"]])
    assert pin == {"n2"}
    assert ign == {"n3"}


def test_filter_candidate_nodes_respects_ignore() -> None:
    nodes = {
        "n1": {"name": "n1", "maintenance": False},
        "n2": {"name": "n2", "maintenance": False},
    }
    out = filter_candidate_nodes(nodes, ignore_nodes={"n1"})
    assert len(out) == 1
    assert out[0]["name"] == "n2"


def test_filter_candidate_nodes_maintenance_excluded() -> None:
    nodes = {
        "a": {"name": "a", "maintenance": True},
        "b": {"name": "b", "maintenance": False},
    }
    out = filter_candidate_nodes(nodes)
    assert [n["name"] for n in out] == ["b"]


def test_filter_candidate_nodes_pin_restricts() -> None:
    nodes = {
        "a": {"name": "a", "maintenance": False},
        "b": {"name": "b", "maintenance": False},
    }
    out = filter_candidate_nodes(nodes, pin_nodes={"b"})
    assert [n["name"] for n in out] == ["b"]


def test_filter_candidate_nodes_pin_and_ignore() -> None:
    nodes = {
        "n1": {"name": "n1", "maintenance": False},
        "n2": {"name": "n2", "maintenance": False},
        "n3": {"name": "n3", "maintenance": False},
    }
    out = filter_candidate_nodes(
        nodes,
        pin_nodes={"n1", "n2"},
        ignore_nodes={"n2"},
    )
    assert [x["name"] for x in out] == ["n1"]


def test_collect_matching_tag_rules_skips_invalid() -> None:
    cfg = {
        "good": {"type": "affinity", "ignore": ["x"]},
        "bad": {"pin": ["a"], "ignore": ["b"]},
    }
    rules = collect_matching_tag_rules(["good", "bad"], cfg)
    assert len(rules) == 1


def test_collect_matching_tag_rules_empty_config() -> None:
    assert collect_matching_tag_rules(["a"], None) == []
    assert collect_matching_tag_rules([], {"a": {"ignore": ["n"]}}) == []


def test_collect_matching_tag_rules_non_dict_rule_skipped() -> None:
    assert collect_matching_tag_rules(["bad"], {"bad": "not-a-dict"}) == []


def test_any_pin_rule_strict() -> None:
    assert any_pin_rule_strict([{"pin": ["a"], "strict": False}]) is False
    assert any_pin_rule_strict([{"pin": ["a"], "strict": True}]) is True
    assert any_pin_rule_strict([{"pin": ["a"]}]) is True
