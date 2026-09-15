"""
MySQL HA Failover Decision Engine - Full Implementation

"""

from typing import List, Optional
from models import (
    TopologyState, Server, OrchestratorNode,
    FailureAnalysis, RecoveryDecision, RecoveryReport,
    FailureType, PromotionRule, ReplicationState, ClusterConfig
)


class FailoverEngine:

    def get_replicas(self, state: TopologyState, server: Server) -> List[Server]:
        return [
            s for s in state.servers
            if s.master_hostname == server.hostname
            and (s.master_port or 3306) == server.port
        ]

    def get_master(self, state: TopologyState, server: Server) -> Optional[Server]:
        if server.master_hostname is None:
            return None
        for s in state.servers:
            if s.hostname == server.master_hostname and s.port == (server.master_port or 3306):
                return s
        return None

    def is_intermediate_master(self, state: TopologyState, server: Server) -> bool:
        if server.master_hostname is None:
            return False
        return len(self.get_replicas(state, server)) > 0

    def find_masters(self, state: TopologyState) -> List[Server]:
        return [s for s in state.servers if s.master_hostname is None and not s.read_only]

    def find_intermediate_masters(self, state: TopologyState) -> List[Server]:
        return [s for s in state.servers if self.is_intermediate_master(state, s)]

    # ------------------------------------------------------------------
    # Failure detection
    # ------------------------------------------------------------------

    def analyze_failure(self, state: TopologyState) -> List[FailureAnalysis]:
        failures = []
        for master in self.find_masters(state):
            replicas = self.get_replicas(state, master)
            f = self._analyze_master(state, master, replicas)
            if f is not None:
                failures.append(f)
        for im in self.find_intermediate_masters(state):
            replicas = self.get_replicas(state, im)
            f = self._analyze_intermediate_master(state, im, replicas)
            if f is not None:
                failures.append(f)
        return failures

    def _analyze_master(self, state: TopologyState, master: Server,
                        replicas: List[Server]) -> Optional[FailureAnalysis]:
        cn = state.cluster_config.cluster_name
        if not master.is_reachable:
            return self._master_unreachable(state, master, replicas, cn)
        return self._master_reachable(state, master, replicas, cn)

    def _master_unreachable(self, state, master, replicas, cn):
        if len(replicas) == 0:
            return FailureAnalysis(FailureType.DEAD_MASTER_WITHOUT_REPLICAS,
                                   master, False, cn,
                                   f"Master {master.key} dead, no replicas")

        reachable = [r for r in replicas if r.is_reachable]
        unreachable = [r for r in replicas if not r.is_reachable]

        if len(reachable) == 0:
            return FailureAnalysis(FailureType.DEAD_MASTER_AND_REPLICAS,
                                   master, False, cn,
                                   f"Master {master.key} and all replicas dead")

        non_delayed = [r for r in reachable if not r.is_sql_delayed]
        replicating = [r for r in non_delayed
                       if r.replication_state == ReplicationState.RUNNING]
        if replicating:
            return FailureAnalysis(FailureType.UNREACHABLE_MASTER,
                                   master, False, cn,
                                   f"Master {master.key} unreachable, replicas still replicating")

        lagging = [r for r in non_delayed
                   if r.replication_state == ReplicationState.LAGGING]
        if non_delayed and len(lagging) == len(non_delayed):
            return FailureAnalysis(FailureType.UNREACHABLE_MASTER_WITH_LAGGING_REPLICAS,
                                   master, True, cn,
                                   f"Master {master.key} unreachable, all non-delayed replicas lagging")

        if unreachable:
            return FailureAnalysis(FailureType.DEAD_MASTER_AND_SOME_REPLICAS,
                                   master, True, cn,
                                   f"Master {master.key} dead, {len(unreachable)} replicas also dead")

        return FailureAnalysis(FailureType.DEAD_MASTER,
                               master, True, cn,
                               f"Master {master.key} dead, all replicas failing replication")

    def _master_reachable(self, state, master, replicas, cn):
        if len(replicas) == 0:
            return None

        reachable = [r for r in replicas if r.is_reachable]
        unreachable = [r for r in replicas if not r.is_reachable]

        # Semi-sync checks
        if master.semi_sync_master_enabled:
            connected_ss = [
                r for r in reachable
                if r.semi_sync_replica_enabled
                and r.replication_state == ReplicationState.RUNNING
            ]
            if len(connected_ss) < master.semi_sync_master_wait_count:
                if master.semi_sync_master_timeout_ms >= 30000:
                    return FailureAnalysis(
                        FailureType.LOCKED_SEMI_SYNC_MASTER,
                        master, True, cn,
                        f"Master {master.key} locked: semi-sync acks "
                        f"({len(connected_ss)}) < wait_count ({master.semi_sync_master_wait_count})")
            if len(connected_ss) > master.semi_sync_master_wait_count:
                if state.cluster_config.enforce_exact_semi_sync_replicas:
                    return FailureAnalysis(
                        FailureType.MASTER_WITH_TOO_MANY_SEMI_SYNC_REPLICAS,
                        master, False, cn,
                        f"Master {master.key}: too many semi-sync replicas "
                        f"({len(connected_ss)}) > wait_count ({master.semi_sync_master_wait_count})")

        # All replicas unreachable
        if len(reachable) == 0 and unreachable:
            return FailureAnalysis(
                FailureType.ALL_MASTER_REPLICAS_NOT_REPLICATING_OR_DEAD,
                master, True, cn,
                f"Master {master.key} OK, all replicas unreachable")

        not_replicating = [
            r for r in reachable
            if r.replication_state in (ReplicationState.FAILED, ReplicationState.STOPPED)
        ]
        if reachable and len(not_replicating) == len(reachable):
            if unreachable:
                return FailureAnalysis(
                    FailureType.ALL_MASTER_REPLICAS_NOT_REPLICATING_OR_DEAD,
                    master, True, cn,
                    f"Master {master.key} OK, all replicas not replicating or dead")
            return FailureAnalysis(
                FailureType.ALL_MASTER_REPLICAS_NOT_REPLICATING,
                master, True, cn,
                f"Master {master.key} OK, all replicas stopped replicating")

        return None

    # ------------------------------------------------------------------

    def _analyze_intermediate_master(self, state, im, replicas):
        cn = state.cluster_config.cluster_name
        if not im.is_reachable:
            return self._im_unreachable(im, replicas, cn)
        return self._im_reachable(im, replicas, cn)

    def _im_unreachable(self, im, replicas, cn):
        reachable = [r for r in replicas if r.is_reachable]
        unreachable = [r for r in replicas if not r.is_reachable]

        if len(reachable) == 0:
            if len(replicas) == 1:
                return FailureAnalysis(
                    FailureType.DEAD_INTERMEDIATE_MASTER_WITH_SINGLE_REPLICA_FAILING_TO_CONNECT,
                    im, False, cn,
                    f"IM {im.key} dead, single replica also unreachable")
            return FailureAnalysis(
                FailureType.DEAD_INTERMEDIATE_MASTER_AND_REPLICAS,
                im, False, cn,
                f"IM {im.key} and all replicas dead")

        non_delayed = [r for r in reachable if not r.is_sql_delayed]
        replicating = [r for r in non_delayed
                       if r.replication_state == ReplicationState.RUNNING]
        if replicating:
            return FailureAnalysis(
                FailureType.UNREACHABLE_INTERMEDIATE_MASTER,
                im, False, cn,
                f"IM {im.key} unreachable, replicas still replicating")

        lagging = [r for r in non_delayed
                   if r.replication_state == ReplicationState.LAGGING]
        if non_delayed and len(lagging) == len(non_delayed):
            return FailureAnalysis(
                FailureType.UNREACHABLE_INTERMEDIATE_MASTER_WITH_LAGGING_REPLICAS,
                im, True, cn,
                f"IM {im.key} unreachable, all non-delayed replicas lagging")

        if unreachable:
            return FailureAnalysis(
                FailureType.DEAD_INTERMEDIATE_MASTER_AND_SOME_REPLICAS,
                im, True, cn,
                f"IM {im.key} dead, some replicas also dead")

        if len(replicas) == 1:
            return FailureAnalysis(
                FailureType.DEAD_INTERMEDIATE_MASTER_WITH_SINGLE_REPLICA,
                im, True, cn,
                f"IM {im.key} dead, single replica failing")

        return FailureAnalysis(
            FailureType.DEAD_INTERMEDIATE_MASTER,
            im, True, cn,
            f"IM {im.key} dead, all replicas failing replication")

    def _im_reachable(self, im, replicas, cn):
        reachable = [r for r in replicas if r.is_reachable]
        unreachable = [r for r in replicas if not r.is_reachable]

        if len(reachable) == 0 and unreachable:
            return FailureAnalysis(
                FailureType.ALL_INTERMEDIATE_MASTER_REPLICAS_FAILING_TO_CONNECT_OR_DEAD,
                im, True, cn,
                f"IM {im.key} OK, all replicas unreachable")

        not_replicating = [
            r for r in reachable
            if r.replication_state in (ReplicationState.FAILED, ReplicationState.STOPPED)
        ]
        if reachable and len(not_replicating) == len(reachable):
            return FailureAnalysis(
                FailureType.ALL_INTERMEDIATE_MASTER_REPLICAS_NOT_REPLICATING,
                im, True, cn,
                f"IM {im.key} OK, all replicas stopped replicating")

        return None

    # ------------------------------------------------------------------
    # Recovery decision
    # ------------------------------------------------------------------

    def should_recover(self, state: TopologyState,
                       failure: FailureAnalysis) -> RecoveryDecision:
        if not failure.is_actionable:
            return RecoveryDecision(False, "Failure type is not actionable")
        cfg = state.cluster_config
        if not cfg.global_recoveries_enabled:
            return RecoveryDecision(False, "Global recoveries are disabled")
        if not cfg.auto_recovery_enabled:
            return RecoveryDecision(False, "Auto-recovery is disabled for this cluster")
        if failure.failed_instance.is_downtimed:
            return RecoveryDecision(False, "Instance is downtimed")
        if cfg.last_recovery_timestamp is not None:
            elapsed = state.current_timestamp - cfg.last_recovery_timestamp
            if elapsed < cfg.recovery_period_block_seconds:
                return RecoveryDecision(
                    False,
                    f"Anti-flapping: {elapsed:.0f}s since last recovery "
                    f"(block period: {cfg.recovery_period_block_seconds}s)")
        return RecoveryDecision(True, "All recovery conditions met")

    # ------------------------------------------------------------------
    # Candidate selection
    # ------------------------------------------------------------------

    def select_promotion_candidate(self, state: TopologyState,
                                   failed_server: Server) -> Optional[Server]:
        replicas = self.get_replicas(state, failed_server)
        candidates = [
            r for r in replicas
            if r.is_reachable and r.promotion_rule != PromotionRule.MUST_NOT
        ]
        if not candidates:
            return None

        rule_order = {
            PromotionRule.PREFER: 0,
            PromotionRule.NEUTRAL: 1,
            PromotionRule.PREFER_NOT: 2,
        }

        def key(s):
            return (
                rule_order.get(s.promotion_rule, 1),
                0 if s.semi_sync_replica_enabled else 1,
                -s.gtid_position,
                0 if s.datacenter == failed_server.datacenter else 1,
                s.hostname,
            )

        candidates.sort(key=key)
        return candidates[0]

    # ------------------------------------------------------------------
    # Raft leader
    # ------------------------------------------------------------------

    def determine_raft_leader(self,
                              orchestrator_nodes: List[OrchestratorNode]
                              ) -> Optional[OrchestratorNode]:
        if not orchestrator_nodes:
            return None
        total = len(orchestrator_nodes)
        quorum = (total // 2) + 1
        eligible = []
        for node in orchestrator_nodes:
            reachable = 1  # self
            for other in orchestrator_nodes:
                if other.hostname != node.hostname:
                    if node.is_reachable_from.get(other.hostname, False):
                        reachable += 1
            if reachable >= quorum:
                eligible.append((node, reachable))
        if not eligible:
            return None
        eligible.sort(key=lambda x: (-x[1], x[0].hostname))
        return eligible[0][0]

    # ------------------------------------------------------------------
    # Outage estimation
    # ------------------------------------------------------------------

    def estimate_outage_seconds(self, state: TopologyState,
                                failure: FailureAnalysis,
                                candidate: Optional[Server]) -> float:
        if candidate is None:
            return 0.0
        detection = 5.0
        ideal = (candidate.promotion_rule == PromotionRule.PREFER
                 and candidate.semi_sync_replica_enabled)
        promotion = 3.0 if ideal else 10.0
        cross_dc = candidate.datacenter != failure.failed_instance.datacenter
        consul = 2.0 if cross_dc else 1.0
        haproxy = 2.0 if cross_dc else 1.0
        return detection + promotion + consul + haproxy

    # ------------------------------------------------------------------
    # Full pipeline
    # ------------------------------------------------------------------

    def execute_recovery(self, state: TopologyState) -> RecoveryReport:
        report = RecoveryReport()
        report.failures = self.analyze_failure(state)
        if not report.failures:
            return report

        report.raft_leader = self.determine_raft_leader(state.orchestrator_nodes)
        if report.raft_leader is None and len(state.orchestrator_nodes) > 0:
            report.recovery_blocked_reason = (
                "No raft quorum - cannot proceed with recovery")
            return report

        # Prefer actionable master-level failures
        target = None
        for f in report.failures:
            if f.is_actionable and f.failed_instance.master_hostname is None:
                target = f
                break
        if target is None:
            for f in report.failures:
                if f.is_actionable:
                    target = f
                    break
        if target is None:
            return report

        decision = self.should_recover(state, target)
        if not decision.should_recover:
            report.recovery_blocked_reason = decision.reason
            return report

        report.recovery_attempted = True
        report.promoted_server = self.select_promotion_candidate(
            state, target.failed_instance)
        report.estimated_outage_seconds = self.estimate_outage_seconds(
            state, target, report.promoted_server)
        return report
