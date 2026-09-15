A firmware project targeting the Hubris RTOS (Oxide Computer Company) fails to build. The TOML configuration is at `/app/config/` — `app.toml` defines tasks (priorities, memory budgets, peripheral assignments, interrupt routing, IPC dependencies) and `chip.toml` describes the STM32H753ZI (ARM Cortex-M7) MCU's memory regions and peripheral register map.

Reference materials at `/app/reference/`:
- `build_log.txt` — failing build output
- `allocator.rs` — Rust source of the build system's MPU memory allocator (power-of-2 sizing, natural alignment, priority-ordered placement)
- `tasks_reference.adoc`, `ipc_reference.adoc`, `interrupts_reference.adoc` — Hubris RTOS documentation
- `chip_reference.db` — SQLite database with chip cross-reference data (pin multiplexing, DMA channel-to-peripheral mappings, interrupt vectors). Query with `sqlite3`.
- `build_manifest.json` — JSON build artifact with per-task actual compiled section sizes and RAM usage. Process with `jq`.

Perform a complete audit of the broken configuration, then design and validate a corrected version. Produce all output in `/app/output/`:

1. `validation_errors.json` — Array of `{"error_type": "<category>", "description": "<text>", "affected_tasks": ["<name>", ...]}`

2. `memory_layout.json` — Original config's MPU-aligned layout: `{"flash": {"<name>": {"address": <int>, "size": <int>}, ...}, "ram": {...}, "flash_overflow": <bool>, "ram_overflow": <bool>}`

3. `task_graph.json` — Original config's IPC dependency graph: `{"edges": [["<from>", "<to>"], ...], "cycles": [["<t1>", ..., "<t1>"], ...], "priority_inversions": [{"high_priority_task": "<name>", "low_priority_task": "<name>"}, ...]}`

4. `fixed_app.toml` — Corrected version of `app.toml` that resolves all validation errors while preserving every original task. Use `chip_reference.db` to determine valid peripheral reassignments and DMA controller mappings. Use `build_manifest.json` to determine appropriate memory budget reductions where allocations vastly exceed actual usage.

5. `task_graph.dot` and `task_graph.svg` — Graphviz DOT-format dependency graph of the corrected configuration, rendered to SVG with `dot`.

6. `optimization_report.json` — `{"original_ram_used": <int>, "fixed_ram_used": <int>, "ram_capacity": <int>, "original_overflow": <bool>, "fixed_overflow": <bool>, "fixes_applied": [{"error_type": "<type>", "description": "<what changed>", "justification": "<why>"}, ...]}`

The memory layout must faithfully reproduce the allocator's behavior as implemented in the Rust source. Only include IPC edges between tasks that exist in the configuration. All addresses must be integers.