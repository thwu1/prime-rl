A KRaft-mode Kafka broker's data directory at `/app/kafka-data/` was recovered after a storage controller failure. The cluster metadata log is intact, but several partition log segments contain various forms of corruption. Some partitions use compressed RecordBatches.

## Environment

- `/app/kafka-data/` — recovered broker data directory containing cluster metadata and partition logs
- `/app/kafka-data/format_reference.txt` — RecordBatch binary format specification (read this carefully)
- `/opt/kafka/` — Apache Kafka 3.7.1 installation

## Goal

Determine the broker's complete topic/partition topology from the recovered data. Identify and repair all corrupted partition logs so that every partition contains only structurally valid RecordBatches that conform to the specification in `format_reference.txt`. Corrupted data that cannot be made structurally valid must be discarded.

Write repaired log files to `/app/repaired/<topic>-<partition>/00000000000000000000.log`.

Write a forensic manifest to `/app/repaired/manifest.json` with the following structure:

```json
{
  "topics": [
    {
      "name": "<topic name>",
      "uuid": "<lowercase hyphenated UUID>",
      "partitions": [
        {
          "id": 0,
          "batches": 2,
          "records": 5,
          "compression": "none",
          "corruptions": ["corruption_type_1"]
        }
      ]
    }
  ]
}
```

Each partition entry reports post-repair batch and record counts, the compression codec used (`"none"` or `"gzip"`), and an array of corruption types found in the original log (empty if the partition was already valid).