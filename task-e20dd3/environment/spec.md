# p0f-Compatible TCP SYN Signature Specification

## Signature Format

```
ver:ittl:olen:mss:wsize,scale:olayout:quirks:pclass
```

Eight colon-separated fields. The `wsize,scale` field contains an internal comma.

### Field Definitions

#### `ver` — IP Version
Integer: `4` for IPv4, `6` for IPv6.

#### `ittl` — Initial TTL (guessed)
The original TTL set by the sender, before routers decremented it. Guess the initial TTL from the observed TTL by selecting the smallest value from `{32, 64, 128, 255}` that is greater than or equal to the observed TTL. Examples: observed 64 → 64, observed 55 → 64, observed 120 → 128.

#### `olen` — IP Options Length
Total length in bytes of IPv4 header options: `(IHL * 4) - 20`. Usually `0`.

#### `mss` — Maximum Segment Size
Value of the MSS TCP option if present, as a decimal integer. Use `*` if absent.

#### `wsize,scale` — Window Size and Scale Factor
Two sub-fields separated by a comma:

**wsize**: The TCP window size, expressed as one of:
- `mss*N` — if MSS option is present, MSS > 0, and `window_size % MSS == 0`, then `N = window_size / MSS`
- `mtu*N` — else if MSS option is present, MSS > 0, and `window_size % (MSS + 40) == 0`, then `N = window_size / (MSS + 40)`
- Literal decimal integer — otherwise (or if MSS option is absent)

**scale**: Value of the Window Scale TCP option if present, as a decimal integer. Use `*` if absent.

#### `olayout` — TCP Option Layout
Comma-separated list of TCP options in the order they appear in the TCP header. Option names:

| TCP Option Kind | Name in olayout |
|---|---|
| 0 (EOL) | `eol+N` where N = number of padding bytes remaining after EOL until the end of the options area |
| 1 (NOP) | `nop` |
| 2 (MSS) | `mss` |
| 3 (Window Scale) | `ws` |
| 4 (SACK Permitted) | `sok` |
| 5 (SACK) | `sack` |
| 8 (Timestamps) | `ts` |
| Other | `?K` where K is the option kind number |

When EOL is encountered, count remaining bytes until the TCP data offset boundary as padding. If no EOL is encountered (options fill exactly to the data offset boundary), do not append any `eol` entry.

#### `quirks` — Quirk Flags
Comma-separated list of detected anomalies/features, in the canonical order listed below. Empty string if no quirks detected.

| Quirk | Condition |
|---|---|
| `df` | DF (Don't Fragment) flag is set in IP header |
| `id+` | IP Identification field is non-zero AND DF flag is set |
| `id-` | IP Identification field is zero AND DF flag is NOT set |
| `ecn` | ECN bits are set in IP ToS/Traffic Class field (`tos & 0x03 != 0`) |
| `0+` | Reserved "must be zero" bit is set in IP flags (bit 15 of flags+fragment field) |
| `seq-` | TCP sequence number is zero |
| `ack+` | TCP ACK number is non-zero AND ACK flag is NOT set |
| `ack-` | TCP ACK number is zero AND ACK flag IS set |
| `uptr+` | TCP urgent pointer is non-zero AND URG flag is NOT set |
| `urgf+` | TCP URG flag is set |
| `pushf+` | TCP PSH (PUSH) flag is set |
| `ts1-` | TCP Timestamp value (TSval) is zero (only when Timestamp option present) |
| `ts2+` | TCP Timestamp echo reply (TSecr) is non-zero on a SYN packet (only when Timestamp option present) |
| `exws` | Window Scale factor > 14 |

Output quirks in the canonical order shown above. Only include quirks whose conditions are met.

#### `pclass` — Payload Class
- `0` — no TCP payload (data after TCP header + options is empty)
- `+` — TCP payload is present

## Fingerprint Database Format

The database is a text file with these line types:

- **Comment**: Lines starting with `;` — ignore entirely.
- **Blank lines**: Ignore.
- **Section header**: `[section_name]` — only `[tcp:request]` is relevant.
- **Label**: `label = <value>` — sets the OS label for the next signature line.
- **Signature**: `sig = <signature_string>` — defines a signature to match.

Each `label`/`sig` pair forms one database entry. The label applies to the immediately following `sig` line.

### Matching Rules

Compare the observed signature against each database entry in order. Return the first match.

For each field of the observed vs. database signature:
- If the database field is `*`, it matches any observed value.
- For `wsize` and `scale` sub-fields: each is compared independently; either can be `*`.
- For `olayout`: must match exactly (no wildcards).
- For `quirks`: the observed and database quirk sets must be identical (exact set match — split by comma and compare as sets).
- All other fields: exact string match.
