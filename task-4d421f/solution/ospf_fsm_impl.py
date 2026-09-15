"""OSPF Neighbor FSM Conformance Engine - RFC 2328

Implements the complete OSPF neighbor finite state machine as specified
in RFC 2328 Sections 10.1-10.4, with support for trace processing and
conformance violation detection.
"""
import json
import copy


class NeighborFSM:
    """Represents a single OSPF neighbor finite state machine instance.

    Models the 8-state, 13-event neighbor FSM from RFC 2328 Section 10.3,
    including conditional transitions based on network type and DR/BDR roles.
    """

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
        """RFC 2328 Section 10.4: Whether to become adjacent.

        Returns True if at least one of the seven conditions for
        adjacency formation is met.
        """
        if self.network_type in ("point-to-point", "point-to-multipoint", "virtual-link"):
            return True
        if self.is_dr or self.is_bdr:
            return True
        if self.neighbor_is_dr or self.neighbor_is_bdr:
            return True
        return False

    def process_event(self, event, ls_request_list_empty=None):
        """Process an FSM event.

        Args:
            event: One of the 13 FSM events from RFC 2328 Section 10.2.
            ls_request_list_empty: Boolean context for ExchangeDone event.

        Returns:
            Tuple (old_state, new_state). If no state change occurs,
            new_state equals old_state.
        """
        old_state = self.state
        new_state = self._compute_transition(event, ls_request_list_empty)
        if new_state is not None:
            self.state = new_state
        else:
            new_state = old_state
        return (old_state, new_state)

    def _compute_transition(self, event, ls_request_list_empty):
        """Compute the next state given current state and event.

        Returns the new state, or None if no state change should occur.
        """
        s = self.state

        if event == "HelloReceived":
            if s in ("Down", "Attempt"):
                return "Init"
            return None

        if event == "Start":
            if s == "Down":
                return "Attempt"
            return None

        if event == "2-WayReceived":
            if s == "Init":
                if self.should_form_adjacency():
                    return "ExStart"
                else:
                    return "2-Way"
            return None

        if event == "NegotiationDone":
            if s == "ExStart":
                return "Exchange"
            return None

        if event == "ExchangeDone":
            if s == "Exchange":
                if ls_request_list_empty:
                    return "Full"
                else:
                    return "Loading"
            return None

        if event == "LoadingDone":
            if s == "Loading":
                return "Full"
            return None

        if event == "AdjOK?":
            if s == "2-Way":
                if self.should_form_adjacency():
                    return "ExStart"
                return None
            elif s in ("ExStart", "Exchange", "Loading", "Full"):
                if not self.should_form_adjacency():
                    return "2-Way"
                return None
            return None

        if event == "1-Way":
            if s in ("2-Way", "ExStart", "Exchange", "Loading", "Full"):
                return "Init"
            return None

        if event == "SeqNumberMismatch":
            if s in ("ExStart", "Exchange", "Loading", "Full"):
                return "ExStart"
            return None

        if event == "BadLSReq":
            if s in ("ExStart", "Exchange", "Loading", "Full"):
                return "ExStart"
            return None

        if event == "KillNbr":
            if s != "Down":
                return "Down"
            return None

        if event == "InactivityTimer":
            if s != "Down":
                return "Down"
            return None

        if event == "LLDown":
            if s != "Down":
                return "Down"
            return None

        return None


