# Passive TCP Fingerprint Specification

## Overview

This document defines the format for passive TCP/IP stack fingerprinting using the p0f methodology. Fingerprints are extracted from TCP SYN and SYN+ACK packets by analyzing IP and TCP header fields, TCP options, and behavioral quirks.

## Packet Classification

- **SYN packets**: TCP SYN flag set, ACK flag clear. Match against `tcp:request` database section.
- **SYN+ACK packets**: Both TCP SYN and ACK flags set. Match against `tcp:response` database section.
- All other packets (ACK-only, RST, data, FIN, etc.) must be ignored.

## Capture File Formats

Captures may be in either standard libpcap (`.pcap`) or pcapng (`.pcapng`) format.

### Standard libpcap (`.pcap`)

- **Global header** (24 bytes): magic number (little-endian `0xa1b2c3d4` or big-endian `0xd4c3b2a1`), version major/minor, timezone offset, sigfigs, snaplen, link-layer type
- **Per-packet record**: 16-byte header (timestamp seconds, timestamp microseconds, captured length, original length) followed by raw packet data
- **Link type 1** = Ethernet

### pcapng (`.pcapng`)

Next-generation block-based capture format. Contains Section Header Blocks (type `0x0A0D0D0A`), Interface Description Blocks (type `0x00000001`), and Enhanced Packet Blocks (type `0x00000006`). Each block starts and ends with a 32-bit total length field. Timestamps in Enhanced Packet Blocks are 64-bit values split across two 32-bit fields (high, low) in the resolution specified by the interface's `if_tsresol` option (default: microseconds). Tools such as `tshark`, `editcap`, and `capinfos` can read and convert pcapng files.

### Ethernet Frame

- 14-byte header: 6 bytes destination MAC, 6 bytes source MAC, 2 bytes EtherType
- **EtherType `0x0800`** = IPv4

## Signature String Format

Each fingerprint is an 8-field colon-separated string:

```
ver:ittl:olen:mss:wsize,wscale:olayout:quirks:pclass
```

### Field Definitions

**ver** — IP version: `4` (IPv4) or `6` (IPv6).

**ittl** — Initial (guessed) TTL. Normalize the observed TTL to the smallest value in `{32, 64, 128, 255}` that is greater than or equal to the observed TTL. Examples: observed 63 → 64; observed 120 → 128; observed 64 → 64; observed 255 → 255.

**olen** — IP options length in bytes: `(IHL - 5) * 4`. Usually 0 for standard IPv4 packets. Non-zero when IP header options are present.

**mss** — TCP Maximum Segment Size option value extracted from the packet. In database signatures, `*` is a wildcard matching any MSS value.

**wsize,wscale** — Window size and window scale factor, comma-separated. `wsize` is the raw window size value from the TCP header. `wscale` is the shift count from the Window Scale option; use `-1` if the Window Scale option is not present in the packet.

**olayout** — Ordered list of TCP option kinds as encountered in the packet, comma-separated, using these symbolic names:

| Name    | TCP Option Kind | Notes |
|---------|----------------|-------|
| `nop`   | 1              | No Operation (1 byte) |
| `mss`   | 2              | Maximum Segment Size (4 bytes) |
| `ws`    | 3              | Window Scale (3 bytes) |
| `sok`   | 4              | SACK Permitted (2 bytes) |
| `sack`  | 5              | Selective ACK (variable length) |
| `ts`    | 8              | Timestamps (10 bytes) |
| `eol+N` | 0              | End of Options List. N = number of NUL padding bytes remaining between the EOL byte and the end of the TCP options area. |
| `?K`    | K              | Unknown option of kind K |

**quirks** — Comma-separated set of quirk flags detected in the packet (empty string if no quirks detected). When formatting, quirks must appear in canonical order:

