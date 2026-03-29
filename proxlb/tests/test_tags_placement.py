"""
Unit-testing node placement when using balancing.tags (and pools ignore) rules.
"""

__author__ = "Peter Dreuw <archandha>"
__copyright__ = "Copyright (C) 2026 Peter Dreuw (@archandha) for credativ GmbH"
__license__ = "GPL-3.0"

from typing import Any, Dict

from models.tags import Tags
from models.pools import Pools
from models.calculations import Calculations
from utils.host_filter import (
    collect_matching_tag_rules,
    merge_pin_ignore,
    filter_candidate_nodes,
)


def _cluster_nodes(*names: str) -> Dict[str, Any]:
    """Shape expected by Helper.validate_node_presence."""
    return {"nodes": {n: {} for n in names}}


def _cfg(tags: Dict[str, Any] = None, pools: Dict[str, Any] = None) -> Dict[str, Any]:
    balancing: Dict[str, Any] = {}
    if tags is not None:
        balancing["tags"] = tags
    if pools is not None:
        balancing["pools"] = pools
    return {"balancing": balancing}


# --- balancing.tags affinity / anti-affinity groups ---


def test_affinity_group_from_balancing_tags_type() -> None:
    proxlb = _cfg(
        tags={
            "app_a": {"type": "affinity"},
        }
    )
    groups = Tags.get_affinity_groups(["app_a", "other"], [], [], proxlb)
    assert "app_a" in groups
    assert "other" not in groups


def test_anti_affinity_group_from_balancing_tags_type() -> None:
    proxlb = _cfg(
        tags={
            "svc_x": {"type": "anti-affinity"},
        }
    )
    groups = Tags.get_anti_affinity_groups(["svc_x"], [], [], proxlb)
    assert "svc_x" in groups


def test_balancing_tags_coexists_with_plb_affinity_prefix() -> None:
    proxlb = _cfg(tags={"plain": {"type": "affinity"}})
    groups = Tags.get_affinity_groups(["plb_affinity_z", "plain"], [], [], proxlb)
    assert "plb_affinity_z" in groups
    assert "plain" in groups


# --- Tags.get_node_relationships (balancing.tags pin intersection) ---


def test_single_balancing_tags_pin() -> None:
    nodes = _cluster_nodes("n1", "n2", "n3")
    proxlb = _cfg(tags={"role": {"pin": ["n1", "n2"]}})
    out = Tags.get_node_relationships(["role"], nodes, [], [], proxlb)
    assert sorted(out) == ["n1", "n2"]


def test_two_tags_pin_intersection() -> None:
    nodes = _cluster_nodes("n1", "n2", "n3")
    proxlb = _cfg(
        tags={
            "a": {"pin": ["n1", "n2"]},
            "b": {"pin": ["n2", "n3"]},
        }
    )
    out = Tags.get_node_relationships(["a", "b"], nodes, [], [], proxlb)
    assert out == ["n2"]


def test_conflicting_pin_intersection_yields_empty() -> None:
    nodes = _cluster_nodes("n1", "n2")
    proxlb = _cfg(
        tags={
            "a": {"pin": ["n1"]},
            "b": {"pin": ["n2"]},
        }
    )
    out = Tags.get_node_relationships(["a", "b"], nodes, [], [], proxlb)
    assert out == []


def test_balancing_tags_pin_intersects_with_pool_pins() -> None:
    nodes = _cluster_nodes("n1", "n2", "n3")
    proxlb = _cfg(
        tags={"t": {"pin": ["n2", "n3"]}},
        pools={"p1": {"type": "affinity", "pin": ["n1", "n2"]}},
    )
    out = Tags.get_node_relationships(["t"], nodes, ["p1"], [], proxlb)
    assert out == ["n2"]


