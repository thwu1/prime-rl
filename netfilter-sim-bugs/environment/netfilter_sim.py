#!/usr/bin/env python3
"""
Linux Netfilter Packet Flow Simulator

Simulates packet processing through the Linux kernel networking stack,
including iptables tables/chains and the conntrack (connection tracking)
subsystem.

Packet flow for incoming (locally-destined) packets:
  NIC -> raw PREROUTING -> [conntrack] -> mangle PREROUTING ->
  nat PREROUTING -> [routing] -> mangle INPUT -> filter INPUT -> application

Conntrack sits between raw PREROUTING and mangle PREROUTING. When the
conntrack table is full, new-flow packets are silently dropped at the
conntrack hook point.

Reference: Netfilter packet flow diagram
https://upload.wikimedia.org/wikipedia/commons/3/37/Netfilter-packet-flow.svg
"""

import json
import sys
from dataclasses import dataclass
from enum import Enum, auto
from ipaddress import ip_address, ip_network
from typing import Optional, Dict, Tuple, List


class Protocol(Enum):
    TCP = 6
    UDP = 17
    ICMP = 1


class TCPFlags(Enum):
    SYN = "S"
    ACK = "A"
    SYN_ACK = "SA"
    FIN = "F"
    RST = "R"
    NONE = ""


class Action(Enum):
    ACCEPT = "ACCEPT"
    DROP = "DROP"
    NOTRACK = "NOTRACK"
    REJECT = "REJECT"


class Verdict(Enum):
    ACCEPT = auto()
    DROP = auto()
    CONTINUE = auto()


@dataclass
class Packet:
    src_ip: str
    dst_ip: str
    src_port: int
    dst_port: int
    protocol: Protocol
    tcp_flags: TCPFlags = TCPFlags.NONE

    @property
    def flow_key(self) -> Tuple:
        return (self.protocol, self.src_ip, self.src_port,
                self.dst_ip, self.dst_port)

    @property
    def reverse_flow_key(self) -> Tuple:
        return (self.protocol, self.dst_ip, self.dst_port,
                self.src_ip, self.src_port)

    @classmethod
    def from_dict(cls, d: dict) -> 'Packet':
        return cls(
            src_ip=d["src_ip"],
            dst_ip=d["dst_ip"],
            src_port=d["src_port"],
            dst_port=d["dst_port"],
            protocol=Protocol[d["protocol"]],
            tcp_flags=TCPFlags(d.get("tcp_flags", ""))
        )


@dataclass
class Rule:
    table: str
    chain: str
    protocol: Optional[Protocol] = None
    src_ip: Optional[str] = None
    src_network: Optional[str] = None
    dst_ip: Optional[str] = None
    src_port: Optional[int] = None
    dst_port: Optional[int] = None
    tcp_flags: Optional[TCPFlags] = None
    action: Action = Action.ACCEPT

    def matches(self, packet: Packet) -> bool:
        if self.protocol is not None and packet.protocol != self.protocol:
            return False
        if self.src_ip is not None and packet.src_ip != self.src_ip:
            return False
        if self.src_network is not None:
            if ip_address(packet.src_ip) not in ip_network(
                    self.src_network, strict=False):
                return False
        if self.dst_ip is not None and packet.dst_ip != self.dst_ip:
            return False
        if self.src_port is not None and packet.src_port != self.src_port:
            return False
        if self.dst_port is not None and packet.dst_port != self.dst_port:
            return False
        if self.tcp_flags is not None and packet.tcp_flags != self.tcp_flags:
            return False
        return True

    @classmethod
    def from_dict(cls, d: dict) -> 'Rule':
        return cls(
            table=d["table"],
            chain=d["chain"],
            protocol=Protocol[d["protocol"]] if d.get("protocol") else None,
            src_ip=d.get("src_ip"),
            src_network=d.get("src_network"),
            dst_ip=d.get("dst_ip"),
            src_port=d.get("src_port"),
            dst_port=d.get("dst_port"),
            tcp_flags=TCPFlags(d["tcp_flags"]) if d.get("tcp_flags") else None,
            action=Action[d["action"]]
        )


class ConntrackTable:
    """Simulates the Linux conntrack table."""

    def __init__(self, max_entries: int, tcp_loose: bool = True):
        self.max_entries = max_entries
        self.tcp_loose = tcp_loose
        self.entries: Dict[Tuple, dict] = {}
        self._pending: Dict[Tuple, dict] = {}

    @property
    def count(self) -> int:
        """Number of confirmed entries in the table."""
        return len(self.entries)

    def lookup(self, packet: Packet) -> bool:
        """Check if a conntrack entry exists for this flow."""
        fk = packet.flow_key
        rk = packet.reverse_flow_key
        return (fk in self.entries or rk in self.entries or
                fk in self._pending or rk in self._pending)

    def process_packet(self, packet: Packet, notrack: bool = False) -> bool:
        """
        Process a packet through conntrack.
        Returns True if packet should continue, False if dropped (table full).
        """
        if notrack:
            return True

        # Existing flow always passes
        if self.lookup(packet):
            return True

        # TCP loose mode: only SYN creates new entries when loose=False
        if not self.tcp_loose and packet.protocol == Protocol.TCP:
            if packet.tcp_flags != TCPFlags.SYN:
                return True

        # Check table capacity
        if self.count >= self.max_entries:
            return False

        # Create new conntrack entry
        self.entries[packet.flow_key] = {
            "protocol": packet.protocol,
            "src_ip": packet.src_ip,
            "src_port": packet.src_port,
            "dst_ip": packet.dst_ip,
            "dst_port": packet.dst_port,
        }
        return True

    def confirm_pending(self, packet: Packet):
        """Confirm a pending conntrack entry after successful chain traversal."""
        fk = packet.flow_key
        if fk in self._pending:
            self.entries[fk] = self._pending.pop(fk)

    def rollback_pending(self, packet: Packet):
        """Roll back a pending conntrack entry when packet is dropped."""
        fk = packet.flow_key
        self._pending.pop(fk, None)


