"""
Kafka KIP-966 Replication Protocol Simulator.

Implements the partition replication state machine with ISR, ELR, and
LastKnownELR management, leader election with clean and unclean recovery
modes, high watermark advancement, and data loss detection.
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SimulationResult:
    """Result of running a simulation scenario."""
    leader: Optional[str]
    isr: list
    elr: list
    last_known_elr: list
    hwm: int
    leo: dict
    committed_data_lost: int
    election_history: list

    def to_dict(self) -> dict:
        return {
            "leader": self.leader,
            "isr": self.isr,
            "elr": self.elr,
            "last_known_elr": self.last_known_elr,
            "hwm": self.hwm,
            "leo": self.leo,
            "committed_data_lost": self.committed_data_lost,
            "election_history": self.election_history,
        }


class PartitionSimulator:
    """Simulates a single Kafka partition's replication protocol with KIP-966."""

    def __init__(self, config: dict):
        self.rf = config["replication_factor"]
        self.min_isr = config["min_isr"]
        self.recovery_mode = config.get("recovery_mode", "balanced")

        self.replicas = [f"R{i+1}" for i in range(self.rf)]

        # Initial state
        self.leader: Optional[str] = "R1"
        self.isr: set = set(self.replicas)
        self.elr: set = set()
        self.last_known_elr: set = set()
        self.fenced: set = set()

        self.leo: dict = {r: 0 for r in self.replicas}
        self.hwm: int = 0

        self.committed_data_lost: int = 0
        self.election_history: list = []

    def process_event(self, event: dict) -> None:
        etype = event["type"]
        handler = {
            "produce": self._handle_produce,
            "replicate": self._handle_replicate,
            "advance_hwm": self._handle_advance_hwm,
            "fence": self._handle_fence,
            "unfence": self._handle_unfence,
            "elect_leader": self._handle_elect_leader,
            "add_to_isr": self._handle_add_to_isr,
        }.get(etype)
        if handler is None:
            raise ValueError(f"Unknown event type: {etype}")
        handler(event)

    # ---- Event handlers ----

    def _handle_produce(self, event: dict) -> None:
        if self.leader is None:
            return
        self.leo[self.leader] += event["count"]

    def _handle_replicate(self, event: dict) -> None:
        replica = event["replica"]
        if self.leader is None or replica == self.leader or replica in self.fenced:
            return
        leader_leo = self.leo[self.leader]
        up_to = event.get("up_to")
        target = min(up_to, leader_leo) if up_to is not None else leader_leo
        # Truncate divergent suffix then fetch
        self.leo[replica] = min(self.leo[replica], leader_leo)
        self.leo[replica] = max(self.leo[replica], target)

    def _handle_advance_hwm(self, event: dict) -> None:
        if self.leader is None:
            return
        if len(self.isr) < self.min_isr:
            return
        isr_leos = [self.leo[r] for r in self.isr]
        new_hwm = min(isr_leos)
        self.hwm = max(self.hwm, new_hwm)

    def _handle_fence(self, event: dict) -> None:
        replica = event["replica"]
        self.fenced.add(replica)
        was_leader = (replica == self.leader)

        # Remove from ISR
        self.isr.discard(replica)

        # Remove leadership
        if was_leader:
            self.leader = None

        # ELR addition: if ISR too small and ISR+ELR combined also too small
        if len(self.isr) < self.min_isr and len(self.isr) + len(self.elr) < self.min_isr:
            self.elr.add(replica)

    def _handle_unfence(self, event: dict) -> None:
        replica = event["replica"]
        self.fenced.discard(replica)

        unclean = event.get("unclean", False)
        records_lost = event.get("records_lost", 0)

        if unclean and records_lost > 0:
            self.leo[replica] = max(0, self.leo[replica] - records_lost)

        if unclean and replica in self.elr:
            self.elr.discard(replica)
            self.last_known_elr.add(replica)

    def _handle_elect_leader(self, event: dict) -> None:
        if self.leader is not None:
            return

        # Step 1: Clean election from ISR
        isr_candidates = sorted(r for r in self.isr if r not in self.fenced)
        if isr_candidates:
            elected = max(isr_candidates, key=lambda r: self.leo[r])
            self._do_election(elected, "clean", preserve_isr=True)
            return

        # Step 2: Clean election from ELR
        elr_candidates = sorted(r for r in self.elr if r not in self.fenced)
        if elr_candidates:
            elected = max(elr_candidates, key=lambda r: self.leo[r])
            self._do_election(elected, "clean", preserve_isr=False)
            return

        # Step 3: Recovery modes
        # Proactive: ELR non-empty but all fenced → pick any unfenced replica
        if self.recovery_mode == "proactive" and self.elr:
            if all(r in self.fenced for r in self.elr):
                all_unfenced = sorted(r for r in self.replicas if r not in self.fenced)
                if all_unfenced:
                    elected = max(all_unfenced, key=lambda r: self.leo[r])
                    self._do_election(elected, "unclean_proactive", preserve_isr=False)
                    return

        # Balanced (also fallback for proactive): ISR empty AND ELR empty
        if self.recovery_mode in ("balanced", "proactive"):
            if not self.isr and not self.elr and self.last_known_elr:
                lkelr_candidates = sorted(
                    r for r in self.last_known_elr if r not in self.fenced
                )
                if lkelr_candidates:
                    elected = max(lkelr_candidates, key=lambda r: self.leo[r])
                    self._do_election(elected, "unclean_balanced", preserve_isr=False)
                    return

        # No candidates / manual mode
        self.election_history.append({"type": "failed", "reason": "no_candidates"})

    def _do_election(self, elected: str, election_type: str, preserve_isr: bool) -> None:
        old_hwm = self.hwm
        data_lost = max(0, old_hwm - self.leo[elected])
        self.committed_data_lost += data_lost

        self.leader = elected
        self.hwm = min(self.hwm, self.leo[elected])

        if preserve_isr:
            # Clean election from ISR: keep unfenced ISR members
            self.isr = {r for r in self.isr if r not in self.fenced}
            if len(self.isr) >= self.min_isr:
                self.elr.clear()
                self.last_known_elr.clear()
        else:
            self.isr = {elected}
            self.elr.discard(elected)
            self.last_known_elr.discard(elected)

        # Truncate all non-leader replicas to the new leader's LEO
        for r in self.replicas:
            if r != elected:
                self.leo[r] = min(self.leo[r], self.leo[elected])

        self.election_history.append({
            "type": election_type,
            "leader": elected,
            "data_lost": data_lost,
        })

    def _handle_add_to_isr(self, event: dict) -> None:
        replica = event["replica"]
        if self.leader is None:
            return
        if replica in self.fenced or replica == self.leader:
            return
        if self.leo[replica] < self.hwm:
            return

        self.isr.add(replica)

        if len(self.isr) >= self.min_isr:
            self.elr.clear()
            self.last_known_elr.clear()

    # ---- Result ----

    def get_result(self) -> SimulationResult:
        return SimulationResult(
            leader=self.leader,
            isr=sorted(self.isr),
            elr=sorted(self.elr),
            last_known_elr=sorted(self.last_known_elr),
            hwm=self.hwm,
            leo=dict(self.leo),
            committed_data_lost=self.committed_data_lost,
            election_history=list(self.election_history),
        )