def test_pool_pins_only_when_no_balancing_tags_pin() -> None:
    nodes = _cluster_nodes("n1", "n2")
    proxlb = _cfg(
        tags={"t": {"ignore": ["n2"]}},
        pools={"p1": {"type": "affinity", "pin": ["n1", "n2"]}},
    )
    out = Tags.get_node_relationships(["t"], nodes, ["p1"], [], proxlb)
    assert sorted(out) == ["n1", "n2"]


def test_plb_pin_intersects_with_balancing_tags_pin() -> None:
    nodes = _cluster_nodes("n1", "n2", "n3")
    proxlb = _cfg(tags={"t": {"pin": ["n2", "n3"]}})
    out = Tags.get_node_relationships(["plb_pin_n2", "t"], nodes, [], [], proxlb)
    assert out == ["n2"]


def test_invalid_node_in_balancing_tags_pin_dropped() -> None:
    nodes = _cluster_nodes("n1")
    proxlb = _cfg(tags={"t": {"pin": ["n1", "ghost"]}})
    out = Tags.get_node_relationships(["t"], nodes, [], [], proxlb)
    assert out == ["n1"]


def test_pin_and_ignore_on_same_tag_skipped() -> None:
    nodes = _cluster_nodes("n1", "n2")
    proxlb = _cfg(tags={"bad": {"pin": ["n1"], "ignore": ["n2"]}})
    out = Tags.get_node_relationships(["bad"], nodes, [], [], proxlb)
    assert out == []


# --- collect_node_ignore_list ---


def test_tag_ignore_only() -> None:
    nodes = _cluster_nodes("n1", "n2")
    proxlb = _cfg(tags={"x": {"ignore": ["n2"]}})
    out = Tags.collect_node_ignore_list(["x"], [], nodes, proxlb)
    assert out == ["n2"]


def test_pool_ignore_only() -> None:
    nodes = _cluster_nodes("a", "b")
    proxlb = _cfg(pools={"pool1": {"type": "affinity", "ignore": ["b"]}})
    out = Tags.collect_node_ignore_list([], ["pool1"], nodes, proxlb)
    assert out == ["b"]


def test_union_tag_and_pool_ignore_sorted_unique() -> None:
    nodes = _cluster_nodes("n1", "n2", "n3")
    proxlb = _cfg(
        tags={"t": {"ignore": ["n2", "n3"]}},
        pools={"p": {"ignore": ["n2"]}},
    )
    out = Tags.collect_node_ignore_list(["t"], ["p"], nodes, proxlb)
    assert out == ["n2", "n3"]


def test_pin_and_ignore_same_tag_excluded_from_ignore_list() -> None:
    nodes = _cluster_nodes("n1", "n2")
    proxlb = _cfg(tags={"bad": {"pin": ["n1"], "ignore": ["n2"]}})
    out = Tags.collect_node_ignore_list(["bad"], [], nodes, proxlb)
    assert out == []


# --- Pools.get_merged_pin_strictness ---


def test_no_pools_tag_pin_strict_false() -> None:
    proxlb = _cfg(tags={"t": {"pin": ["n1"], "strict": False}})
    assert Pools.get_merged_pin_strictness(proxlb, [], ["t"]) is False


def test_no_pools_tag_pin_default_strict_true() -> None:
    proxlb = _cfg(tags={"t": {"pin": ["n1"]}})
    assert Pools.get_merged_pin_strictness(proxlb, [], ["t"]) is True


def test_pool_strict_true_or_tag_strict_false() -> None:
    proxlb = _cfg(
        tags={"t": {"pin": ["n1"], "strict": False}},
        pools={"p": {"type": "affinity", "strict": True}},
    )
    assert Pools.get_merged_pin_strictness(proxlb, ["p"], ["t"]) is True


def test_ignore_only_tag_does_not_force_strict() -> None:
    proxlb = _cfg(tags={"t": {"ignore": ["n1"]}})
    assert Pools.get_merged_pin_strictness(proxlb, [], ["t"]) is False


