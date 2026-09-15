# Network Telemetry Binary Format Specification

## Overview

Binary telemetry data files in `/app/data/` represent BPF map dumps from an
eBPF-based network observability system. A packet capture of the monitored
traffic is at `/app/data/capture.pcap`. Anomaly detection thresholds are
configured in `/app/anomaly_config.yaml`.

## Files

| File | Record Type | Record Size |
|------|------------|-------------|
| `conntrack_entries.bin` | ConntrackRecord | 160 bytes |
| `drop_events.bin` | DropRecord | 24 bytes |
| `dns_events.bin` | DnsEvent | 24 bytes |
| `tcp_retransmits.bin` | RetransmitEvent | 20 bytes |
| `capture.pcap` | libpcap format | variable |

Each binary file is a flat array of fixed-size records with **no file header**.
Determine record count from `file_size / record_size`.

## Byte Order Convention

Network protocol fields (IP addresses, ports) are **big-endian** (network byte
order). All other fields (counters, timestamps, state values) are
**little-endian** (x86 host byte order). Padding bytes are zero-filled.

---

## Record Formats

### ConntrackKey (16 bytes)

| Offset | Size | Type | Endian | Field | Description |
|--------|------|------|--------|-------|-------------|
| 0 | 4 | u32 | big | src\_ip | Source IPv4 address |
| 4 | 4 | u32 | big | dst\_ip | Destination IPv4 address |
| 8 | 2 | u16 | big | src\_port | Source port |
| 10 | 2 | u16 | big | dst\_port | Destination port |
| 12 | 1 | u8 | — | proto | IP protocol (6=TCP, 17=UDP) |
| 13 | 3 | — | — | \_pad | Alignment padding |

### TcpFlagCounts (36 bytes)

Per-direction packet counts for each TCP flag observed.

| Offset | Size | Type | Endian | Field |
|--------|------|------|--------|-------|
| 0 | 4 | u32 | little | syn |
| 4 | 4 | u32 | little | ack |
| 8 | 4 | u32 | little | fin |
| 12 | 4 | u32 | little | rst |
| 16 | 4 | u32 | little | psh |
| 20 | 4 | u32 | little | urg |
| 24 | 4 | u32 | little | ece |
| 28 | 4 | u32 | little | cwr |
| 32 | 4 | u32 | little | ns |

### ConntrackEntry (144 bytes)

| Offset | Size | Type | Endian | Field | Description |
|--------|------|------|--------|-------|-------------|
| 0 | 1 | u8 | — | is\_direction\_unknown | 1 if direction cannot be determined |
| 1 | 1 | u8 | — | traffic\_direction | 0=unknown, 1=egress, 2=ingress |
| 2 | 2 | — | — | \_pad1 | Padding |
| 4 | 4 | u32 | little | seq\_num | Last TCP sequence number |
| 8 | 4 | u32 | little | ack\_num | Last TCP ACK number |
| 12 | 4 | u32 | little | tsval | TCP timestamp value |
| 16 | 4 | u32 | little | tsecr | TCP timestamp echo reply |
| 20 | 36 | TcpFlagCounts | — | flags\_seen\_tx | Flags in transmit direction |
| 56 | 36 | TcpFlagCounts | — | flags\_seen\_rx | Flags in receive direction |
| 92 | 4 | — | — | \_pad2 | Padding (u64 alignment) |
| 96 | 8 | u64 | little | bytes\_tx | Total bytes transmitted |
| 104 | 8 | u64 | little | bytes\_rx | Total bytes received |
| 112 | 8 | u64 | little | packets\_tx | Total packets transmitted |
| 120 | 8 | u64 | little | packets\_rx | Total packets received |
| 128 | 8 | u64 | little | eviction\_time\_ns | Eviction timestamp (nanoseconds) |
| 136 | 4 | u32 | little | is\_closing | 1 if connection teardown in progress |
| 140 | 4 | — | — | \_pad3 | Padding |

**ConntrackRecord** = ConntrackKey (16) + ConntrackEntry (144) = **160 bytes**

