# IPv6 Conformance Analyzer Specification

## Overview

This specification defines an IPv6 packet conformance analyzer aligned with the NIST USGv6 Core
capability set and RFC 8200 (Internet Protocol, Version 6 Specification).

## Input

Hex-encoded IPv6 packets in `/app/packets/*.hex`. Each file contains exactly one packet
represented as hex bytes. Whitespace (spaces, newlines, tabs) separates bytes for readability
and must be stripped during parsing. Hex digits are case-insensitive.

## Required Output

Write analysis results to `/app/results.json` with this structure:

```json
{
  "packets": {
    "<filename_without_extension>": {
      "version": "<int: IP version from header>",
      "traffic_class": "<int: 8-bit traffic class>",
      "flow_label": "<int: 20-bit flow label>",
      "payload_length": "<int: Payload Length from IPv6 header>",
      "hop_limit": "<int: Hop Limit from IPv6 header>",
      "src_addr": "<string: source IPv6 address in RFC 5952 canonical form>",
      "dst_addr": "<string: destination IPv6 address in RFC 5952 canonical form>",
      "header_chain": "<list of int: sequence of Next Header values>",
      "violations": "<list of string: violation codes detected>",
      "is_fragment": "<bool: true if packet contains a Fragment header>",
      "fragment_offset": "<int or null: Fragment Offset in 8-octet units>",
      "fragment_m_flag": "<bool or null: More Fragments flag>",
      "fragment_id": "<string or null: Fragment Identification as hex '0x...'>"
    }
  },
  "fragment_sets": {
    "<fragment_id_hex>": {
      "fragments": "<list of string: packet names in this set>",
      "overlapping": "<bool: true if any fragments overlap>",
      "reassembled_payload_length": "<int or null: computed reassembled Payload Length>"
    }
  }
}
```

## IPv6 Header Format (40 bytes)

```
Bytes 0-3:   Version (4 bits) | Traffic Class (8 bits) | Flow Label (20 bits)
Bytes 4-5:   Payload Length (16-bit unsigned)
Byte  6:     Next Header (8 bits)
Byte  7:     Hop Limit (8 bits)
Bytes 8-23:  Source Address (128 bits)
Bytes 24-39: Destination Address (128 bits)
```

## Header Chain

The `header_chain` field records the sequence of Next Header values encountered while
walking the packet. It starts with the IPv6 header's Next Header value. If that value
identifies an extension header, parse the extension header to obtain its Next Header
value, append it, and continue. Terminate when a non-extension-header value is reached
(including value 59 for No Next Header).

Extension header Next Header values:
- 0: Hop-by-Hop Options
- 43: Routing
- 44: Fragment
- 51: Authentication Header (AH)
- 50: Encapsulating Security Payload (ESP)
- 60: Destination Options

## Extension Header Parsing

| Type | NH Value | Length Calculation |
|------|----------|-------------------|
| Hop-by-Hop Options | 0 | (Hdr Ext Len + 1) * 8 bytes |
| Destination Options | 60 | (Hdr Ext Len + 1) * 8 bytes |
| Routing | 43 | (Hdr Ext Len + 1) * 8 bytes |
| Fragment | 44 | Fixed 8 bytes |
| Authentication | 51 | (Hdr Ext Len + 2) * 4 bytes |

### Fragment Header Layout (8 bytes)

```
Byte  0:     Next Header
Byte  1:     Reserved
Bytes 2-3:   Fragment Offset (13 bits) | Res (2 bits) | M flag (1 bit)
Bytes 4-7:   Identification (32 bits)
```

Extract Fragment Offset: `(value >> 3) & 0x1FFF`
Extract M flag: `value & 0x01`

## Conformance Violations

Detect the following violations per RFC 8200:

| Code | RFC 8200 Section | Description |
|------|-----------------|-------------|
| `INVALID_VERSION` | 3 | Version field is not 6 |
| `HBH_NOT_FIRST` | 4.3 | Hop-by-Hop Options header is present but does not immediately follow the IPv6 header (i.e., it is not the first extension header at byte offset 40) |
| `DUPLICATE_HEADER` | 4.1 | An extension header other than Destination Options appears more than once in the chain. Destination Options may appear up to twice. |
| `FRAGMENT_LENGTH_NOT_ALIGNED` | 4.5 | Fragment data length (Payload Length minus offset of fragment data from start of payload) is not a multiple of 8 octets when M flag = 1 |
| `PAYLOAD_LENGTH_MISMATCH` | 3 | Payload Length field does not match actual number of bytes following the IPv6 header |
| `REASSEMBLY_EXCEEDS_MAX` | 4.5 | Fragment Offset * 8 + fragment data length exceeds 65535 |

### Fragment Data Length

The fragment data length is the number of bytes after the Fragment header within the payload:

```
fragment_data_length = Payload_Length - (Fragment_header_position_in_payload + 8)
```

Where `Fragment_header_position_in_payload` is the byte offset of the Fragment header
measured from the start of the payload (i.e., from byte 40 of the packet).

## Fragment Set Analysis

Group all fragment packets by (source address, destination address, fragment ID).
For each group with 2 or more fragments:

**Overlap detection**: A fragment covers byte range `[FO*8, FO*8 + fragment_data_length)`.
Two fragments overlap if their ranges intersect.

**Reassembled Payload Length**: For non-overlapping sets that contain both a first fragment
(Fragment Offset = 0) and a last fragment (M flag = 0), compute per RFC 8200 Section 4.5:

```
PL.orig = PL.first - FL.first - 8 + (8 * FO.last) + FL.last
```

Where:
- `PL.first` = Payload Length field of the first fragment packet
- `FL.first` = fragment data length of the first fragment
- `FO.last`  = Fragment Offset of the last fragment
- `FL.last`  = fragment data length of the last fragment

Set `reassembled_payload_length` to null if overlapping or if the set lacks a first or last fragment.

## IPv6 Address Formatting

Format addresses per RFC 5952:
- Suppress leading zeros in each 16-bit group
- Use `::` for the longest run of consecutive all-zero groups
- Use lowercase hex digits
- Example: `2001:db8:1::1` (not `2001:0DB8:0001:0000:0000:0000:0000:0001`)
