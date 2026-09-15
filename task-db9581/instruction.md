A fleet of embedded IoT devices is exhibiting premature eMMC degradation. A raw FTL metadata dump from one affected unit has been extracted to `/app/flash_dump.bin`. An incomplete vendor datasheet fragment covering portions of the binary layout is at `/app/flash_spec.md`.

The datasheet has significant gaps: the journal entry integrity mechanism, operation type encoding, and process attribution table format are undocumented. You must reverse-engineer these undocumented sections from the raw binary to complete your analysis.

Investigate the dump and produce the following diagnostic artifacts in `/app/results/`:

### `/app/results/summary.json`

Device health assessment. Object with these exact keys:

- `corrupt_entries` (int): journal entries that fail integrity verification
- `valid_write_entries` (int): entries passing integrity that represent write operations
- `total_host_writes_bytes` (int): total host-initiated write volume in bytes
- `total_nand_erase_bytes` (int): total NAND-level erase volume in bytes across the device
- `write_amplification_factor` (float): WAF, rounded to 6 decimal places
- `elapsed_days` (int): device age in days since manufacture, truncated
- `remaining_lifetime_days` (int): estimated remaining days at current daily erase rate vs. TBW endurance rating, truncated
- `max_erase_count` (int)
- `min_erase_count` (int)
- `mean_erase_count` (float): rounded to 2 decimal places

### `/app/results/process_writes.json`

Per-process write attribution. Array of `{"pid": <int>, "name": <str>, "bytes_written": <int>}` for each process that performed writes. Sorted by `bytes_written` descending, then `pid` ascending for ties.

### `/app/results/hot_blocks.json`

Top 20 physical blocks by erase count. Array of `{"physical_block": <int>, "erase_count": <int>}`, sorted by erase count descending, then block number ascending for ties.

### `/app/results/optimized_mapping.json`

Wear-leveling remapping that minimizes the worst-case projected wear across the device. Define `write_heat[l]` as the total page count from valid writes targeting logical block `l`. The wear cost for logical block `l` under mapping `m` is `erase_count[m[l]] + write_heat[l]`.

Object with:
- `mapping`: array of length `total_blocks` where `mapping[l] = physical_block`, a valid permutation of `[0, total_blocks)`
- `projected_max_total` (int): minimized maximum wear cost under your mapping
- `current_max_total` (int): maximum wear cost under the existing FTL mapping from the dump