A hex-encoded packet capture from industrial controller diagnostic sessions is at `/app/capture.hex` (one packet per line). The SIDP protocol specification is at `/app/protocol_spec.txt`.

Produce two files:

**`/app/sidp_layers.py`** — A Scapy-based implementation of the complete SIDP protocol stack that correctly parses and reconstructs any packet in the capture, handling all protocol versions, conditional header layouts, integrity checks, payload dispatch, and parameter encoding described in the specification. Must export `craft_response(hex_request: str) -> str`: given a hex-encoded ReadParam request, return a hex-encoded valid ReadParam response with param value `\x00\x00\x00\x00`, same session_id, sequence incremented by 1, and the response flag set.

**`/app/analyze.py`** — Forensic analysis script that parses every packet in the capture using your implementation and writes `/app/analysis.json` containing:

- `total_packets` — integer count
- `unique_session_ids` — sorted list of zero-padded hex strings (e.g. `"0x00005678"`)
- `anomaly_indices` — sorted 0-based indices of packets violating protocol rules
- `anomaly_reasons` — map of index string to violation category string as defined in the specification
- `device_type`, `firmware_version`, `serial_number` — extracted from the appropriate service responses
- `parameters` — map of hex param ID (e.g. `"0x0001"`) to extracted value, using the data type encoding rules in the specification
- `reassembled_firmware_crc32` — CRC-32 hex string of reassembled fragment transfer payload (e.g. `"0xaabbccdd"`)
- `reassembled_firmware_size` — byte count of reassembled payload

Scapy is pre-installed.