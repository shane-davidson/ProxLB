"""
Tests for pinning_mode (always vs load-based), effective scope merge, and pin violation helpers.
"""

__license__ = "GPL-3.0"

from typing import Any, Dict

from models.calculations import Calculations
from models.pools import (
    PINNING_MODE_ALWAYS,
    PINNING_MODE_LOAD_BASED,
    Pools,
    normalize_pinning_mode,
)


def _cfg(
    balancing: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if balancing is not None:
        out["balancing"] = balancing
    return out


def test_normalize_pinning_mode_values() -> None:
    assert normalize_pinning_mode("always") == PINNING_MODE_ALWAYS
    assert normalize_pinning_mode("ALWAYS") == PINNING_MODE_ALWAYS
    assert normalize_pinning_mode("load-based") == PINNING_MODE_LOAD_BASED
    assert normalize_pinning_mode("load_based") == PINNING_MODE_LOAD_BASED
    assert normalize_pinning_mode(None) is None


def test_normalize_pinning_mode_invalid_falls_back() -> None:
    assert normalize_pinning_mode("bogus") == PINNING_MODE_LOAD_BASED


def test_get_effective_pinning_mode_default() -> None:
    assert Pools.get_effective_pinning_mode(_cfg({}), [], []) == PINNING_MODE_LOAD_BASED


def test_get_effective_pinning_mode_balancing_default() -> None:
    proxlb = _cfg({"pinning_mode": PINNING_MODE_ALWAYS})
    assert Pools.get_effective_pinning_mode(proxlb, [], []) == PINNING_MODE_ALWAYS


def test_get_effective_pinning_mode_tag_dominance_any_always() -> None:
    proxlb = _cfg(
        {
            "pinning_mode": PINNING_MODE_LOAD_BASED,
            "tags": {
                "a": {"pinning_mode": PINNING_MODE_LOAD_BASED},
                "b": {"pinning_mode": PINNING_MODE_ALWAYS},
            },
        }
    )
    assert Pools.get_effective_pinning_mode(proxlb, [], ["a", "b"]) == PINNING_MODE_ALWAYS


def test_get_effective_pinning_mode_pool_overrides_tag() -> None:
    proxlb = _cfg(
        {
            "pinning_mode": PINNING_MODE_LOAD_BASED,
            "tags": {"t": {"pinning_mode": PINNING_MODE_ALWAYS}},
            "pools": {"p1": {"pinning_mode": PINNING_MODE_LOAD_BASED}},
        }
    )
    assert Pools.get_effective_pinning_mode(proxlb, ["p1"], ["t"]) == PINNING_MODE_LOAD_BASED


def test_get_effective_pinning_mode_pool_any_always() -> None:
    proxlb = _cfg(
        {
            "pinning_mode": PINNING_MODE_LOAD_BASED,
            "pools": {
                "p1": {"pinning_mode": PINNING_MODE_LOAD_BASED},
                "p2": {"pinning_mode": PINNING_MODE_ALWAYS},
            },
        }
    )
    assert Pools.get_effective_pinning_mode(proxlb, ["p1", "p2"], []) == PINNING_MODE_ALWAYS


def test_guest_has_pin_violation() -> None:
    proxlb_data = {
        "guests": {
            "g1": {
                "node_relationships": ["n1", "n2"],
                "node_current": "n3",
            }
        }
    }
    assert Calculations.guest_has_pin_violation(proxlb_data, "g1") is True
    proxlb_data["guests"]["g1"]["node_current"] = "n1"
    assert Calculations.guest_has_pin_violation(proxlb_data, "g1") is False


def test_guest_has_pin_violation_empty_relationships() -> None:
    proxlb_data = {"guests": {"g1": {"node_relationships": [], "node_current": "n3"}}}
    assert Calculations.guest_has_pin_violation(proxlb_data, "g1") is False


def _base_node(
    name: str,
    *,
    memory_used_percent: float,
    memory_total: int = 100_000_000_000,
) -> Dict[str, Any]:
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


def test_relocate_guests_bypasses_hottest_when_always_and_violation() -> None:
    """Guest on low-load node with pin violation + always: still get node_target from pin logic."""
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
            "n1": _base_node("n1", memory_used_percent=90.0),
            "n2": _base_node("n2", memory_used_percent=50.0),
            "n3": _base_node("n3", memory_used_percent=10.0),
        },
        "groups": {
            "affinity": {
                "grp1": {
                    "guests": ["vm1"],
                    "counter": 1,
                    "memory_used": 1_000_000_000,
                    "cpu_total": 2,
                    "cpu_used": 0,
                    "memory_total": 4_000_000_000,
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
                "node_relationships": ["n1", "n2"],
                "node_relationships_strict": True,
                "node_ignore_list": [],
                "pools": [],
                "tags": [],
                "effective_pinning_mode": PINNING_MODE_ALWAYS,
            }
        },
    }

    Calculations.relocate_guests(proxlb_data)

    assert proxlb_data["guests"]["vm1"]["node_target"] == "n2"


def test_relocate_guests_respects_hottest_when_load_based_violation() -> None:
    """load-based + violation: hottest gate still applies; guest on cold node skipped."""
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
            "n1": _base_node("n1", memory_used_percent=90.0),
            "n2": _base_node("n2", memory_used_percent=50.0),
            "n3": _base_node("n3", memory_used_percent=10.0),
        },
        "groups": {
            "affinity": {
                "grp1": {
                    "guests": ["vm1"],
                    "counter": 1,
                    "memory_used": 1_000_000_000,
                    "cpu_total": 2,
                    "cpu_used": 0,
                    "memory_total": 4_000_000_000,
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
                "node_relationships": ["n1", "n2"],
                "node_relationships_strict": True,
                "node_ignore_list": [],
                "pools": [],
                "tags": [],
                "effective_pinning_mode": PINNING_MODE_LOAD_BASED,
            }
        },
    }

    Calculations.relocate_guests(proxlb_data)

    assert proxlb_data["guests"]["vm1"]["node_target"] == "n3"
