"""
Reference implementation of the L4 consistent-hash load balancer.

"""

from framework import LoadBalancerBase, TABLE_SIZE, lb_hash, five_tuple_key
from typing import Dict, List, Optional, Tuple


class LoadBalancer(LoadBalancerBase):
    """L4 load balancer with consistent hashing and connection tracking."""

    def __init__(self):
        self._services: Dict[str, dict] = {}

    def _svc(self, service_id: str) -> dict:
        return self._services[service_id]

    # -- Service / backend management ----------------------------------------

    def add_service(self, service_id: str) -> None:
        if service_id not in self._services:
            self._services[service_id] = {
                "backends": {},
                "table": [],
                "connections": {},
            }

    def add_backend(
        self, service_id: str, backend_id: str, weight: int = 1
    ) -> None:
        svc = self._svc(service_id)
        svc["backends"][backend_id] = {"weight": weight, "healthy": True}
        self._rebuild(svc)

    def remove_backend(self, service_id: str, backend_id: str) -> None:
        svc = self._svc(service_id)
        svc["backends"].pop(backend_id, None)
        self._rebuild(svc)

    def set_backend_health(
        self, service_id: str, backend_id: str, healthy: bool
    ) -> None:
        svc = self._svc(service_id)
        if backend_id in svc["backends"]:
            svc["backends"][backend_id]["healthy"] = healthy
            self._rebuild(svc)

    # -- Table construction --------------------------------------------------

    def _rebuild(self, svc: dict) -> None:
        healthy: List[Tuple[str, int]] = sorted(
            (bid, info["weight"])
            for bid, info in svc["backends"].items()
            if info["healthy"]
        )

        if not healthy:
            svc["table"] = []
            return

        M = TABLE_SIZE
        n = len(healthy)

        perms: List[List[int]] = []
        bids: List[str] = []
        weights: List[int] = []

        for bid, w in healthy:
            key = bid.encode("utf-8")
            offset = lb_hash(key, 0) % M
            skip = lb_hash(key, 1) % (M - 1) + 1
            perm = [(offset + j * skip) % M for j in range(M)]
            perms.append(perm)
            bids.append(bid)
            weights.append(w)

        table: List[Optional[str]] = [None] * M
        nxt = [0] * n
        filled = 0

        while filled < M:
            for i in range(n):
                for _ in range(weights[i]):
                    if filled >= M:
                        break
                    c = perms[i][nxt[i]]
                    while table[c] is not None:
                        nxt[i] += 1
                        c = perms[i][nxt[i]]
                    table[c] = bids[i]
                    nxt[i] += 1
                    filled += 1
                if filled >= M:
                    break

        svc["table"] = table

    # -- Packet selection ----------------------------------------------------

    def select_backend(
        self, service_id: str, packet: dict
    ) -> Optional[str]:
        svc = self._svc(service_id)
        key = five_tuple_key(packet)
        is_fin = packet.get("fin", False)

        if key in svc["connections"]:
            bid = svc["connections"][key]
            if bid in svc["backends"]:
                if is_fin:
                    del svc["connections"][key]
                return bid
            del svc["connections"][key]

        table = svc["table"]
        if not table:
            return None

        ft_bytes = key.encode("utf-8")
        idx = lb_hash(ft_bytes, seed=2) % TABLE_SIZE
        bid = table[idx]

        if not is_fin:
            svc["connections"][key] = bid

        return bid

    # -- Accessors -----------------------------------------------------------

    def get_lookup_table(self, service_id: str) -> list:
        return list(self._svc(service_id)["table"])

    def get_connection_count(self, service_id: str) -> int:
        return len(self._svc(service_id)["connections"])
