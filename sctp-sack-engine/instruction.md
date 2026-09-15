Analyze a WebRTC data channel session captured across three artifacts and produce a unified protocol-level analysis in `/app/results.json`.

## Artifacts

**`/app/handshake.pcap`** — A pcap file (LINKTYPE_RAW/IPv4, SCTP protocol 132) containing the SCTP INIT and INIT-ACK exchange that established the association. Use `tshark` to extract the negotiated association parameters. The pcap uses CRC-32C checksums; you may need to configure tshark's SCTP checksum validation preference if it flags them.

**`/app/dcep_payloads.bin`** — Binary file containing serialized DCEP (Data Channel Establishment Protocol, RFC 8832) DATA_CHANNEL_OPEN messages. Each entry is framed as: 2 bytes big-endian stream ID, 2 bytes big-endian payload length, then the raw DATA_CHANNEL_OPEN message bytes. A DATA_CHANNEL_OPEN message has the structure: message_type(1 byte, always 0x03), channel_type(1 byte), priority(2 bytes BE), reliability_parameter(4 bytes BE), label_length(2 bytes BE), protocol_length(2 bytes BE), label(variable), protocol(variable).

**`/app/session_trace.json`** — A JSON event trace of the data transfer phase with three event types: `data_received` (a DATA chunk arrived with `tsn`, `stream_id`, `ssn`), `forward_tsn` (a FORWARD-TSN chunk per RFC 3758 with `id`, `new_cumulative_tsn`, and `streams`), and `compute_sack` (compute SACK fields at this checkpoint, identified by `id`). The trace includes `initial_tsn` for the sending endpoint. TSN arithmetic uses uint32 with serial number comparison (RFC 1982). The receiver's initial cumulative TSN ack is `initial_tsn - 1` (uint32 arithmetic).

## Required output

Save `/app/results.json` with this structure:

```json
{
  "association": {
    "a_initiate_tag": <uint32 from INIT>,
    "b_initiate_tag": <uint32 from INIT-ACK>,
    "a_initial_tsn": <uint32 from INIT>,
    "b_initial_tsn": <uint32 from INIT-ACK>,
    "a_rwnd": <uint32 from INIT>,
    "b_rwnd": <uint32 from INIT-ACK>
  },
  "data_channels": [
    {"stream_id": <int>, "label": "<string>", "channel_type": <int>,
     "priority": <int>, "reliability_param": <int>, "protocol": "<string>"}
  ],
  "sacks": {
    "<checkpoint_id>": {
      "cumulative_tsn": <uint32>,
      "gap_blocks": [[start_offset, end_offset], ...],
      "dup_tsns": [<tsn>, ...]
    }
  },
  "abandoned_tsns": {
    "<forward_tsn_id>": [<tsn>, ...]
  }
}
```

Gap Ack Block offsets use RFC 4960 Section 3.3.4 encoding: `actual_TSN = cumulative_tsn + offset`. Blocks must be sorted ascending. Duplicate TSN list contains TSNs received more than once since the previous `compute_sack` checkpoint. The `abandoned_tsns` for each FORWARD-TSN event lists TSNs in the range `(old_cumulative_tsn, new_cumulative_tsn]` that were NOT received at the time the FORWARD-TSN was processed (sorted ascending).