class OSPFNetwork:
    """Manages OSPF network topology and processes event traces.

    Handles topology-dependent adjacency decisions, DR/BDR role updates,
    and conformance validation.
    """

    def __init__(self, topology_file):
        with open(topology_file) as f:
            topo = json.load(f)
        self.routers = topo["routers"]
        self.networks = topo["networks"]

    def _get_shared_network(self, router1, router2):
        """Find the network shared by two routers."""
        r1_nets = set()
        for iface in self.routers[router1]["interfaces"].values():
            r1_nets.add(iface["network"])
        r2_nets = set()
        for iface in self.routers[router2]["interfaces"].values():
            r2_nets.add(iface["network"])
        shared = r1_nets & r2_nets
        if shared:
            return list(shared)[0]
        return None

    def _make_fsm(self, router, neighbor, networks):
        """Create a NeighborFSM with the correct network context."""
        net_name = self._get_shared_network(router, neighbor)
        net = networks[net_name]
        return NeighborFSM(
            router_id=router,
            neighbor_id=neighbor,
            network_type=net["type"],
            is_dr=(net.get("dr") == router),
            is_bdr=(net.get("bdr") == router),
            neighbor_is_dr=(net.get("dr") == neighbor),
            neighbor_is_bdr=(net.get("bdr") == neighbor)
        )

    def _update_fsm_roles(self, fsm, router, neighbor, networks):
        """Update FSM DR/BDR properties from current network state."""
        net_name = self._get_shared_network(router, neighbor)
        net = networks[net_name]
        fsm.is_dr = (net.get("dr") == router)
        fsm.is_bdr = (net.get("bdr") == router)
        fsm.neighbor_is_dr = (net.get("dr") == neighbor)
        fsm.neighbor_is_bdr = (net.get("bdr") == neighbor)

    def process_trace(self, trace_file):
        """Process an event trace file and return transition log.

        Creates fresh FSM instances for each trace so traces are independent.
        Deep-copies the network topology so DR/BDR updates within a trace
        do not persist across traces.
        """
        with open(trace_file) as f:
            trace = json.load(f)

        networks = copy.deepcopy(self.networks)
        fsms = {}
        transitions = []

        for event_data in trace["events"]:
            router = event_data["router"]
            neighbor = event_data["neighbor"]
            event = event_data["event"]
            ls_req_empty = event_data.get("ls_request_list_empty")

            key = (router, neighbor)
            if key not in fsms:
                fsms[key] = self._make_fsm(router, neighbor, networks)

            fsm = fsms[key]

            # Apply DR/BDR update before processing the event
            if "dr_update" in event_data:
                net_name = self._get_shared_network(router, neighbor)
                networks[net_name]["dr"] = event_data["dr_update"]["dr"]
                networks[net_name]["bdr"] = event_data["dr_update"]["bdr"]
                self._update_fsm_roles(fsm, router, neighbor, networks)

            old_state, new_state = fsm.process_event(event, ls_req_empty)

            transitions.append({
                "time": event_data["time"],
                "router": router,
                "neighbor": neighbor,
                "event": event,
                "from_state": old_state,
                "to_state": new_state
            })

        final_states = {}
        for (r, n), fsm in fsms.items():
            final_states[f"{r}->{n}"] = fsm.state

        return {
            "trace_id": trace["trace_id"],
            "transitions": transitions,
            "final_states": final_states
        }

    def validate_transitions(self, trace_file):
        """Validate claimed state transitions against the RFC spec.

        For each transition, creates a temporary FSM in the claimed
        from_state with the appropriate network context, processes the
        event, and checks whether the expected to_state matches the
        claimed to_state. DR/BDR updates are applied cumulatively.

        Returns a list of violation dicts.
        """
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

            # Apply DR/BDR update if present
            if "dr_update" in t:
                net_name = self._get_shared_network(router, neighbor)
                networks[net_name]["dr"] = t["dr_update"]["dr"]
                networks[net_name]["bdr"] = t["dr_update"]["bdr"]

            # Create temporary FSM in claimed_from state with current context
            temp_fsm = self._make_fsm(router, neighbor, networks)
            temp_fsm.state = claimed_from

            ls_req_empty = t.get("ls_request_list_empty")
            _, expected_to = temp_fsm.process_event(event, ls_req_empty)

            if expected_to != claimed_to:
                violations.append({
                    "index": i,
                    "type": "invalid_transition",
                    "detail": (
                        f"Event '{event}' in state '{claimed_from}': "
                        f"expected '{expected_to}' but claimed '{claimed_to}'"
                    )
                })

        return violations
