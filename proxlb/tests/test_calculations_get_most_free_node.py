"""
Unit-testing static method get_most_free_node in class Calculations
in calculations.py for edge cases where no nodes are available for balancing.
"""

__author__ = "Peter Dreuw <archandha>"
__copyright__ = "Copyright (C) 2026 Peter Dreuw (@archandha) for credativ GmbH"
__license__ = "GPL-3.0"


import pytest

from models.calculations import Calculations


def test_get_most_free_node_crash_repro_fix24() -> None:
    """Test case where all nodes are in maintainance mode"""
    proxlb_data = {
        "nodes": {
            "node1": {"name": "node1", "maintenance": True, "cpu_avg_percent": 10},
            "node2": {"name": "node2", "maintenance": True, "cpu_avg_percent": 20},
        },
        "meta": {"balancing": {}},
    }

    result = Calculations.get_most_free_node(proxlb_data, return_node=False)

    assert result is None, "Expected None when no nodes are available for balancing."
    assert (
        proxlb_data["meta"]["balancing"]["balance_next_node"] is None
    ), "Expected balance_next_node to be None."


def test_min_usage_with_empty_nodes() -> None:
    """
    Test the case where there are no nodes available (empty nodes dict).
    """
    proxlb_data = {
        "nodes": {},
        "meta": {"balancing": {}},
    }  # Simulate empty data

    node = Calculations.get_most_free_node(proxlb_data, return_node=False)

    assert node is None, "Expected None when no nodes are available."
    assert (
        proxlb_data["meta"]["balancing"]["balance_next_node"] is None
    ), "Expected balance_next_node to be None."


def test_get_most_free_node_excludes_ignored_nodes() -> None:
    proxlb_data = {
        "nodes": {
            "n1": {
                "name": "n1",
                "maintenance": False,
                "memory_used_percent": 10.0,
            },
            "n2": {
                "name": "n2",
                "maintenance": False,
                "memory_used_percent": 50.0,
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
    assert node["name"] == "n2"
    assert proxlb_data["meta"]["balancing"]["balance_next_node"] == "n2"
