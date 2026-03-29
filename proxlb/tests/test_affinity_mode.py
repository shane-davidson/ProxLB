"""Tests for affinity_mode (affinity + anti-affinity) and hottest-node bypass."""

__license__ = "GPL-3.0"

from typing import Any, Dict

from models.calculations import Calculations
from models.pools import PINNING_MODE_ALWAYS, PINNING_MODE_LOAD_BASED, Pools, normalize_affinity_mode


def _cfg(balancing: Dict[str, Any] | None = None) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if balancing is not None:
        out["balancing"] = balancing
    return out


def test_get_effective_affinity_mode_default() -> None:
    assert Pools.get_effective_affinity_mode(_cfg({}), [], []) == PINNING_MODE_LOAD_BASED


def test_get_effective_affinity_mode_pool_overrides_tag() -> None:
    proxlb = _cfg(
        {
            "affinity_mode": PINNING_MODE_LOAD_BASED,
            "tags": {"t": {"affinity_mode": PINNING_MODE_ALWAYS}},
            "pools": {"p1": {"affinity_mode": PINNING_MODE_LOAD_BASED}},
        }
    )
    assert Pools.get_effective_affinity_mode(proxlb, ["p1"], ["t"]) == PINNING_MODE_LOAD_BASED


def test_normalize_affinity_mode() -> None:
    assert normalize_affinity_mode("always") == PINNING_MODE_ALWAYS
    assert normalize_affinity_mode("invalid") == PINNING_MODE_LOAD_BASED


def test_guest_has_affinity_mode_violation_split_affinity_group() -> None:
    proxlb_data = {
        "groups": {"affinity": {"g1": {"guests": ["a", "b"]}}, "anti_affinity": {}},
        "guests": {
            "a": {"node_current": "n1"},
            "b": {"node_current": "n2"},
        },
        "nodes": {
            "n1": {"maintenance": False},
            "n2": {"maintenance": False},
        },
    }
    assert Calculations.guest_has_affinity_mode_violation(proxlb_data, "a") is True


def test_guest_has_affinity_mode_violation_anti_affinity_collision() -> None:
    proxlb_data = {
        "groups": {
            "affinity": {"uuid1": {"guests": ["a"]}},
            "anti_affinity": {"anti1": {"guests": ["a", "b"]}},
        },
        "guests": {
            "a": {"node_current": "n1"},
            "b": {"node_current": "n1"},
        },
        "nodes": {"n1": {"maintenance": False}},
    }
    assert Calculations.validate_current_anti_affinity(proxlb_data, "a") is False
    assert Calculations.guest_has_affinity_mode_violation(proxlb_data, "a") is True


def _base_node(name: str, memory_used_percent: float, memory_total: int = 100_000_000_000) -> Dict[str, Any]:
    mem_used = int(memory_total * memory_used_percent / 100.0)
    return {
        "name": name,
        "maintenance": False,
        "ignore": False,
        "memory_total": memory_total,
        "memory_used": mem_used,
        "memory_free": memory_total - mem_used,
        "memory_used_percent": memory_used_percent,
        "cpu_total": 100,
        "cpu_used": 0,
        "cpu_free": 100,
        "cpu_used_percent": 0.0,
        "disk_total": 1000,
        "disk_used": 0,
        "disk_free": 1000,
        "disk_used_percent": 0.0,
        "cpu_assigned": 0,
        "memory_assigned": 0,
        "disk_assigned": 0,
        "cpu_assigned_percent": 0.0,
        "memory_assigned_percent": 0.0,
        "disk_assigned_percent": 0.0,
    }


def test_relocate_guests_bypasses_hottest_for_affinity_mode_always() -> None:
    """Guest on cold node with split affinity group + affinity_mode always: still relocate."""
    proxlb_data: Dict[str, Any] = {
        "meta": {
            "balancing": {
                "balance": True,
                "enforce_affinity": False,
                "enforce_pinning": False,
                "method": "memory",
                "mode": "used",
                "balance_next_node": "n1",
            }
        },
        "nodes": {
            "n1": _base_node("n1", 90.0),
            "n2": _base_node("n2", 50.0),
            "n3": _base_node("n3", 10.0),
        },
        "groups": {
            "affinity": {
                "agroup": {
                    "guests": ["vm1", "vm2"],
                    "counter": 2,
                    "memory_used": 2_000_000_000,
                    "cpu_total": 4,
                    "cpu_used": 0,
                    "memory_total": 8_000_000_000,
                    "disk_total": 0,
                    "disk_used": 0,
                }
            },
            "anti_affinity": {},
        },
        "guests": {
            "vm1": {
                "name": "vm1",
                "node_current": "n3",
                "node_target": "n3",
                "processed": False,
                "ignore": False,
                "cpu_total": 2,
                "cpu_used": 0,
                "memory_total": 4_000_000_000,
                "memory_used": 1_000_000_000,
                "disk_total": 0,
                "disk_used": 0,
                "node_relationships": [],
                "node_relationships_strict": False,
                "node_ignore_list": [],
                "pools": [],
                "tags": [],
                "effective_pinning_mode": PINNING_MODE_LOAD_BASED,
                "effective_affinity_mode": PINNING_MODE_ALWAYS,
            },
            "vm2": {
                "name": "vm2",
                "node_current": "n1",
                "node_target": "n1",
                "processed": False,
                "ignore": False,
                "cpu_total": 2,
                "cpu_used": 0,
                "memory_total": 4_000_000_000,
                "memory_used": 1_000_000_000,
                "disk_total": 0,
                "disk_used": 0,
                "node_relationships": [],
                "node_relationships_strict": False,
                "node_ignore_list": [],
                "pools": [],
                "tags": [],
                "effective_pinning_mode": PINNING_MODE_LOAD_BASED,
                "effective_affinity_mode": PINNING_MODE_LOAD_BASED,
            },
        },
    }

    Calculations.relocate_guests(proxlb_data)

    assert proxlb_data["guests"]["vm1"]["node_target"] != "n3"


def test_skip_hottest_pin_or_affinity_or() -> None:
    assert Calculations._skip_hottest_node_gate(
        {
            "meta": {"balancing": {}},
            "guests": {
                "g": {
                    "effective_pinning_mode": PINNING_MODE_ALWAYS,
                    "effective_affinity_mode": PINNING_MODE_LOAD_BASED,
                    "pools": [],
                    "tags": [],
                    "node_relationships": ["n1"],
                    "node_current": "n2",
                }
            },
        },
        "g",
    )
    assert not Calculations._skip_hottest_node_gate(
        {
            "meta": {"balancing": {}},
            "guests": {
                "g": {
                    "effective_pinning_mode": PINNING_MODE_LOAD_BASED,
                    "effective_affinity_mode": PINNING_MODE_LOAD_BASED,
                    "pools": [],
                    "tags": [],
                    "node_relationships": [],
                    "node_current": "n1",
                }
            },
            "groups": {"affinity": {}, "anti_affinity": {}},
            "nodes": {"n1": {"maintenance": False}},
        },
        "g",
    )
