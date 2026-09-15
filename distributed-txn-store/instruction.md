Implement a distributed transactional key-value store node for the Maelstrom `txn-rw-register` workload. Maelstrom is installed at `/opt/maelstrom/` (documentation in `/opt/maelstrom/doc/`). Place your executable node binary at `/app/node`.

Your node communicates via newline-delimited JSON messages over STDIN/STDOUT. It must handle `init` (receiving its node ID and cluster membership) and `txn` messages. Each `txn` contains an ordered list of micro-operations -- reads `["r", key, null]` and writes `["w", key, value]` -- over integer-keyed registers. Reads must be filled in with current values; writes set register values. Respond with `txn_ok` containing the completed operation list.

The node must replicate writes across a multi-node cluster (2+ nodes) while satisfying **Read Committed** consistency under the Adya isolation model -- preventing G0 (dirty write), G1a (aborted read), G1b (intermediate read), and G1c (circular information flow). It must remain **totally available** during network partitions: every transaction must receive a response even when nodes cannot communicate.

The hardest verification runs Maelstrom with network fault injection and checks both consistency and availability:

```
/opt/maelstrom/maelstrom test -w txn-rw-register --bin /app/node \
  --node-count 2 --concurrency 2n --time-limit 10 --rate 500 \
  --consistency-models read-committed --availability total --nemesis partition
```