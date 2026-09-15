"""OSPF Protocol Conformance Analyzer — RFC 2328

Combines tshark-based pcap analysis, FSM trace validation,
and scapy test-packet generation.
"""

import json
import copy
import subprocess
import os


class OSPFAnalyzer:
    """Main analyzer: pcap extraction, FSM engine, violation detection,
    and test-pcap generation."""

    def __init__(self, topology_file):
        with open(topology_file) as f:
            self.topo = json.load(f)
        self.routers = self.topo["routers"]
        self.networks = self.topo["networks"]

    # ----------------------------------------------------------------
    # tshark pcap extraction
    # ----------------------------------------------------------------

    def extract_packets(self, pcap_file):
        """Extract OSPF Hello packets from *pcap_file* via tshark."""
        cmd = [
            "tshark", "-r", pcap_file, "-n",
            "-T", "fields",
            "-e", "frame.time_epoch",
            "-e", "ip.src",
            "-e", "ospf.srcrouter",
            "-e", "ospf.msg",
            "-e", "ospf.hello.hello_interval",
            "-e", "ospf.hello.router_dead_interval",
            "-e", "ospf.hello.router_priority",
            "-e", "ospf.hello.designated_router",
            "-e", "ospf.hello.backup_designated_router",
            "-e", "ospf.hello.active_neighbor",
            "-E", "separator=|",
            "-E", "occurrence=a",
            "-Y", "ospf",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True,
                                check=True)
        packets = []
        for line in result.stdout.strip().split('\n'):
            if not line.strip():
                continue
            parts = line.split('|')
            # Pad to 10 fields
            while len(parts) < 10:
                parts.append('')

            pkt = {
                "timestamp": float(parts[0]) if parts[0] else 0.0,
                "src_ip": parts[1],
                "src_router": parts[2],
            }

            msg_type = parts[3].strip()
            if msg_type in ("1", "Hello Packet"):
                pkt["type"] = "Hello"
            else:
                pkt["type"] = "Hello"  # fallback for Hello-only captures

            pkt["hello_interval"] = int(parts[4]) if parts[4] else 10
            pkt["dead_interval"] = int(parts[5]) if parts[5] else 40
            pkt["priority"] = int(parts[6]) if parts[6] else 1
            pkt["dr"] = parts[7] if parts[7] else "0.0.0.0"
            pkt["bdr"] = parts[8] if parts[8] else "0.0.0.0"
            nbr_str = parts[9]
            pkt["neighbors"] = [n for n in nbr_str.split(',') if n.strip()]

            packets.append(pkt)
        return packets

    # ----------------------------------------------------------------
    # pcap-based FSM analysis
    # ----------------------------------------------------------------

    def _router_id_to_name(self, rid):
        for name, info in self.routers.items():
            if info["router_id"] == rid:
                return name
        return None

    def _shared_network_by_id(self, rid1, rid2):
        """Find the shared network given two router IDs (dotted-quad)."""
        name1 = self._router_id_to_name(rid1)
        name2 = self._router_id_to_name(rid2)
        if not name1 or not name2:
            return None
        return self._get_shared_network(name1, name2)

    def _should_form_adjacency(self, net_type, is_dr, is_bdr,
                               nbr_is_dr, nbr_is_bdr):
        if net_type in ("point-to-point", "point-to-multipoint",
                        "virtual-link"):
            return True
        return is_dr or is_bdr or nbr_is_dr or nbr_is_bdr

    def analyze_capture(self, pcap_file, router_id):
        """Full pcap analysis from *router_id*'s perspective."""
        packets = self.extract_packets(pcap_file)

        fsm_states = {}          # neighbor_rid -> state
        last_hello_ts = {}       # neighbor_rid -> float
        own_hello_int = None     # perspective router's HelloInterval
        own_dead_int = None
        transitions = []
        violations = []

        # First pass: learn perspective router's own parameters
        for pkt in packets:
            if pkt["src_router"] == router_id and pkt["type"] == "Hello":
                own_hello_int = pkt["hello_interval"]
                own_dead_int = pkt["dead_interval"]
                break

        # Second pass: process neighbor packets
        for pkt in packets:
            if pkt["type"] != "Hello":
                continue
            src = pkt["src_router"]
            if src == router_id:
                continue  # skip own packets

            ts = pkt["timestamp"]

            # --- dead-interval check ---
            if src in last_hello_ts:
                gap = ts - last_hello_ts[src]
                dead_int = pkt["dead_interval"]
                if gap > dead_int:
                    violations.append({
                        "type": "dead_interval_exceeded",
                        "detail": (f"Gap {gap:.1f}s > DeadInterval "
                                   f"{dead_int}s for {src}"),
                        "timestamp": ts,
                    })
                    # insert synthetic InactivityTimer
                    if src in fsm_states and fsm_states[src] != "Down":
                        old = fsm_states[src]
                        fsm_states[src] = "Down"
                        transitions.append({
                            "timestamp": last_hello_ts[src] + dead_int,
                            "neighbor": src,
                            "event": "InactivityTimer",
                            "from_state": old,
                            "to_state": "Down",
                        })
            last_hello_ts[src] = ts

            # --- parameter-mismatch check ---
            if own_hello_int is not None:
                if pkt["hello_interval"] != own_hello_int:
                    violations.append({
                        "type": "hello_interval_mismatch",
                        "detail": (f"Neighbor {src} HelloInterval="
                                   f"{pkt['hello_interval']} vs local "
                                   f"{own_hello_int}"),
                        "timestamp": ts,
                    })
                if own_dead_int is not None and pkt["dead_interval"] != own_dead_int:
                    violations.append({
                        "type": "hello_interval_mismatch",
                        "detail": (f"Neighbor {src} DeadInterval="
                                   f"{pkt['dead_interval']} vs local "
                                   f"{own_dead_int}"),
                        "timestamp": ts,
                    })

            # --- FSM processing ---
            if src not in fsm_states:
                fsm_states[src] = "Down"

            cur = fsm_states[src]

            # HelloReceived event
            if cur in ("Down", "Attempt"):
                fsm_states[src] = "Init"
                transitions.append({
                    "timestamp": ts, "neighbor": src,
                    "event": "HelloReceived",
                    "from_state": cur, "to_state": "Init",
                })
                cur = "Init"

            # Check 2-WayReceived / 1-Way
            if router_id in pkt["neighbors"]:
                # Perspective router is in the neighbor list
                if cur == "Init":
                    # Adjacency decision
                    net_name = self._shared_network_by_id(router_id, src)
                    if net_name:
                        net = self.networks[net_name]
                        net_type = net["type"]
                    else:
                        net_type = "point-to-point"  # fallback

                    is_dr = (pkt["dr"] == router_id)
                    is_bdr = (pkt["bdr"] == router_id)
                    nbr_is_dr = (pkt["dr"] == src)
                    nbr_is_bdr = (pkt["bdr"] == src)

                    if self._should_form_adjacency(net_type, is_dr, is_bdr,
                                                   nbr_is_dr, nbr_is_bdr):
                        new = "ExStart"
                    else:
                        new = "2-Way"
                    fsm_states[src] = new
                    transitions.append({
                        "timestamp": ts, "neighbor": src,
                        "event": "2-WayReceived",
                        "from_state": "Init", "to_state": new,
                    })
            else:
                # Not in neighbor list → 1-Way if state >= 2-Way
                if cur in ("2-Way", "ExStart", "Exchange",
                           "Loading", "Full"):
                    fsm_states[src] = "Init"
                    transitions.append({
                        "timestamp": ts, "neighbor": src,
                        "event": "1-Way",
                        "from_state": cur, "to_state": "Init",
                    })

        return {
            "transitions": transitions,
            "final_states": dict(fsm_states),
            "violations": violations,
        }

    # ----------------------------------------------------------------
    # JSON trace FSM engine
    # ----------------------------------------------------------------

    def _get_shared_network(self, router1, router2):
        r1_nets = set()
        for iface in self.routers[router1]["interfaces"].values():
            r1_nets.add(iface["network"])
        r2_nets = set()
        for iface in self.routers[router2]["interfaces"].values():
            r2_nets.add(iface["network"])
        shared = r1_nets & r2_nets
        return list(shared)[0] if shared else None

    def _make_fsm(self, router, neighbor, networks):
        net_name = self._get_shared_network(router, neighbor)
        net = networks[net_name]
        return _NeighborFSM(
            router, neighbor, net["type"],
            is_dr=(net.get("dr") == router),
            is_bdr=(net.get("bdr") == router),
            neighbor_is_dr=(net.get("dr") == neighbor),
            neighbor_is_bdr=(net.get("bdr") == neighbor),
        )

    def _update_fsm_roles(self, fsm, router, neighbor, networks):
        net_name = self._get_shared_network(router, neighbor)
        net = networks[net_name]
        fsm.is_dr = (net.get("dr") == router)
        fsm.is_bdr = (net.get("bdr") == router)
        fsm.neighbor_is_dr = (net.get("dr") == neighbor)
        fsm.neighbor_is_bdr = (net.get("bdr") == neighbor)

    def process_trace(self, trace_file):
        with open(trace_file) as f:
            trace = json.load(f)

        networks = copy.deepcopy(self.networks)
        fsms = {}
        transitions = []

        for ev in trace["events"]:
            router = ev["router"]
            neighbor = ev["neighbor"]
            event = ev["event"]
            ls_req_empty = ev.get("ls_request_list_empty")

            key = (router, neighbor)
            if key not in fsms:
                fsms[key] = self._make_fsm(router, neighbor, networks)
            fsm = fsms[key]

            if "dr_update" in ev:
                net_name = self._get_shared_network(router, neighbor)
                networks[net_name]["dr"] = ev["dr_update"]["dr"]
                networks[net_name]["bdr"] = ev["dr_update"]["bdr"]
                self._update_fsm_roles(fsm, router, neighbor, networks)

            old, new = fsm.process_event(event, ls_req_empty)
            transitions.append({
                "time": ev["time"],
                "router": router,
                "neighbor": neighbor,
                "event": event,
                "from_state": old,
                "to_state": new,
            })

        final_states = {}
        for (r, n), fsm in fsms.items():
            final_states[f"{r}->{n}"] = fsm.state

        return {
            "trace_id": trace["trace_id"],
            "transitions": transitions,
            "final_states": final_states,
        }

    def validate_transitions(self, trace_file):
        with open(trace_file) as f:
            data = json.load(f)

        violations = []
        networks = copy.deepcopy(self.networks)

        for i, t in enumerate(data["transitions"]):
            router = t["router"]
            neighbor = t["neighbor"]
            event = t["event"]
            claimed_from = t["from_state"]
            claimed_to = t["to_state"]

            if "dr_update" in t:
                net_name = self._get_shared_network(router, neighbor)
                networks[net_name]["dr"] = t["dr_update"]["dr"]
                networks[net_name]["bdr"] = t["dr_update"]["bdr"]

            tmp = self._make_fsm(router, neighbor, networks)
            tmp.state = claimed_from
            ls_req_empty = t.get("ls_request_list_empty")
            _, expected_to = tmp.process_event(event, ls_req_empty)

            if expected_to != claimed_to:
                violations.append({
                    "index": i,
                    "type": "invalid_transition",
                    "detail": (f"Event '{event}' in state "
                               f"'{claimed_from}': expected "
                               f"'{expected_to}' but claimed "
                               f"'{claimed_to}'"),
                })
        return violations

    # ----------------------------------------------------------------
    # scapy pcap generation
    # ----------------------------------------------------------------

    def generate_test_pcap(self, packets_spec, output_file):
        """Generate an OSPF Hello pcap using scapy."""
        from scapy.all import Ether, IP, wrpcap, conf
        from scapy.contrib.ospf import OSPF_Hdr, OSPF_Hello
        conf.verb = 0

        pkts = []
        for spec in packets_spec:
            pkt = (
                Ether(dst="01:00:5e:00:00:05") /
                IP(src=spec["src_ip"],
                   dst=spec.get("dst_ip", "224.0.0.5"),
                   proto=89, ttl=1, tos=0xc0) /
                OSPF_Hdr(version=2, type=1,
                         src=spec["router_id"],
                         area="0.0.0.0") /
                OSPF_Hello(
                    mask="255.255.255.0",
                    hellointerval=spec.get("hello_interval", 10),
                    prio=spec.get("priority", 1),
                    deadinterval=spec.get("dead_interval", 40),
                    router=spec.get("dr", "0.0.0.0"),
                    backup=spec.get("bdr", "0.0.0.0"),
                    neighbors=spec.get("neighbors", []),
                )
            )
            pkt.time = spec.get("timestamp", 0)
            pkts.append(pkt)

        wrpcap(output_file, pkts)
        return output_file


