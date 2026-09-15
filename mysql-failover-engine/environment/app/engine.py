"""
MySQL HA Failover Decision Engine

Implement a failover decision engine that matches orchestrator's behavior
for failure detection, recovery gating, promotion candidate selection,
raft leader election, outage estimation, and recovery orchestration.

Study the documentation in /app/docs/ and the reference scenarios in
/app/scenarios/ to understand expected behavior.

"""

from typing import List, Optional
from models import (
    TopologyState, Server, OrchestratorNode,
    FailureAnalysis, RecoveryDecision, RecoveryReport,
    FailureType, PromotionRule, ReplicationState, ClusterConfig
)


class FailoverEngine:
    """
    MySQL HA Failover Decision Engine.

    Models orchestrator's failure detection, recovery decisions,
    and failover orchestration behavior.
    """

    def get_replicas(self, state: TopologyState, server: Server) -> List[Server]:
        """Return all direct replicas of the given server in the topology."""
        raise NotImplementedError

    def get_master(self, state: TopologyState, server: Server) -> Optional[Server]:
        """Return the master of the given server, or None if it has no master."""
        raise NotImplementedError

    def is_intermediate_master(self, state: TopologyState, server: Server) -> bool:
        """True if the server has both a master and its own replicas."""
        raise NotImplementedError

    def find_masters(self, state: TopologyState) -> List[Server]:
        """Find all top-level masters in the topology."""
        raise NotImplementedError

    def find_intermediate_masters(self, state: TopologyState) -> List[Server]:
        """Find all intermediate masters in the topology."""
        raise NotImplementedError

    def analyze_failure(self, state: TopologyState) -> List[FailureAnalysis]:
        """Detect and classify all failures in the topology."""
        raise NotImplementedError

    def should_recover(self, state: TopologyState, failure: FailureAnalysis) -> RecoveryDecision:
        """Determine whether automated recovery should proceed for a detected failure."""
        raise NotImplementedError

    def select_promotion_candidate(self, state: TopologyState, failed_server: Server) -> Optional[Server]:
        """Select the best replica to promote when the given server fails."""
        raise NotImplementedError

    def determine_raft_leader(self, orchestrator_nodes: List[OrchestratorNode]) -> Optional[OrchestratorNode]:
        """Determine which orchestrator node should be the raft leader."""
        raise NotImplementedError

    def estimate_outage_seconds(self, state: TopologyState, failure: FailureAnalysis,
                                candidate: Optional[Server]) -> float:
        """Estimate total outage duration for a failover scenario."""
        raise NotImplementedError

    def execute_recovery(self, state: TopologyState) -> RecoveryReport:
        """Execute the full recovery pipeline and return a report."""
        raise NotImplementedError
