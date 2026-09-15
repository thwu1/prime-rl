"""
Per-packet L4 load balancer for the Cilium eBPF datapath simulator.

Simplified from __per_packet_lb_svc_xlate_4() in bpf_lxc.c.
Performs service lookup by VIP:port and DNAT to a selected backend
using round-robin selection.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class LBBackend:
    address: str
    port: int
    backend_id: int = 0


@dataclass
class LBService:
    vip: str
    port: int
    backends: List[LBBackend] = field(default_factory=list)
    rev_nat_index: int = 0
    l7_lb_proxy_port: int = 0


class LoadBalancer:
    """Per-packet L4 load balancer with round-robin backend selection."""

    def __init__(self):
        self._services: Dict[str, LBService] = {}
        self._rr: Dict[str, int] = {}

    def add_service(self, svc: LBService):
        self._services[f"{svc.vip}:{svc.port}"] = svc

    def lookup(self, daddr: str, dport: int) -> Optional[LBService]:
        return self._services.get(f"{daddr}:{dport}")

    def select_backend(self, svc: LBService) -> Optional[LBBackend]:
        if not svc.backends:
            return None
        k = f"{svc.vip}:{svc.port}"
        idx = self._rr.get(k, 0)
        be = svc.backends[idx % len(svc.backends)]
        self._rr[k] = idx + 1
        return be
