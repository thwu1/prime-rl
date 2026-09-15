A Tenstorrent Wormhole chip has a 10x12 toroidal NoC grid with 12 DRAM banks (columns 0 and 5), Tensix worker (T) tiles, and two physically independent NoC fabrics. Saturating DRAM bandwidth requires placing 12 reader cores — one per bank — on available T-tiles such that data return paths have minimal congestion. Manufacturing defects cause entire T-tile rows to be "harvested" (disabled); harvested tiles still route packets but cannot host readers.

The environment provides:

- `/app/wormhole_grid.json` — chip topology: DRAM bank positions, T-tile grid coordinates, NoC routing rules, bandwidth parameters
- `/app/noc_sim.c` — C-based NoC link congestion simulator (known to produce incorrect results — contains bugs that must be identified and fixed before use)
- `/app/Makefile` — builds `noc_sim` binary from `noc_sim.c`
- `/app/tlb_spec.json` — NoC Route Configuration Table (RCT) register encoding specification for RISC-V firmware generation

Create `/app/noc_pipeline.py` that accepts:

```
python3 /app/noc_pipeline.py --config /app/wormhole_grid.json --harvested-rows 1,7 --output /app/output.json
```

Use `--harvested-rows ""` when no rows are harvested.

The tool must produce optimal DRAM reader placements that minimize NoC congestion, validate them against a corrected and compiled C simulator, and generate cross-assembled RISC-V RV32I firmware that programs each reader's RCT entry. Firmware assembly files go in `/app/firmware/`, cross-assembled with `riscv64-linux-gnu-as` and verified with `riscv64-linux-gnu-objdump`.

Output `/app/output.json` must contain:

- **`placements`**: 12 objects with `bank_id`, `reader_x`, `reader_y`, `noc_id` (0 or 1), `vc` (0 or 1). Each reader on a distinct valid T-tile not in a harvested row.
- **`routes`**: 12 objects with `bank_id` and `links` (data return path as `[[x1,y1],[x2,y2]]` per hop, following the selected NoC fabric's dimension-ordered routing rule with toroidal wrapping).
- **`congestion`**: `total_shared_links` (links used by >1 route per NoC), `max_link_load` (peak sharing on any single link), `total_excess_load` (sum of load-1 for overloaded links).
- **`estimated_bandwidth_pct`**: `sum(min(per_bank_bw, noc_link_bw / max_load_on_path)) / (12 * per_bank_bw) * 100`.
- **`simulator_validation`**: `compiled` (bool), `bugs_fixed` (list of fix descriptions), `sim_max_link_load` (int from simulator output), `validation_passed` (bool).
- **`firmware`**: 12 objects with `bank_id`, `rct_value_hex` (16-char zero-padded hex of 64-bit RCT value per spec), `asm_file` (path to .s file), `obj_verified` (bool — objdump confirms correct instructions).

Constraints:

- Readers sharing the same row and `noc_id` must use different virtual channels.
- With no harvesting or a single harvested row, achieve `max_link_load` = 1 (zero congestion).
- With up to 5 harvested rows, `max_link_load` ≤ 2 and `estimated_bandwidth_pct` ≥ 90.