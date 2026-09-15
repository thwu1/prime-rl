`/app/capture.bin` contains a COBS-framed postcard-RPC binary stream captured from an embedded device's serial interface. Rust serde type definitions are in `/app/schema.rs`, protocol documentation in `/app/protocol_notes.txt`, and a Cargo project scaffold with `postcard` and `serde` dependencies at `/app/decoder/`.

The capture contains six message types: `TempReading`, `MotorCommand`, `StatusReport`, `BatchSamples`, `ConfigEntry`, and `SystemEvent`. Wire keys for only `TempReading` and `MotorCommand` are provided directly in the schema. The remaining four keys must be derived by computing FNV1a-64 hashes over the RPC path, a null separator byte, and the canonical type schema string, following the procedure in `/app/protocol_notes.txt`.

`SystemEvent` contains a nested `EventKind` enum with four variant kinds (two struct variants, one newtype, one unit). Its canonical schema string has deeply nested structure where the flat comma-separated format creates ambiguity between enum variant boundaries and struct field boundaries that must be resolved using the casing convention. Constructing this schema string correctly may require building and experimenting with the Cargo project at `/app/decoder/` to validate against the real `postcard` crate's serialization behavior.

The stream also contains corrupted frames. Use `xxd` to inspect the raw binary data of corrupted frames and classify each by error category: `cobs_error` (COBS decode failure), `header_too_short` (decoded payload under 9 bytes), or `unknown_key` (valid decode but unrecognized key). Report the first 16 hex characters of each corrupted frame's COBS-encoded bytes (or the full hex if shorter than 8 bytes).

After decoding all valid frames, re-encode each one back to its complete COBS-framed wire representation and verify byte-perfect round-trip correctness against the original frame bytes.

Perform cross-message thermal correlation: for each `MemoryWarning`-variant `SystemEvent`, find all valid `TempReading` messages whose `timestamp_ms` falls within +-2000ms of the event's `timestamp_ms`. Report the count and mean `celsius_x100` of matching readings.

Write results to `/app/analysis.json`:

```json
{
  "total_frames": "<int: all extracted frames including invalid>",
  "valid_frames": "<int>",
  "invalid_frames": "<int>",
  "derived_keys": {
    "StatusReport": "<16-char lowercase hex of LE u64>",
    "BatchSamples": "<16-char lowercase hex>",
    "ConfigEntry": "<16-char lowercase hex>",
    "SystemEvent": "<16-char lowercase hex>"
  },
  "round_trip_success": "<int: valid frames whose re-encoding matches>",
  "message_counts": {
    "TempReading": "<int>", "MotorCommand": "<int>",
    "StatusReport": "<int>", "BatchSamples": "<int>",
    "ConfigEntry": "<int>", "SystemEvent": "<int>"
  },
  "invalid_frame_details": [
    {"frame_index": "<int: 0-based position in stream>",
     "raw_hex_prefix": "<first 16 hex chars of COBS payload, or full hex if shorter>",
     "error_category": "<cobs_error|header_too_short|unknown_key>"}
  ],
  "temp_analysis": {
    "min_celsius_x100": "<int>", "max_celsius_x100": "<int>",
    "mean_celsius_x100": "<float>",
    "unique_sensor_ids": ["<sorted ints>"],
    "invalid_count": "<int: TempReadings where valid is false>"
  },
  "motor_analysis": {
    "max_abs_speed_rpm": "<int>",
    "total_duration_ms": "<int>"
  },
  "fault_sequence_numbers": ["<sorted seq_nos of Fault-variant StatusReports>"],
  "calibration_offset_sums": ["<int, int, int>: element-wise sum"],
  "recovery_gaps": ["<sorted: seq_no gaps from each Fault to next Idle>"],
  "unrecovered_faults": "<int>",
  "batch_total_samples": "<int>",
  "batch_channel_counts": {"<channel_id>": "<int>"},
  "config_none_count": "<int>",
  "system_event_summary": {
    "boot_count": "<int>",
    "watchdog_reset_total": "<int: sum of Watchdog counter values>",
    "memory_warning_count": "<int>",
    "shutdown_count": "<int>",
    "firmware_versions": ["<sorted unique strings>"],
    "unique_source_ids": ["<sorted ints>"],
    "peak_memory_used_kb": "<int: max used_kb across MemoryWarning events>"
  },
  "thermal_correlation": [
    {"event_timestamp_ms": "<int>",
     "nearby_temp_count": "<int>",
     "nearby_temp_mean_x100": "<float>"}
  ]
}
```