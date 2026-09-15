# Fingerprint Signature Specification

## Signature String Format

Each TCP SYN fingerprint is an 8-field colon-separated string:

```
ver:ittl:olen:mss:wsize,wscale:olayout:quirks:pclass
```

### Field Definitions

**ver** -- IP version: `4` or `6`

**ittl** -- Initial (guessed) TTL. Normalize observed TTL to the smallest value in `{32, 64, 128, 255}` that is >= the observed TTL. For example, observed 63 -> initial 64; observed 120 -> initial 128.

**olen** -- IP options length in bytes: `(IHL - 5) * 4`. Usually 0.

**mss** -- TCP MSS option value. Use `*` if MSS option is not present.

**wsize,wscale** -- Window size and window scale factor, comma-separated. The raw window size value from the TCP header and the window scale shift count from the WScale option. Use `-1` for wscale if WScale option not present.

**olayout** -- Ordered list of TCP option kinds seen in the packet, comma-separated, using these names:

| Name   | TCP Option Kind |
|--------|-----------------|
| `nop`  | 1               |
| `mss`  | 2               |
| `ws`   | 3               |
| `sok`  | 4               |
| `sack` | 5               |
| `ts`   | 8               |
| `eol+N`| 0 (N = bytes of padding remaining after EOL to end of options area) |
| `?K`   | unknown option of kind K |

**quirks** -- Comma-separated set of quirk flags (empty string if no quirks). Must appear in canonical order:

| Flag     | Condition                                              |
|----------|--------------------------------------------------------|
| `df`     | DF (Don't Fragment) flag is set in IP header           |
| `id+`    | IP ID field is non-zero when DF is set                 |
| `id-`    | IP ID field is zero when DF is NOT set                 |
| `ecn`    | ECN bits (TOS & 0x03) are non-zero                    |
| `0+`     | Reserved bits in TCP header are non-zero               |
| `flow`   | IPv6 flow label is non-zero (IPv6 only)                |
| `seq-`   | TCP sequence number is zero                            |
| `ack+`   | TCP ACK number is non-zero but ACK flag is NOT set     |
| `ack-`   | TCP ACK number is zero but ACK flag IS set             |
| `uptr+`  | TCP urgent pointer is non-zero but URG flag is NOT set |
| `urgf+`  | TCP URG flag is set                                    |
| `pushf+` | TCP PSH flag is set                                    |
| `ts1-`   | TCP timestamp value (TSval) is zero                    |
| `ts2+`   | TCP timestamp echo reply (TSecr) is non-zero in SYN   |
| `opt+`   | Trailing data past parsed options                      |
| `exws`   | Excessive window scale (> 14)                          |

**pclass** -- Payload class: `0` (no TCP payload after headers), `+` (payload present), `*` (any, database only)

---

## Signature Database Schema

The SQLite database (`fingerprints.db`) contains two tables:

```sql
CREATE TABLE sections (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE signatures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    section_id INTEGER NOT NULL REFERENCES sections(id),
    label TEXT NOT NULL,
    sig TEXT NOT NULL,
    priority INTEGER NOT NULL
);
```

- `sections` -- groups of signatures (e.g., `tcp:request` for TCP SYN fingerprints)
- `signatures` -- each row is a `label` (OS identification string) and a `sig` (signature pattern string)
- Signatures are evaluated in ascending `priority` order; first match wins

---

## Matching Rules

For each colon-separated field, the packet's extracted value must satisfy the database pattern:

1. **Exact match**: field values must be equal
2. **Wildcard** (`*`): matches any value (used in mss, wsize, wscale, pclass fields)
3. **Window formula** (`mss*N`): packet window size == MSS x N
4. **Window formula** (`mtu*N`): packet window size == (MSS + 40) x N
5. **Quirks**: the packet's quirk set must exactly equal the database quirk set (set equality, order does not matter)
6. **pclass**: `*` matches any; `0` and `+` require exact match
