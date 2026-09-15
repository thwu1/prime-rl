# Packet Container and Signature Format Specification

## Binary Packet Container (`packets.bin`)

### File Header (16 bytes)

| Offset | Size | Type       | Description                     |
|--------|------|------------|---------------------------------|
| 0      | 4    | bytes      | Magic: `TCPF` (ASCII)           |
| 4      | 4    | uint32_le  | Version (must be 1)             |
| 8      | 4    | uint32_le  | Packet count                    |
| 12     | 4    | uint32_le  | Reserved (0)                    |

### Per-Packet Record (variable length)

| Offset | Size   | Type       | Description                          |
|--------|--------|------------|--------------------------------------|
| 0      | 8      | float64_le | Timestamp (Unix epoch, microsecond)  |
| 8      | 4      | uint32_le  | Frame length in bytes                |
| 12     | N      | bytes      | Raw Ethernet frame                   |

Packets are stored sequentially with no padding between records.

---

## Ethernet Frame Layout

Standard Ethernet II frame:

| Offset | Size | Description                              |
|--------|------|------------------------------------------|
| 0      | 6    | Destination MAC address                  |
| 6      | 6    | Source MAC address                       |
| 12     | 2    | EtherType (big-endian, 0x0800 = IPv4)    |
| 14     | ...  | Payload (IPv4 packet)                    |

---

## IPv4 Header Layout

| Offset | Size | Description                                          |
|--------|------|------------------------------------------------------|
| 0      | 1    | Version (high nibble) + IHL (low nibble, in 32-bit words) |
| 1      | 1    | TOS/DSCP+ECN (ECN = lowest 2 bits)                   |
| 2      | 2    | Total Length (big-endian)                             |
| 4      | 2    | Identification (big-endian)                          |
| 6      | 2    | Flags+Fragment Offset (big-endian; DF = bit 14 = 0x4000) |
| 8      | 1    | TTL                                                  |
| 9      | 1    | Protocol (6 = TCP)                                   |
| 10     | 2    | Header Checksum                                      |
| 12     | 4    | Source IP address                                    |
| 16     | 4    | Destination IP address                               |
| 20     | ...  | IP Options (if IHL > 5; length = (IHL-5)*4 bytes)    |

---

## TCP Header Layout

| Offset | Size | Description                                            |
|--------|------|--------------------------------------------------------|
| 0      | 2    | Source Port (big-endian)                               |
| 2      | 2    | Destination Port (big-endian)                          |
| 4      | 4    | Sequence Number (big-endian)                           |
| 8      | 4    | Acknowledgment Number (big-endian)                     |
| 12     | 2    | Data Offset + Reserved + Flags (big-endian)            |
|        |      |   Bits 15-12: Data Offset (header length in 32-bit words) |
|        |      |   Bits 11-9: Reserved                                 |
|        |      |   Bit 8: NS                                           |
|        |      |   Bit 7: CWR                                          |
|        |      |   Bit 6: ECE                                          |
|        |      |   Bit 5: URG                                          |
|        |      |   Bit 4: ACK                                          |
|        |      |   Bit 3: PSH                                          |
|        |      |   Bit 2: RST                                          |
|        |      |   Bit 1: SYN                                          |
|        |      |   Bit 0: FIN                                          |
| 14     | 2    | Window Size (big-endian)                               |
| 16     | 2    | Checksum                                               |
| 18     | 2    | Urgent Pointer (big-endian)                            |
| 20     | ...  | TCP Options (if Data Offset > 5)                       |

---

## TCP Option Kinds

| Kind | Name          | Length  | Structure                                |
|------|---------------|---------|------------------------------------------|
| 0    | EOL           | 1       | Single byte, terminates option parsing   |
| 1    | NOP           | 1       | Single byte, no-op padding               |
| 2    | MSS           | 4       | kind(1) + len(1) + MSS value(2, big-endian) |
| 3    | Window Scale  | 3       | kind(1) + len(1) + shift count(1)        |
| 4    | SACK Permitted| 2       | kind(1) + len(1)                         |
| 5    | SACK          | varies  | kind(1) + len(1) + SACK blocks           |
| 8    | Timestamps    | 10      | kind(1) + len(1) + TSval(4) + TSecr(4)  |
| other| Unknown       | varies  | kind(1) + len(1) + data(len-2)           |

