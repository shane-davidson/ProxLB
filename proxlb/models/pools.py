"""
The Pools class retrieves all present pools defined on a Proxmox cluster
including the chield objects.
"""

__author__ = "Florian Paul Azim Hoberg <gyptazy>"
__copyright__ = "Copyright (C) 2025 Florian Paul Azim Hoberg (@gyptazy)"
__license__ = "GPL-3.0"


from typing import Any, Dict, List, Optional
from utils.logger import SystemdLogger
from utils.host_filter import collect_matching_tag_rules, any_pin_rule_strict
import time

logger = SystemdLogger()

PINNING_MODE_ALWAYS = "always"
PINNING_MODE_LOAD_BASED = "load-based"


def _normalize_always_load_based(value: Any, setting_label: str) -> Optional[str]:
    """
    Parse 'always' | 'load-based' for pinning_mode, affinity_mode, etc.
    Invalid values log a warning and map to load-based.
    """
    if value is None:
        return None
    s = str(value).strip().lower().replace("_", "-")
    if s == PINNING_MODE_ALWAYS:
        return PINNING_MODE_ALWAYS
    if s in (PINNING_MODE_LOAD_BASED, "loadbased"):
        return PINNING_MODE_LOAD_BASED
    logger.warning(
        f"Invalid {setting_label} value {value!r}; using {PINNING_MODE_LOAD_BASED!r}."
    )
    return PINNING_MODE_LOAD_BASED


def normalize_pinning_mode(value: Any) -> Optional[str]:
    """See _normalize_always_load_based."""
    return _normalize_always_load_based(value, "balancing.pinning_mode")


def normalize_affinity_mode(value: Any) -> Optional[str]:
    """Same values as pinning_mode: always | load-based (affinity + anti-affinity placement)."""
    return _normalize_always_load_based(value, "balancing.affinity_mode")


def _aggregate_always_load_based_modes(modes: List[str]) -> Optional[str]:
    """Dominance: any 'always' wins; else load-based if any mode present."""
    if not modes:
        return None
    if PINNING_MODE_ALWAYS in modes:
        return PINNING_MODE_ALWAYS
    return PINNING_MODE_LOAD_BASED


def _aggregate_pinning_modes(modes: List[str]) -> Optional[str]:
    return _aggregate_always_load_based_modes(modes)