# --- host_filter helpers (tag placement) ---


def test_collect_matching_tag_rules_priority_order() -> None:
    cfg = {
        "low": {"ignore": ["a"], "priority": 1},
        "high": {"ignore": ["b"], "priority": 99},
    }
    rules = collect_matching_tag_rules(["low", "high"], cfg)
    assert rules[0]["priority"] == 99
    assert rules[1]["priority"] == 1


def test_merge_pin_ignore_combined_with_ignore_lists() -> None:
    pin, ign = merge_pin_ignore([["n1", "n2"], ["n2"]], [["n3"]])
    assert pin == {"n2"}
    assert ign == {"n3"}


def test_filter_candidate_nodes_pin_filter_plus_ignore() -> None:
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


# --- val_anti_affinity + node_ignore_list ---


def test_val_anti_affinity_picks_first_eligible_not_in_ignore_list() -> None:
    proxlb_data = {
        "nodes": {
            "n1": {"name": "n1", "maintenance": False},
            "n2": {"name": "n2", "maintenance": False},
            "n3": {"name": "n3", "maintenance": False},
        },
        "groups": {
            "anti_affinity": {
                "grp": {
                    "guests": ["vm1", "vm2"],
                    "counter": 2,
                    "used_nodes": [],
                }
            }
        },
        "guests": {
            "vm1": {
                "processed": False,
                "node_ignore_list": ["n1"],
            }
        },
        "meta": {"balancing": {}},
    }
    Calculations.val_anti_affinity(proxlb_data, "vm1")
    assert proxlb_data["meta"]["balancing"]["balance_next_node"] == "n2"
    assert proxlb_data["groups"]["anti_affinity"]["grp"]["used_nodes"] == ["n2"]


def test_val_anti_affinity_skips_ignored_until_eligible() -> None:
    proxlb_data = {
        "nodes": {
            "n1": {"name": "n1", "maintenance": False},
            "n2": {"name": "n2", "maintenance": False},
        },
        "groups": {
            "anti_affinity": {
                "grp": {
                    "guests": ["vm1"],
                    "counter": 2,
                    "used_nodes": [],
                }
            }
        },
        "guests": {
            "vm1": {
                "processed": False,
                "node_ignore_list": ["n1"],
            }
        },
        "meta": {"balancing": {}},
    }
    Calculations.val_anti_affinity(proxlb_data, "vm1")
    assert proxlb_data["meta"]["balancing"]["balance_next_node"] == "n2"


# --- get_most_free_node + ignores ---


def test_get_most_free_node_chooses_least_loaded_among_non_ignored() -> None:
    proxlb_data = {
        "nodes": {
            "n1": {
                "name": "n1",
                "maintenance": False,
                "memory_used_percent": 5.0,
            },
            "n2": {
                "name": "n2",
                "maintenance": False,
                "memory_used_percent": 80.0,
            },
            "n3": {
                "name": "n3",
                "maintenance": False,
                "memory_used_percent": 10.0,
            },
        },
        "meta": {"balancing": {"method": "memory", "mode": "used"}},
    }
    node = Calculations.get_most_free_node(
        proxlb_data,
        return_node=False,
        guest_node_relation_list=None,
        guest_ignore_nodes=["n1"],
    )
    assert node is not None
    assert node["name"] == "n3"


def test_get_most_free_node_all_candidates_ignored_returns_none() -> None:
    proxlb_data = {
        "nodes": {
            "n1": {
                "name": "n1",
                "maintenance": False,
                "memory_used_percent": 10.0,
            },
        },
        "meta": {"balancing": {"method": "memory", "mode": "used"}},
    }
    node = Calculations.get_most_free_node(
        proxlb_data,
        return_node=False,
        guest_node_relation_list=None,
        guest_ignore_nodes=["n1"],
    )
    assert node is None
    assert proxlb_data["meta"]["balancing"]["balance_next_node"] is None
