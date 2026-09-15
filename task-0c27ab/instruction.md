A Kafka 3.7 broker running in KRaft mode crashed during a rolling upgrade. Its data directory at `/app/kafka-data/` contains partition logs for two user topics (`alpha-topic` with partitions 0-1, `beta-topic` with partitions 0-1) and the `__cluster_metadata-0` internal topic storing cluster topology as binary-encoded TopicRecord, PartitionRecord, and FeatureLevelRecord payloads.

Multiple forms of corruption affect log segments (`.log`), offset index files (`.index`), and leader-epoch-checkpoint files across the data directory. A ground-truth manifest at `/app/manifest.json` describes the expected topics, partitions, leader epochs, and record values.

Use `xxd` for byte-level inspection of binary headers and CRC fields. Write Python scripts for parsing and repairing the binary structures.

## Requirements

1. **Diagnose all corruptions** by parsing log segments and cross-referencing with the manifest
2. **Repair all `.log` files** -- Fix CRC32-Castagnoli errors (reflected polynomial 0x82F63B78) where data is intact, reconstruct from the manifest where record data is corrupted, and recreate missing partition directories with valid log data. Each RecordBatch uses big-endian encoding: baseOffset(i64), batchLength(i32), partitionLeaderEpoch(i32), magic(i8)=2, CRC(u32), then properties bytes (CRC covers attributes through end of records). Individual records use zigzag-encoded signed varints.
3. **Regenerate `.index` files** -- Offset index entries are 8-byte pairs of (relative_offset: i32, physical_position: i32), both big-endian. Each entry maps a batch's base offset to its byte position in the `.log` file. All partition directories (including `__cluster_metadata-0`) must have a valid `.index` file consistent with the repaired `.log`.
4. **Fix `leader-epoch-checkpoint` files** -- Each user-topic partition directory must contain a valid checkpoint (line 1: version `0`, line 2: entry count, subsequent lines: `<epoch> <start_offset>`) with epochs matching the manifest's `leader_epoch` values
5. **Complete cluster metadata** -- The `__cluster_metadata-0` log must contain TopicRecord and PartitionRecord entries for every topic and partition. Cluster metadata record values use frame_version(i8), type(i8), version(i8), then type-specific fields with Kafka compact encoding (uvarint(len+1) for strings/arrays)
6. **Write corruption report** to `/app/report.json`

## Report Format (`/app/report.json`)

```json
{
  "corruptions": [
    {"file": "<path relative to kafka-data/>", "type": "<type>", "details": "<description>"}
  ],
  "topology": {
    "<topic_name>": {"uuid_hex": "<32-char lowercase hex of 16-byte UUID>", "partitions": [<sorted partition indices>]}
  }
}
```

Valid corruption types: `invalid_crc`, `corrupted_data`, `missing_file`, `missing_partition_record`, `stale_index`, `invalid_checkpoint`

The `topology` section must reflect the **repaired** cluster metadata state.