class Pools:
    """
    The Pools class retrieves all present pools defined on a Proxmox cluster
    including the chield objects.

    Methods:
        __init__:
            Initializes the Pools class.

        get_pools(proxmox_api: any) -> Dict[str, Any]:
            Retrieve pool definitions and membership from the Proxmox cluster.
            Returns a dict with a top-level "pools" mapping each poolid to
            {"name": <poolid>, "members": [<member_names>...]}.
            This method does not collect per-member metrics or perform node filtering.
    """
    def __init__(self):
        """
        Initializes the Pools class with the provided ProxLB data.
        """

    @staticmethod
    def get_pools(proxmox_api: any) -> Dict[str, Any]:
        """
        Retrieve all pools and their members from a Proxmox cluster.

        Queries the Proxmox API for pool definitions and returns a dictionary
        containing each pool's id/name and a list of its member VM/CT names.
        This function does not perform per-member metric collection or node
        filtering — it only gathers pool membership information.

        Args:
            proxmox_api (any): Proxmox API client instance.

        Returns:
            Dict[str, Any]: Dictionary with a top-level "pools" key mapping poolid
                    to {"name": <poolid>, "members": [<member_names>...]}.
        """
        logger.debug("Starting: get_pools.")
        pools = {"pools": {}}

        # Pool objects: iterate over all pools in the cluster.
        # We keep pool members even if their nodes are ignored so resource accounting
        # for rebalancing remains correct and we avoid overprovisioning nodes.
        for pool in proxmox_api.pools.get():
            logger.debug(f"Got pool: {pool['poolid']}")
            pools['pools'][pool['poolid']] = {}
            pools['pools'][pool['poolid']]['name'] = pool['poolid']
            pools['pools'][pool['poolid']]['members'] = []

            # Fetch pool details and collect member names
            try:
                pool_details = proxmox_api.pools(pool['poolid']).get()
            except Exception as e:
                logger.error(f"Error fetching pool details for pool {pool['poolid']}: {e}")
                continue

            for member in pool_details.get("members", []):

                # We might also have objects without the key "name", e.g. storage pools
                if "name" not in member:
                    logger.debug(f"Skipping member without name in pool: {pool['poolid']}")
                    continue

                logger.debug(f"Got member: {member['name']} for pool: {pool['poolid']}")
                pools['pools'][pool['poolid']]['members'].append(member["name"])

        logger.debug("Finished: get_pools.")
        return pools

    @staticmethod
    def get_pools_for_guest(guest_name: str, pools: Dict[str, Any]) -> Dict[str, Any]:
        """
        Return the list of pool names that include the given guest.

        Args:
            guest_name (str): Name of the VM or CT to look up.
            pools (Dict[str, Any]): Pools structure as returned by get_pools(),
            expected to contain a top-level "pools" mapping each poolid to
            {"name": <poolid>, "members": [<member_names>...]}.

        Returns:
            list[str]: Names of pools the guest is a member of (empty list if none).
        """
        logger.debug("Starting: get_pools_for_guests.")
        guest_pools = []

        for pool in pools.items():
            for pool_id, pool_data in pool[1].items():

                if type(pool_data) is dict:
                    pool_name = pool_data.get("name", "")
                    pool_name_members = pool_data.get("members", [])

                    if guest_name in pool_name_members:
                        logger.debug(f"Guest: {guest_name} is member of Pool: {pool_name}.")
                        guest_pools.append(pool_name)
                    else:
                        logger.debug(f"Guest: {guest_name} is NOT member of Pool: {pool_name}.")

                else:
                    logger.debug(f"Pool data for pool_id {pool_id} is not a dict: {pool_data}")

        logger.debug("Finished: get_pools_for_guests.")
        return guest_pools

    @staticmethod
    def get_pool_node_affinity_strictness(proxlb_config: Dict[str, Any], guest_pools: list) -> bool:
        """
        Retrieve the node affinity strictness setting for a guest across its pools.

        The last matching pool in guest_pools order wins (same as historical behavior).
        """
        logger.debug("Starting: get_pool_node_affinity_strictness.")
        node_strictness = True
        pools_cfg = proxlb_config.get("balancing", {}).get("pools") or {}
        for pool in guest_pools:
            pool_settings = pools_cfg.get(pool, {})
            node_strictness = pool_settings.get("strict", True)
        logger.debug("Finished: get_pool_node_affinity_strictness.")
        return node_strictness

    @staticmethod
    def get_merged_pin_strictness(proxlb_config: Dict[str, Any], guest_pools: List[str], guest_tags: List[str]) -> bool:
        """
        True if pinning should be strict: any pool has strict True, or any balancing.tags
        pin rule for a tag on this guest has strict True (default True when pin is set).
        """
        logger.debug("Starting: get_merged_pin_strictness.")
        pool_strict = (
            Pools.get_pool_node_affinity_strictness(proxlb_config, guest_pools)
            if guest_pools
            else False
        )
        tags_cfg = proxlb_config.get("balancing", {}).get("tags") or {}
        rules = collect_matching_tag_rules(guest_tags or [], tags_cfg)
        pin_rules = [r for r in rules if r.get("pin")]
        tag_strict = any_pin_rule_strict(pin_rules)
        out = pool_strict or tag_strict
        logger.debug("Finished: get_merged_pin_strictness.")
        return out

    @staticmethod
    def _get_effective_always_load_based_mode(
        proxlb_config: Dict[str, Any],
        guest_pools: List[str],
        guest_tags: List[str],
        field_name: str,
        normalize_fn,
    ) -> str:
        """
        Shared: pinning_mode or affinity_mode with pool > tag > balancing precedence.
        """
        logger.debug(f"Starting: get_effective_{field_name}.")
        balancing = proxlb_config.get("balancing") or {}
        default = normalize_fn(balancing.get(field_name))
        if default is None:
            default = PINNING_MODE_LOAD_BASED

        tags_cfg = balancing.get("tags") or {}
        tag_modes: List[str] = []
        for tag in guest_tags or []:
            rule = tags_cfg.get(tag)
            if not isinstance(rule, dict) or field_name not in rule:
                continue
            m = normalize_fn(rule.get(field_name))
            if m is not None:
                tag_modes.append(m)
        tag_effective = _aggregate_always_load_based_modes(tag_modes)

        pools_cfg = balancing.get("pools") or {}
        pool_modes: List[str] = []
        for pool in guest_pools or []:
            pset = pools_cfg.get(pool)
            if not isinstance(pset, dict) or field_name not in pset:
                continue
            m = normalize_fn(pset.get(field_name))
            if m is not None:
                pool_modes.append(m)
        pool_effective = _aggregate_always_load_based_modes(pool_modes)

        out = default
        if tag_effective is not None:
            out = tag_effective
        if pool_effective is not None:
            out = pool_effective
        logger.debug(f"Finished: get_effective_{field_name}.")
        return out

    @staticmethod
    def get_effective_pinning_mode(
        proxlb_config: Dict[str, Any],
        guest_pools: List[str],
        guest_tags: List[str],
    ) -> str:
        """
        Effective pinning_mode for relocate_guests hottest-node gate bypass.

        Cross-scope precedence (fixed, not configurable): pool overrides tag overrides
        balancing default. Within tags or within pools: any 'always' dominates
        'load-based'.

        Returns:
            PINNING_MODE_ALWAYS or PINNING_MODE_LOAD_BASED (default when unset).
        """
        return Pools._get_effective_always_load_based_mode(
            proxlb_config, guest_pools, guest_tags, "pinning_mode", normalize_pinning_mode
        )

    @staticmethod
    def get_effective_affinity_mode(
        proxlb_config: Dict[str, Any],
        guest_pools: List[str],
        guest_tags: List[str],
    ) -> str:
        """
        Effective affinity_mode (affinity + anti-affinity placement) for hottest-node bypass.

        Same precedence and values as pinning_mode.
        """
        return Pools._get_effective_always_load_based_mode(
            proxlb_config, guest_pools, guest_tags, "affinity_mode", normalize_affinity_mode
        )
