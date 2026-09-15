"""
Connection tracking for the Cilium eBPF datapath simulator.

Models the BPF CT hash map with scope-aware lookups. Supports
bidirectional (SCOPE_BIDIR) and forward-only (SCOPE_FORWARD)
lookup semantics.

CT state metadata encoding (used between BPF tail call stages):
  Bit layout: [31:16] rev_nat_index, [0] loopback flag
  Encodes via encode_ct_state(), decodes via decode_ct_state().
  These functions must be exact inverses of each other.
"""

from dataclasses import dataclass
from enum import IntEnum
from typing import Dict, Optional, Tuple


class CTStatus(IntEnum):
    CT_NEW = 0
    CT_ESTABLISHED = 1
    CT_REPLY = 2
    CT_RELATED = 3


class CTScope(IntEnum):
    SCOPE_BIDIR = 0
    SCOPE_FORWARD = 1


class CTDir(IntEnum):
    CT_EGRESS = 0
    CT_INGRESS = 1


@dataclass
class CTTuple:
    saddr: str = ""
    daddr: str = ""
    sport: int = 0
    dport: int = 0
    nexthdr: int = 0

    def reverse(self) -> 'CTTuple':
        return CTTuple(self.daddr, self.saddr, self.dport, self.sport, self.nexthdr)

    def key(self) -> str:
        return f"{self.saddr}:{self.sport}->{self.daddr}:{self.dport}/{self.nexthdr}"


@dataclass
class CTEntry:
    rev_nat_index: int = 0
    loopback: bool = False
    node_port: bool = False
    proxy_redirect: bool = False
    src_sec_id: int = 0
    rx_packets: int = 0
    tx_packets: int = 0


class CTMap:
    """BPF hash map for connection tracking entries.

    Supports bidirectional and forward-only lookups. SCOPE_FORWARD
    is used after LB translation to prevent matching stale reverse
    entries from unrelated connections that share the same post-DNAT
    5-tuple.
    """

    def __init__(self):
        self._entries: Dict[str, CTEntry] = {}

    def lookup(self, tup: CTTuple, direction: CTDir,
               scope: CTScope) -> Tuple[CTStatus, Optional[CTEntry]]:
        fwd_key = self._make_key(tup, direction)
        if fwd_key in self._entries:
            entry = self._entries[fwd_key]
            entry.rx_packets += 1
            return CTStatus.CT_ESTABLISHED, entry

        if scope == CTScope.SCOPE_FORWARD:
            return CTStatus.CT_NEW, None

        rev_tup = tup.reverse()
        rev_dir = CTDir.CT_INGRESS if direction == CTDir.CT_EGRESS else CTDir.CT_EGRESS
        rev_key = self._make_key(rev_tup, rev_dir)
        if rev_key in self._entries:
            entry = self._entries[rev_key]
            entry.tx_packets += 1
            return CTStatus.CT_REPLY, entry

        return CTStatus.CT_NEW, None

    def create(self, tup: CTTuple, direction: CTDir, entry: CTEntry):
        self._entries[self._make_key(tup, direction)] = entry

    def get_entry(self, saddr, daddr, sport, dport, proto) -> Optional[CTEntry]:
        """Retrieve a CT entry for inspection."""
        tup = CTTuple(saddr, daddr, sport, dport, proto)
        key = self._make_key(tup, CTDir.CT_EGRESS)
        return self._entries.get(key)

    def _make_key(self, tup: CTTuple, direction: CTDir) -> str:
        return f"{direction.value}|{tup.key()}"


def encode_ct_state(rev_nat_index: int, loopback: bool) -> int:
    """Pack CT state into 32-bit metadata (CB_CT_STATE).

    Bit layout: [31:16] rev_nat_index, [0] loopback flag.
    Mirrors lb4_ctx_store_state() in bpf_lxc.c.
    """
    return (rev_nat_index << 16) | (1 if loopback else 0)


def decode_ct_state(meta: int) -> Tuple[int, bool]:
    """Unpack CT state from 32-bit metadata.

    Must invert encode_ct_state exactly:
      rev_nat_index = bits[31:16], loopback = bit[0].
    """
    loopback = bool(meta & 0x1)
    rev_nat_index = (meta >> 8) & 0xFF
    return rev_nat_index, loopback
