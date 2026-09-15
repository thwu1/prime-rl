# Wormhole NoC Architecture Specification

## Grid Topology

The Tenstorrent Wormhole AI accelerator chip contains a 10-column x 12-row grid of tiles:

- **Columns x=0 and x=9**: DRAM bank tiles (left and right edges)
- **Columns x=1 through x=8**: Worker tiles (Tensix compute cores)
- **Rows y=0 through y=11**: All rows span the grid

### DRAM Bank Positions

Twelve DRAM banks are distributed across the left and right edges:

| Bank ID | Position | Side  |
|---------|----------|-------|
| 0       | (0, 0)   | Left  |
| 1       | (0, 2)   | Left  |
| 2       | (0, 4)   | Left  |
| 3       | (0, 6)   | Left  |
| 4       | (0, 8)   | Left  |
| 5       | (0, 10)  | Left  |
| 6       | (9, 1)   | Right |
| 7       | (9, 3)   | Right |
| 8       | (9, 5)   | Right |
| 9       | (9, 7)   | Right |
| 10      | (9, 9)   | Right |
| 11      | (9, 11)  | Right |

Left banks occupy even rows; right banks occupy odd rows.

### Harvesting

Manufacturing defects cause certain rows to be disabled ("harvested"). No reader core can be placed on a harvested row. The NoC mesh, however, remains fully operational on harvested rows — only the compute tile is disabled, not the interconnect links passing through it.

## Network-on-Chip (NoC) Routing

Two physically independent NoCs carry data across the grid:

- **NoC #0**: Dimension-ordered routing — X-first **Eastbound** (increasing x), then Y **Southbound** (increasing y)
- **NoC #1**: Dimension-ordered routing — X-first **Westbound** (decreasing x), then Y **Northbound** (decreasing y)

Each NoC provides 32 GB/s per directional link at 1 GHz (32 bytes/cycle).

### Return Path Model

When a DRAM bank sends data back to its assigned reader core, the data follows a dimension-ordered route:

#### Left-side banks (x=0) → use NoC #0

From bank at `(0, bank_y)` to reader at `(reader_x, reader_y)`:

1. **East segment**: traverse links `(x, bank_y) → (x+1, bank_y)` for each `x` in `[0, reader_x)` (staying on `bank_y` row)
2. **South segment**: traverse links `(reader_x, y) → (reader_x, y+1)` for each `y` in `[bank_y, reader_y)` (staying on `reader_x` column)

**Constraint**: `reader_y >= bank_y` (the South direction only increases y; wraparound is prohibited)

#### Right-side banks (x=9) → use NoC #1

From bank at `(9, bank_y)` to reader at `(reader_x, reader_y)`:

1. **West segment**: traverse links `(x, bank_y) → (x-1, bank_y)` for each `x` in `(reader_x, 9]` descending (staying on `bank_y` row)
2. **North segment**: traverse links `(reader_x, y) → (reader_x, y-1)` for each `y` in `(reader_y, bank_y]` descending (staying on `reader_x` column)

**Constraint**: `reader_y <= bank_y` (the North direction only decreases y; wraparound is prohibited)

### Directional Links

A directional link is uniquely identified by: `(direction, from_x, from_y, to_x, to_y)` where `direction ∈ {E, W, N, S}`. Two links with different directions at the same grid position are physically separate and do not interfere.

### Congestion-Free Constraint

Two return paths **conflict** if they share any directional link on the same NoC. Since left-side banks exclusively use NoC #0 and right-side banks exclusively use NoC #1, conflicts can only occur between banks on the **same side** (left-left or right-right).

A placement is **congestion-free** if no two return paths share any directional link.

## Placement Rules

1. Each of the 12 DRAM banks must have exactly one assigned reader on a **worker tile** (`x ∈ [1, 8]`, `y ∈ [0, 11]`)
2. No reader may be placed on a **harvested row**
3. No two readers may occupy the **same tile**
4. The placement must be **congestion-free** (no shared return-path links)
5. No **wraparound** routing: left readers must have `y >= bank_y`; right readers must have `y <= bank_y`
6. **Minimize total hop count** across all 12 readers

### Ideal Placement

When no rows are harvested, each bank's reader sits one hop away:

- Left bank at `(0, y)` → reader at `(1, y)` — 1 hop East
- Right bank at `(9, y)` → reader at `(8, y)` — 1 hop West

When the ideal row is harvested, the reader must be **displaced**. Displacement may require moving to an adjacent row (increasing cost by 1 hop per row) or to a different column (if the adjacent row is occupied or would cause congestion).

### Hop Count

`hop_count = |reader_x - bank_x| + |reader_y - bank_y|`

## Link Utilization Analysis

For a given placement, the **utilization** of a directional link is the number of return paths that traverse it. In a congestion-free placement, every link has utilization exactly 1 (used by one path) or 0 (unused).

### Required Metrics

- **Total links used**: count of distinct directional links traversed by any return path (across both NoCs). For a congestion-free placement, this equals the total hop count.
- **Max link load**: maximum utilization across all links on either NoC (must be 1 for congestion-free placements)
- **NoC split**: count of distinct links used on NoC #0 vs NoC #1 independently

## Bandwidth Estimation Model

- Each DRAM bank provides **24 GB/s** of bandwidth
- **Theoretical maximum**: 12 × 24 = **288 GB/s**
- **Hop penalty**: each extra hop beyond the ideal 1-hop adds **0.5%** overhead (modeling increased NoC latency)
- **Extra hops per reader**: `max(0, hop_count - 1)`
- **Total extra hops**: sum of extra hops across all 12 readers
- **Utilization factor**: `1.0 - 0.005 × total_extra_hops`
- **Estimated bandwidth**: `288.0 × utilization_factor` (in GB/s)
