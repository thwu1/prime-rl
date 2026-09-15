Partition log segments at `/app/data/` contain Kafka RecordBatch data for topics `orders` (partitions 0–1), `events` (partitions 0–1), and `metrics` (partition 0). Several segments are corrupted and must be repaired in-place before they can be served.

Write a repair tool at `/app/repair_tool.py` that detects and fixes corruptions in the RecordBatch log files under `/app/data/`. Write a corruption report to `/app/report.json` containing a `"corruptions"` array where each entry has `"file"` (path relative to `/app/data/`, e.g. `orders-0/00000000000000000000.log`), `"batch_index"` (0-based), `"type"` (one of: `invalid_crc`, `invalid_batch_length`, `invalid_magic`, `invalid_record_count`, `invalid_timestamps`), and `"details"`.

Build a Kafka-wire-protocol-compatible TCP server at `/app/broker.py` listening on port 9092 that handles ApiVersions (API key 18), Metadata (API key 3), and Fetch (API key 1) requests, serving the repaired records from `/app/data/`. The broker must support version negotiation including flexible-version headers (ApiVersions v3 with compact arrays and tagged fields) so that standard Kafka clients can connect.

After repairing the logs and starting the broker (`python3 /app/broker.py &`), verify by connecting via the Kafka wire protocol and fetching from each topic — you should receive these record values:
- `orders`: 5 messages (3 from partition 0, 2 from partition 1) with order details
- `events`: 7 messages (4 from partitions 0, 3 from partition 1) with user and page events
- `metrics`: 2 messages with system metric readings

If `kcat` is available, you can also verify with:
```
kcat -b localhost:9092 -C -t orders -o 0 -e -q
kcat -b localhost:9092 -C -t events -o 0 -e -q
kcat -b localhost:9092 -C -t metrics -o 0 -e -q
```

Topic names derive from partition directory names (`orders-0` → topic `orders`, partition 0).

Reference: `/app/format_reference.txt` (RecordBatch on-disk format), `/app/wire_reference.txt` (Kafka wire protocol and API message layouts). Pre-installed tools: `xxd`, `nc`.