For options with kind >= 2, the second byte is the total option length (including kind and length bytes). For kind 0 (EOL) and kind 1 (NOP), there is no length byte.

---

## p0f Signature Format

Each signature is a colon-separated string with 8 fields:

```
ver:ittl:olen:mss:wsize,wscale:olayout:quirks:pclass
```

### Field Definitions

**ver** — IP version: `4` or `6`

**ittl** — Initial (guessed) TTL. Normalize observed TTL to the smallest value in `{32, 64, 128, 255}` that is >= the observed TTL. For example, observed 63 → initial 64; observed 120 → initial 128.

**olen** — IP options length in bytes: `(IHL - 5) * 4`. Usually 0.

**mss** — TCP MSS option value. `-1` if MSS option not present. In the database, `*` is a wildcard matching any MSS.

**wsize,wscale** — Window size and window scale factor, comma-separated. The raw window size value from the TCP header and the window scale shift count from the WScale option (-1 if not present). In the database:
- `wsize` can be an exact value, `mss*N` (window = MSS × N), `mtu*N` (window = (MSS+40) × N), or `*` (wildcard)
- `wscale` is exact or `*` (wildcard)

**olayout** — Ordered list of TCP option kinds, comma-separated, using these names:
- `nop` (kind 1), `mss` (kind 2), `ws` (kind 3), `sok` (kind 4), `sack` (kind 5), `ts` (kind 8)
- `eol+N` — EOL (kind 0) followed by N bytes of padding until the end of the options area
- `?K` — unknown option of kind K

**quirks** — Comma-separated set of quirk flags (empty string if no quirks). Canonical order:

| Flag    | Condition                                              |
|---------|--------------------------------------------------------|
| `df`    | DF (Don't Fragment) flag is set in IP header           |
| `id+`   | IP ID field is non-zero when DF is set                 |
| `id-`   | IP ID field is zero when DF is NOT set                 |
| `ecn`   | ECN bits (TOS & 0x03) are non-zero                    |
| `0+`    | Reserved bits in TCP header are non-zero               |
| `flow`  | IPv6 flow label is non-zero (IPv6 only)                |
| `seq-`  | TCP sequence number is zero                            |
| `ack+`  | TCP ACK number is non-zero but ACK flag is NOT set     |
| `ack-`  | TCP ACK number is zero but ACK flag IS set             |
| `uptr+` | TCP urgent pointer is non-zero but URG flag is NOT set |
| `urgf+` | TCP URG flag is set                                    |
| `pushf+`| TCP PSH flag is set                                    |
| `ts1-`  | TCP timestamp value (TSval) is zero                    |
| `ts2+`  | TCP timestamp echo reply (TSecr) is non-zero in SYN   |
| `opt+`  | Trailing data past parsed options                      |
| `exws`  | Excessive window scale (> 14)                          |

**pclass** — Payload class: `0` (no TCP payload after headers), `+` (payload present), `*` (any, database only)

---

## Signature Database Format (`signatures.db`)

Text file with the following syntax:
- Lines starting with `;` are comments
- Lines starting with `[` denote sections (e.g., `[tcp:request]`)
- `label = <OS label>` sets the label for the next signature
- `sig = <signature string>` defines the signature pattern

Entries are evaluated in order; first match wins.

### Matching Rules

For each field, the packet's extracted value must satisfy the database pattern:
1. **Exact match**: field values must be equal
2. **Wildcard** (`*`): matches any value
3. **Window formula** (`mss*N`): packet window == packet_mss × N
4. **Window formula** (`mtu*N`): packet window == (packet_mss + 40) × N
5. **Quirks**: the packet's quirk set must exactly equal the database quirk set (set equality, order does not matter)
6. **pclass**: `*` matches any; `0` and `+` require exact match