| Flag     | Condition                                              |
|----------|--------------------------------------------------------|
| `df`     | DF (Don't Fragment) flag is set in IPv4 header         |
| `id+`    | IP Identification field is non-zero AND DF flag IS set |
| `id-`    | IP Identification field is zero AND DF flag is NOT set |
| `ecn`    | ECN bits in IP TOS field are non-zero (TOS & 0x03 != 0) |
| `0+`     | Reserved bits in TCP header are non-zero               |
| `flow`   | IPv6 flow label is non-zero (IPv6 only)                |
| `seq-`   | TCP sequence number is zero                            |
| `ack+`   | TCP ACK number is non-zero but ACK flag is NOT set     |
| `ack-`   | TCP ACK number is zero but ACK flag IS set             |
| `uptr+`  | TCP urgent pointer is non-zero but URG flag is NOT set |
| `urgf+`  | TCP URG flag is set                                    |
| `pushf+` | TCP PSH flag is set                                    |
| `ts1-`   | TCP Timestamp Value (TSval) is zero                    |
| `ts2+`   | TCP Timestamp Echo Reply (TSecr) is non-zero           |
| `opt+`   | Trailing unparsed data past end of options              |
| `exws`   | Excessive window scale factor (> 14)                   |

Canonical quirk order for formatting: `df, id+, id-, ecn, 0+, flow, seq-, ack+, ack-, uptr+, urgf+, pushf+, ts1-, ts2+, opt+, exws`

**pclass** — Payload class: `0` (no TCP payload after headers), `+` (payload present), `*` (any — used as wildcard in database signatures only).

---

## Signature Database Schema

The SQLite database (`signatures.db`) uses a normalized multi-table schema:

```sql
CREATE TABLE sections (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE os_families (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE os_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    family_id INTEGER NOT NULL REFERENCES os_families(id),
    version TEXT NOT NULL,
    label TEXT NOT NULL UNIQUE
);

CREATE TABLE sig_patterns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    section_id INTEGER NOT NULL REFERENCES sections(id),
    version_id INTEGER NOT NULL REFERENCES os_versions(id),
    ip_ver TEXT NOT NULL,
    ittl TEXT NOT NULL,
    olen TEXT NOT NULL,
    mss_pattern TEXT NOT NULL,
    wsize_pattern TEXT NOT NULL,
    wscale_pattern TEXT NOT NULL,
    olayout TEXT NOT NULL,
    quirks TEXT NOT NULL DEFAULT '',
    pclass TEXT NOT NULL DEFAULT '0',
    priority INTEGER NOT NULL
);
```

### Table Relationships

- `sections` — signature groups: `tcp:request` (id=1) for SYN, `tcp:response` (id=2) for SYN+ACK
- `os_families` — OS family names (e.g., "Linux", "Windows")
- `os_versions` — specific OS versions, each linked to a family; the `label` column contains the match result string (e.g., "Linux:6.x")
- `sig_patterns` — decomposed signature patterns; each row links to a section and an OS version

### Reconstructing the Signature String

The full p0f-format signature string is reconstructed by concatenating fields from `sig_patterns`:

```
ip_ver:ittl:olen:mss_pattern:wsize_pattern,wscale_pattern:olayout:quirks:pclass
```

### Matching Process

1. Determine the packet type (SYN or SYN+ACK)
2. Select the appropriate section (`tcp:request` or `tcp:response`)
3. Retrieve `sig_patterns` joined with `os_versions` (for the label), ordered by `priority` ascending
4. **First match wins** — return that entry's `os_versions.label`
5. If no signature matches, the result is `unknown`

---

## Matching Rules

For each field of a database signature pattern, the extracted packet value must satisfy:

1. **Exact match**: literal string comparison (e.g., `ip_ver`, `ittl`, `olen` fields)
2. **Wildcard** (`*`): matches any value. Used in `mss_pattern`, `wsize_pattern`, `wscale_pattern`, and `pclass` fields.
3. **MSS formula** (`mss*N`): the packet's window size must equal the packet's MSS value multiplied by N. If MSS is not present in the packet, the formula cannot match.
4. **MTU formula** (`mtu*N`): the packet's window size must equal `(MSS + 40) * N`. If MSS is not present, the formula cannot match.
5. **Quirks**: the packet's detected quirk set must **exactly equal** the database signature's quirk set (set equality; order does not matter during comparison).
6. **pclass**: `*` matches any payload class; `0` and `+` require exact match.

---

## IPv4 Header Fields (relevant to fingerprinting)

- Byte 0: version (upper 4 bits) + IHL (lower 4 bits). Header length = IHL * 4 bytes.
- Byte 1: TOS/DSCP+ECN. ECN bits are the lowest 2 bits (TOS & 0x03).
- Bytes 2-3: Total Length
- Bytes 4-5: Identification
- Bytes 6-7: Flags + Fragment Offset. DF flag = bit 14 (value 0x4000 in the 16-bit flags+frag field).
- Byte 8: TTL
- Byte 9: Protocol (6 = TCP)
- Bytes 12-15: Source IP
- Bytes 16-19: Destination IP
- Bytes 20+: IP Options (if IHL > 5)

## TCP Header Fields (relevant to fingerprinting)

- Bytes 0-1: Source Port
- Bytes 2-3: Destination Port
- Bytes 4-7: Sequence Number
- Bytes 8-11: Acknowledgment Number
- Bytes 12-13: Data Offset (upper 4 bits of byte 12, multiply by 4 for header length) + Reserved + Flags
- Bytes 14-15: Window Size
- Bytes 18-19: Urgent Pointer
- Bytes 20+: TCP Options (if Data Offset > 5)

TCP Flags (in the lower 9 bits of bytes 12-13):
- Bit 1 (0x02): SYN
- Bit 3 (0x08): PSH
- Bit 4 (0x10): ACK
- Bit 5 (0x20): URG
- Bit 2 (0x04): RST