# ----------------------------------------------------------------
# Internal FSM (private helper, not part of the public API)
# ----------------------------------------------------------------

class _NeighborFSM:
    """RFC 2328 Section 10.3 neighbor FSM."""

    def __init__(self, router_id, neighbor_id, network_type,
                 is_dr=False, is_bdr=False,
                 neighbor_is_dr=False, neighbor_is_bdr=False):
        self.router_id = router_id
        self.neighbor_id = neighbor_id
        self.state = "Down"
        self.network_type = network_type
        self.is_dr = is_dr
        self.is_bdr = is_bdr
        self.neighbor_is_dr = neighbor_is_dr
        self.neighbor_is_bdr = neighbor_is_bdr

    def should_form_adjacency(self):
        if self.network_type in ("point-to-point", "point-to-multipoint",
                                 "virtual-link"):
            return True
        return (self.is_dr or self.is_bdr or
                self.neighbor_is_dr or self.neighbor_is_bdr)

    def process_event(self, event, ls_request_list_empty=None):
        old = self.state
        new = self._transition(event, ls_request_list_empty)
        if new is not None:
            self.state = new
        else:
            new = old
        return (old, new)

    def _transition(self, event, ls_req_empty):
        s = self.state

        if event == "HelloReceived":
            return "Init" if s in ("Down", "Attempt") else None

        if event == "Start":
            return "Attempt" if s == "Down" else None

        if event == "2-WayReceived":
            if s == "Init":
                return "ExStart" if self.should_form_adjacency() else "2-Way"
            return None

        if event == "NegotiationDone":
            return "Exchange" if s == "ExStart" else None

        if event == "ExchangeDone":
            if s == "Exchange":
                return "Full" if ls_req_empty else "Loading"
            return None

        if event == "LoadingDone":
            return "Full" if s == "Loading" else None

        if event == "AdjOK?":
            if s == "2-Way":
                return "ExStart" if self.should_form_adjacency() else None
            if s in ("ExStart", "Exchange", "Loading", "Full"):
                return "2-Way" if not self.should_form_adjacency() else None
            return None

        if event == "1-Way":
            if s in ("2-Way", "ExStart", "Exchange", "Loading", "Full"):
                return "Init"
            return None

        if event in ("SeqNumberMismatch", "BadLSReq"):
            if s in ("ExStart", "Exchange", "Loading", "Full"):
                return "ExStart"
            return None

        if event in ("KillNbr", "InactivityTimer", "LLDown"):
            return "Down" if s != "Down" else None

        return None
