# Reference Scenarios

These JSON files contain topology snapshots from past incidents with annotated expected outcomes. Use them to understand how the failover engine should classify failures and make recovery decisions.

Each scenario contains:
- `servers`: List of MySQL server instances with their current state
- `orchestrator_nodes`: List of orchestrator nodes with connectivity information (for raft consensus)
- `cluster_config`: Cluster-level configuration parameters
- `current_timestamp`: Current time (for anti-flapping calculations)
- `expected`: Expected failure analysis results and recovery outcomes

Server field reference:
- `replication_state`: one of `"running"`, `"lagging"`, `"stopped"`, `"failed"`
- `promotion_rule`: one of `"prefer"`, `"neutral"`, `"prefer_not"`, `"must_not"`
- `is_sql_delayed`: `true` for replicas configured with `SQL_Delay`
- `master_hostname`: `null` for top-level masters

These scenarios are illustrative examples. The test suite covers additional edge cases beyond what is shown here.
