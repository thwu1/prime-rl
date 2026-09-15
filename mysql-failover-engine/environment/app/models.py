"""
MySQL HA Topology Models

Data models representing MySQL replication topology components,
modeled after GitHub's orchestrator-based HA infrastructure.

"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Dict


class FailureType(Enum):
    """Orchestrator failure detection taxonomy."""
    NO_FAILURE = "NoFailure"
    DEAD_MASTER = "DeadMaster"
    DEAD_MASTER_AND_REPLICAS = "DeadMasterAndReplicas"
    DEAD_MASTER_AND_SOME_REPLICAS = "DeadMasterAndSomeReplicas"
    DEAD_MASTER_WITHOUT_REPLICAS = "DeadMasterWithoutReplicas"
    UNREACHABLE_MASTER = "UnreachableMaster"
    UNREACHABLE_MASTER_WITH_LAGGING_REPLICAS = "UnreachableMasterWithLaggingReplicas"
    LOCKED_SEMI_SYNC_MASTER = "LockedSemiSyncMaster"
    MASTER_WITH_TOO_MANY_SEMI_SYNC_REPLICAS = "MasterWithTooManySemiSyncReplicas"
    ALL_MASTER_REPLICAS_NOT_REPLICATING = "AllMasterReplicasNotReplicating"
    ALL_MASTER_REPLICAS_NOT_REPLICATING_OR_DEAD = "AllMasterReplicasNotReplicatingOrDead"
    DEAD_INTERMEDIATE_MASTER = "DeadIntermediateMaster"
    DEAD_INTERMEDIATE_MASTER_WITH_SINGLE_REPLICA = "DeadIntermediateMasterWithSingleReplica"
    DEAD_INTERMEDIATE_MASTER_WITH_SINGLE_REPLICA_FAILING_TO_CONNECT = "DeadIntermediateMasterWithSingleReplicaFailingToConnect"
    DEAD_INTERMEDIATE_MASTER_AND_SOME_REPLICAS = "DeadIntermediateMasterAndSomeReplicas"
    DEAD_INTERMEDIATE_MASTER_AND_REPLICAS = "DeadIntermediateMasterAndReplicas"
    ALL_INTERMEDIATE_MASTER_REPLICAS_FAILING_TO_CONNECT_OR_DEAD = "AllIntermediateMasterReplicasFailingToConnectOrDead"
    ALL_INTERMEDIATE_MASTER_REPLICAS_NOT_REPLICATING = "AllIntermediateMasterReplicasNotReplicating"
    UNREACHABLE_INTERMEDIATE_MASTER = "UnreachableIntermediateMaster"
    UNREACHABLE_INTERMEDIATE_MASTER_WITH_LAGGING_REPLICAS = "UnreachableIntermediateMasterWithLaggingReplicas"


class PromotionRule(Enum):
    """Promotion preference for a server during failover."""
    MUST_NOT = "must_not"
    PREFER_NOT = "prefer_not"
    NEUTRAL = "neutral"
    PREFER = "prefer"


class ReplicationState(Enum):
    """State of replication on a replica."""
    RUNNING = "running"
    LAGGING = "lagging"
    STOPPED = "stopped"
    FAILED = "failed"


@dataclass
class Server:
    """Represents a MySQL server instance in a replication topology."""
    hostname: str
    port: int = 3306
    datacenter: str = "dc1"
    is_reachable: bool = True

    master_hostname: Optional[str] = None
    master_port: Optional[int] = None
    replication_state: ReplicationState = ReplicationState.RUNNING
    replication_lag_seconds: float = 0.0
    gtid_position: int = 0
    is_sql_delayed: bool = False

    read_only: bool = True
    binlog_format: str = "ROW"
    mysql_version: str = "8.0.28"
    log_slave_updates: bool = True

    semi_sync_master_enabled: bool = False
    semi_sync_replica_enabled: bool = False
    semi_sync_master_wait_count: int = 1
    semi_sync_master_timeout_ms: int = 500

    promotion_rule: PromotionRule = PromotionRule.NEUTRAL
    is_downtimed: bool = False

    @property
    def key(self) -> str:
        return f"{self.hostname}:{self.port}"


@dataclass
class OrchestratorNode:
    """Represents an orchestrator instance in a raft cluster."""
    hostname: str
    datacenter: str
    is_reachable_from: Dict[str, bool] = field(default_factory=dict)


@dataclass
class ClusterConfig:
    """Configuration for a MySQL cluster's recovery behavior."""
    cluster_name: str = "default"
    auto_recovery_enabled: bool = True
    recovery_period_block_seconds: int = 3600
    last_recovery_timestamp: Optional[float] = None
    global_recoveries_enabled: bool = True
    reasonable_replication_lag_seconds: float = 10.0
    reasonable_locked_semi_sync_seconds: float = 10.0
    enforce_exact_semi_sync_replicas: bool = False
    recover_locked_semi_sync_master: bool = False


@dataclass
class TopologyState:
    """Complete snapshot of a MySQL HA topology at a point in time."""
    servers: List[Server] = field(default_factory=list)
    orchestrator_nodes: List[OrchestratorNode] = field(default_factory=list)
    cluster_config: ClusterConfig = field(default_factory=ClusterConfig)
    current_timestamp: float = 0.0


@dataclass
class FailureAnalysis:
    """Result of analyzing a potential failure in the topology."""
    failure_type: FailureType
    failed_instance: Server
    is_actionable: bool
    cluster_name: str
    description: str = ""


@dataclass
class RecoveryDecision:
    """Whether and why recovery should or should not proceed."""
    should_recover: bool
    reason: str = ""


@dataclass
class RecoveryReport:
    """Full report from a recovery pipeline execution."""
    failures: List[FailureAnalysis] = field(default_factory=list)
    recovery_attempted: bool = False
    promoted_server: Optional[Server] = None
    raft_leader: Optional[OrchestratorNode] = None
    estimated_outage_seconds: float = 0.0
    recovery_blocked_reason: str = ""