### DropRecord (24 bytes)

Aggregated packet drop counters per drop reason category.

| Offset | Size | Type | Endian | Field | Description |
|--------|------|------|--------|-------|-------------|
| 0 | 2 | u16 | little | drop\_type | Drop reason category |
| 2 | 2 | — | — | \_pad1 | Padding |
| 4 | 4 | s32 | little | return\_val | Kernel return value (signed) |
| 8 | 8 | u64 | little | count | Number of dropped packets |
| 16 | 8 | u64 | little | bytes | Total dropped bytes |

**Drop type values:**

| Value | Name |
|-------|------|
| 1 | IPTABLES\_RULE\_DROP |
| 2 | IPTABLES\_NAT\_DROP |
| 3 | TCP\_CONNECT\_BASIC |
| 4 | TCP\_ACCEPT\_BASIC |
| 5 | TCP\_CLOSE\_BASIC |
| 6 | CONNTRACK\_DROP |
| 7 | UNKNOWN\_DROP |

### DnsEvent (24 bytes)

DNS query or response captured via BPF socket filter.

| Offset | Size | Type | Endian | Field | Description |
|--------|------|------|--------|-------|-------------|
| 0 | 4 | u32 | big | src\_ip | Source IPv4 |
| 4 | 4 | u32 | big | dst\_ip | Destination IPv4 |
| 8 | 2 | u16 | big | src\_port | Source port |
| 10 | 2 | u16 | big | dst\_port | Destination port |
| 12 | 2 | u16 | big | query\_id | DNS transaction ID |
| 14 | 2 | u16 | big | query\_type | DNS RR type |
| 16 | 2 | u16 | little | answer\_count | Answer RR count (0 for queries) |
| 18 | 1 | u8 | — | response\_code | DNS RCODE |
| 19 | 1 | u8 | — | is\_response | 0=query, 1=response |
| 20 | 4 | u32 | little | timestamp\_ns | Event timestamp (low 32 bits) |

**DNS query types:** 1=A, 2=NS, 5=CNAME, 15=MX, 16=TXT, 28=AAAA, 33=SRV, 255=ANY

**DNS response codes:** 0=NOERROR, 1=FORMERR, 2=SERVFAIL, 3=NXDOMAIN, 4=NOTIMP, 5=REFUSED

### RetransmitEvent (20 bytes)

TCP retransmission event from kernel tracepoint.

| Offset | Size | Type | Endian | Field | Description |
|--------|------|------|--------|-------|-------------|
| 0 | 4 | u32 | little | tcp\_state | TCP state at retransmit time |
| 4 | 2 | u16 | big | src\_port | Source port |
| 6 | 2 | u16 | big | dst\_port | Destination port |
| 8 | 4 | u32 | big | src\_ip | Source IPv4 |
| 12 | 4 | u32 | big | dst\_ip | Destination IPv4 |
| 16 | 1 | u8 | — | tcp\_flags | TCP flags bitmask |
| 17 | 1 | u8 | — | af | Address family (2=AF\_INET) |
| 18 | 2 | — | — | \_pad | Padding |

**TCP state values:** 1=ESTABLISHED, 2=SYN\_SENT, 3=SYN\_RECV, 4=FIN\_WAIT1, 5=FIN\_WAIT2, 6=TIME\_WAIT, 7=CLOSE, 8=CLOSE\_WAIT, 9=LAST\_ACK, 10=LISTEN, 11=CLOSING

**TCP flags bitmask:** bit0=FIN(0x01), bit1=SYN(0x02), bit2=RST(0x04), bit3=PSH(0x08), bit4=ACK(0x10), bit5=URG(0x20)

---

## Output Format

Write `/app/report.json` with this schema:

