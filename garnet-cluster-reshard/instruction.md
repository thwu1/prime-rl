A 3-node Microsoft Garnet cluster is running on ports 7000-7002 (initialized by `/opt/garnet/init_cluster.sh`). The cluster uses Garnet's passive control plane model. Slot distribution: port 7000 owns [0-5460], port 7001 owns [5461-10922], port 7002 owns [10923-16383]. 500 keys (`key:0000` through `key:0499`) with values (`val:0000` through `val:0499`) have been loaded.

Write `/app/reshard.py` to expand this cluster to 4 balanced masters with a replica:

1. Rebalance so that each of 4 master nodes (ports 7000-7003) owns approximately 4096 hash slots (within ±10 of 4096). All 16384 slots must be covered.

2. Start a 5th instance on port 7004 configured as a replica of the port 7003 primary using AOF-based replication. The replica must be actively replicating (`master_link_status:up`).

3. All 500 original keys must be accessible with correct values after the operation completes.

4. Write `/app/cluster_report.json` containing:
   - `nodes`: list of objects with `id` (string), `port` (int), `role` ("master" or "replica"), `slot_count` (int)
   - `total_keys_verified`: integer (must be 500)
   - `replica_replicating`: boolean (must be true)

The `garnet-server` binary is on PATH. Each instance requires `--checkpointdir` (unique per instance), `--cluster`, `--aof`, and `--config-import-path /opt/garnet/garnet.conf`. Garnet implements the RESP protocol with standard Redis cluster commands (`CLUSTER MEET`, `CLUSTER NODES`, `CLUSTER ADDSLOTSRANGE`, `CLUSTER SET-CONFIG-EPOCH`, `CLUSTER SETSLOT`, `CLUSTER SETSLOTRANGE`, `CLUSTER REPLICATE`, `CLUSTER MYID`, `CLUSTER GETKEYSINSLOT`, `CLUSTER MTASKS`, `MIGRATE`) plus `MIGRATE ... SLOTSRANGE` for bulk slot migration. `SET-CONFIG-EPOCH` must be called on fresh nodes (empty config, epoch 0) before `CLUSTER MEET`. Note that Garnet's passive control plane differs from Redis in important ways — not all migration approaches that work in Redis will work identically in Garnet, and the `MIGRATE SLOTSRANGE` variant has restrictions on target node state that may require alternative strategies.