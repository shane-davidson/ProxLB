"""
Pure helpers for filtering hypervisor nodes by maintenance, pin lists, and ignore lists.
Used by balancing placement (get_most_free_node, anti-affinity, etc.).
"""

__author__ = "ProxLB"
__license__ = "GPL-3.0"

from typing import Any, Dict, List, Optional, Set, Tuple


def collect_matching_tag_rules(guest_tags: List[str], tags_cfg: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Return rule dicts from balancing.tags for tags present on the guest, sorted by priority descending.
    Skips invalid entries that define both pin and ignore.
    """
    if not tags_cfg or not guest_tags:
        return []
    rules: List[Tuple[int, Dict[str, Any], str]] = []
    for tag in guest_tags:
        if tag not in tags_cfg:
            continue
        rule = tags_cfg[tag]
        if not isinstance(rule, dict):
            continue
        has_pin = bool(rule.get("pin"))
        has_ignore = bool(rule.get("ignore"))
        if has_pin and has_ignore:
            continue
        priority = rule.get("priority", 0)
        try:
            priority = int(priority)
        except (TypeError, ValueError):
            priority = 0
        rules.append((priority, rule, tag))
    rules.sort(key=lambda x: (-x[0], x[2]))
    return [r[1] for r in rules]


def merge_pin_ignore(
    pin_lists: List[List[str]],
    ignore_lists: List[List[str]],
) -> Tuple[Optional[Set[str]], Set[str]]:
    """
    pin_lists: each inner list from a 'pin' rule; intersection across non-empty.
    ignore_lists: union of all ignore nodes.

    Returns (effective_pin_set or None if no pin rules, ignored_nodes set).
    """
    ignored: Set[str] = set()
    for lst in ignore_lists:
        for n in lst or []:
            if n:
                ignored.add(n)

    non_empty_pins = [p for p in pin_lists if p]
    if not non_empty_pins:
        return None, ignored

    intersection: Optional[Set[str]] = None
    for lst in non_empty_pins:
        s = set(lst)
        if intersection is None:
            intersection = s
        else:
            intersection &= s
    return intersection if intersection is not None else set(), ignored


def filter_candidate_nodes(
    nodes_dict: Dict[str, Any],
    *,
    maintenance: bool = True,
    pin_nodes: Optional[Set[str]] = None,
    ignore_nodes: Optional[Set[str]] = None,
) -> List[Any]:
    """
    Return list of node dicts: not in maintenance (if maintenance=True), in pin_nodes if set,
    and not in ignore_nodes.
    nodes_dict maps node name -> node metadata dict with 'name' and 'maintenance' keys.
    """
    ignore_nodes = ignore_nodes or set()
    out: List[Any] = []
    for node in nodes_dict.values():
        name = node.get("name")
        if not name:
            continue
        if maintenance and node.get("maintenance"):
            continue
        if name in ignore_nodes:
            continue
        if pin_nodes is not None and name not in pin_nodes:
            continue
        out.append(node)
    return out


def any_pin_rule_strict(matching_rules: List[Dict[str, Any]]) -> bool:
    """True if any matching rule with pin has strict True (default True when pin is set)."""
    for rule in matching_rules:
        if not rule.get("pin"):
            continue
        if rule.get("strict", True):
            return True
    return False