```json
{
  "connections": [
    {
      "src_ip": "<dotted decimal>",
      "dst_ip": "<dotted decimal>",
      "src_port": "<int>",
      "dst_port": "<int>",
      "proto": "TCP|UDP",
      "state": "ESTABLISHED|SYN_SENT|SYN_RECV|TIME_WAIT|FIN_WAIT|CLOSE_WAIT|RESET|ACTIVE",
      "direction": "egress|ingress|unknown",
      "is_direction_unknown": "<bool>",
      "bytes_tx": "<int>",
      "bytes_rx": "<int>",
      "packets_tx": "<int>",
      "packets_rx": "<int>",
      "retransmit_count": "<int>",
      "flags_summary": {
        "tx": {"syn": 0, "ack": 0, "fin": 0, "rst": 0, "psh": 0, "urg": 0, "ece": 0, "cwr": 0, "ns": 0},
        "rx": {"syn": 0, "ack": 0, "fin": 0, "rst": 0, "psh": 0, "urg": 0, "ece": 0, "cwr": 0, "ns": 0}
      },
      "is_closing": "<bool>",
      "eviction_time_ns": "<int>"
    }
  ],
  "drops": [
    {
      "drop_type": "<int>",
      "drop_type_name": "IPTABLES_RULE_DROP|...",
      "return_val": "<int>",
      "count": "<int>",
      "bytes": "<int>"
    }
  ],
  "anomalies": [
    {
      "type": "half_open|rst_storm|retransmit_heavy|dns_no_response|asymmetric_flow|fin_not_acked",
      "connection": "<src_ip>:<src_port>-><dst_ip>:<dst_port>",
      "detail": "<human-readable description>"
    }
  ],
  "dns_correlations": [
    {
      "query_id": "<int>",
      "query_name": "<string: queried domain name>",
      "query_type": "A|AAAA|CNAME|...",
      "src_ip": "<query source IP>",
      "dst_ip": "<query destination IP>",
      "src_port": "<query source port>",
      "has_response": "<bool>",
      "response_code": "NOERROR|NXDOMAIN|...|null",
      "answer_count": "<int>",
      "latency_ns": "<int: response_ts - query_ts, only if has_response>"
    }
  ],
  "pcap_analysis": {
    "total_packets": "<int: total packets in capture file>",
    "capture_duration_secs": "<int: seconds between first and last packet>"
  },
  "summary": {
    "total_connections": "<int>",
    "tcp_connections": "<int>",
    "udp_connections": "<int>",
    "total_anomalies": "<int>",
    "anomaly_types": ["<list of distinct anomaly type strings>"],
    "total_bytes_tx": "<int: sum across all connections>",
    "total_bytes_rx": "<int: sum across all connections>",
    "total_packets_tx": "<int>",
    "total_packets_rx": "<int>",
    "total_drop_count": "<int: sum of drop record counts>",
    "total_drop_bytes": "<int: sum of drop record bytes>",
    "total_retransmits": "<int: total retransmit events in file>",
    "dns_queries": "<int: count of DNS events with is_response=0>",
    "dns_responses": "<int: count of DNS events with is_response=1>",
    "connections_with_anomalies": "<int: unique connections that have at least one anomaly>"
  }
}
```

**Value conventions:**
- IP addresses: dotted decimal (`"10.0.1.10"`)
- Protocol: uppercase (`"TCP"`, `"UDP"`)
- Direction: lowercase (`"egress"`, `"ingress"`, `"unknown"`)
- State: uppercase (`"ESTABLISHED"`, `"SYN_SENT"`, etc.)
- Anomaly types: lowercase with underscores; thresholds for applicable types in `/app/anomaly_config.yaml`
- Connection keys: `"<src_ip>:<src_port>-><dst_ip>:<dst_port>"`
- Drop type names: uppercase with underscores (see drop type table)
- DNS query type names: standard (`"A"`, `"AAAA"`, `"CNAME"`, `"MX"`, `"NS"`, `"TXT"`, `"SRV"`, `"ANY"`)
- DNS response codes: standard (`"NOERROR"`, `"FORMERR"`, `"SERVFAIL"`, `"NXDOMAIN"`, `"NOTIMP"`, `"REFUSED"`)