class NetfilterSimulator:
    """Simulates the Linux netfilter packet processing pipeline."""

    def __init__(self, rules: List[Rule], conntrack_max: int,
                 tcp_loose: bool = True, conntrack_enabled: bool = True):
        self.rules = rules
        self.conntrack = ConntrackTable(conntrack_max, tcp_loose)
        self.conntrack_enabled = conntrack_enabled

        self.counters: Dict[str, int] = {}
        for table in ["raw", "mangle", "nat", "filter"]:
            for chain in ["PREROUTING", "INPUT", "FORWARD",
                          "OUTPUT", "POSTROUTING"]:
                self.counters[f"{table}:{chain}"] = 0

        self.dropped_packets = 0
        self.accepted_packets = 0
        self.conntrack_drops = 0

    def _get_rules(self, table: str, chain: str) -> List[Rule]:
        return [r for r in self.rules
                if r.table == table and r.chain == chain]

    def _process_chain(self, packet: Packet,
                       table: str, chain: str) -> Verdict:
        """Process packet through a table/chain. Returns verdict."""
        key = f"{table}:{chain}"
        self.counters[key] += 1

        for rule in self._get_rules(table, chain):
            if rule.matches(packet):
                if rule.action == Action.DROP:
                    return Verdict.DROP
                elif rule.action == Action.NOTRACK:
                    return Verdict.CONTINUE
                elif rule.action == Action.ACCEPT:
                    return Verdict.ACCEPT
                elif rule.action == Action.REJECT:
                    return Verdict.DROP

        return Verdict.CONTINUE

    def _check_notrack(self, packet: Packet) -> bool:
        """Check if packet matches any NOTRACK rule in raw PREROUTING."""
        for rule in self._get_rules("raw", "PREROUTING"):
            if rule.matches(packet) and rule.action == Action.NOTRACK:
                return True
        return False

    def process_incoming_packet(self, packet: Packet) -> str:
        """
        Process an incoming packet through PREROUTING -> INPUT path.
        Returns disposition string.
        """
        notrack = False

        # 1. raw PREROUTING
        verdict = self._process_chain(packet, "raw", "PREROUTING")
        if verdict == Verdict.DROP:
            self.dropped_packets += 1
            return "dropped:raw_prerouting"

        # Detect NOTRACK marking
        notrack = self._check_notrack(packet)

        # 2. conntrack hook (between raw and mangle PREROUTING)
        if self.conntrack_enabled:
            ct_ok = self.conntrack.process_packet(packet, notrack=False)
            if not ct_ok:
                self.conntrack_drops += 1
                self.dropped_packets += 1
                return "dropped:conntrack_table_full"

        # 3. mangle PREROUTING
        verdict = self._process_chain(packet, "mangle", "PREROUTING")
        if verdict == Verdict.DROP:
            self.dropped_packets += 1
            return "dropped:mangle_prerouting"

        # 4. nat PREROUTING
        verdict = self._process_chain(packet, "nat", "PREROUTING")
        if verdict == Verdict.DROP:
            self.dropped_packets += 1
            return "dropped:nat_prerouting"

        # 5. Routing decision (all packets locally destined in simulation)

        # 6. mangle INPUT
        verdict = self._process_chain(packet, "mangle", "INPUT")
        if verdict == Verdict.DROP:
            self.dropped_packets += 1
            return "dropped:mangle_input"

        # 7. filter INPUT
        verdict = self._process_chain(packet, "filter", "INPUT")
        if verdict == Verdict.DROP:
            self.dropped_packets += 1
            return "dropped:filter_input"

        # 8. Local delivery - accepted
        self.accepted_packets += 1
        return "accepted"

    def process_packet_sequence(self, packets: List[Packet]) -> dict:
        """Process a sequence of packets and return results."""
        results = []
        for pkt in packets:
            result = self.process_incoming_packet(pkt)
            results.append(result)

        return {
            "packet_results": results,
            "counters": dict(self.counters),
            "conntrack_entries": self.conntrack.count,
            "total_dropped": self.dropped_packets,
            "total_accepted": self.accepted_packets,
            "conntrack_drops": self.conntrack_drops,
        }


def load_scenario(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def run_scenario(scenario: dict) -> dict:
    rules = [Rule.from_dict(r) for r in scenario["rules"]]
    packets = [Packet.from_dict(p) for p in scenario["packets"]]

    sim = NetfilterSimulator(
        rules=rules,
        conntrack_max=scenario["conntrack_max"],
        tcp_loose=scenario.get("tcp_loose", True),
        conntrack_enabled=scenario.get("conntrack_enabled", True),
    )

    return sim.process_packet_sequence(packets)


def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <scenario.json>")
        sys.exit(1)

    scenario = load_scenario(sys.argv[1])
    results = run_scenario(scenario)
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
