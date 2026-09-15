Implement a Kafka broker at `/app/run.sh` that listens on TCP port 9092 and handles four Kafka binary wire protocol APIs by reading pre-generated binary log files from `/data/kraft-combined-logs/`. The broker must be compatible with `kcat -L -b localhost:9092` for metadata listing.

## APIs to implement

- **ApiVersions** (API key 18, versions 0–4): Return supported API keys and their version ranges. Response header v0 (correlation ID only). Return error code 35 (UNSUPPORTED_VERSION) for versions outside 0–4.

- **Metadata** (API key 3, versions 0–1): Return broker information (node_id 1, host localhost, port 9092) and topic/partition metadata discovered from the cluster metadata binary log at `/data/kraft-combined-logs/__cluster_metadata-0/00000000000000000000.log`. Uses old-style encoding: INT32 array counts, INT16 string lengths. Response header v0. Version 1 adds rack (nullable), controller_id, and is_internal fields. A null topics array (count = -1) means list all topics. This API enables `kcat` interoperability.

- **DescribeTopicPartitions** (API key 75, version 0): Return topic UUIDs and partition leader/replica info from the cluster metadata log. Error code 3 (UNKNOWN_TOPIC_OR_PARTITION) with zeroed UUID for unknown topics. Response header v1 (correlation ID + tagged fields). Null cursor (`0xff`).

- **Fetch** (API key 1, version 16): Serve raw RecordBatch bytes from `/data/kraft-combined-logs/<topic>-<partition>/00000000000000000000.log`, keyed by topic UUID. Error code 100 (UNKNOWN_TOPIC_ID) for unknown UUIDs. Records use COMPACT_NULLABLE_BYTES encoding. Response header v1.

## Protocol encoding

All integers big-endian. **Request header format varies by API version**: flexible APIs (ApiVersions v3+, DescribeTopicPartitions v0+, Fetch v12+) use header v2: api_key(INT16) + api_version(INT16) + correlation_id(INT32) + client_id(NULLABLE_STRING) + tagged_fields(uvarint). Non-flexible APIs (Metadata v0–1, ApiVersions v0–2, Fetch v0–11) use header v1: same fields without trailing tagged_fields. Handling this distinction correctly is essential — `kcat` sends Metadata requests with header v1, and the broker must not attempt to read a tag buffer that is not present.

Metadata API uses old-style encoding: INT32(count) + elements for arrays, INT16(length) + bytes for strings. The other APIs (DescribeTopicPartitions, Fetch, ApiVersions v3+) use compact encoding: uvarint(count+1) + elements, uvarint(len+1) + bytes.

The cluster metadata log contains RecordBatches whose records use zigzag varint encoding; typed payloads include TopicRecord (type 2, maps name→UUID) and PartitionRecord (type 3, version 1, defines partition assignments with a compact array of directory UUIDs).

The environment includes `kcat`, `tshark`, and `tcpdump` for protocol analysis and interoperability testing. The fixture generator at `/setup/generate_fixtures.py` is a binary encoding reference.