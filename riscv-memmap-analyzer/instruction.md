Build `/app/soc_analyzer.py` — a tool that parses RISC-V SoC debugger configuration files from the riscv_vhdl project and cross-validates them against VHDL hardware constants.

The configuration files at `/app/configs/` use the riscv_vhdl debugger's non-standard format: single-quoted strings, hex integer literals (`0x10000`), `true`/`false` boolean literals, `#include "file"` preprocessor directives for file composition, trailing commas, and `['AttrName', value]` or `['AttrName', value, 'doc comment']` attribute arrays. The entry point is `/app/configs/func_river_x1_gui.json`, which includes `common_riscv.json` and `common_soc.json`.

The VHDL hardware configuration at `/app/rtl/river_cfg.vhd` defines synthesizable River CPU constants using standard VHDL `constant NAME : TYPE := VALUE;` declarations.

The tool must support three subcommands:

**`python3 /app/soc_analyzer.py memmap <config_file>`** — Output the AXI bus memory map as a JSON array sorted by base address. Only include devices listed in the bus (`BusGenericClass`) `MapList`. Each entry: `name`, `base_address` (hex string), `end_address` (hex string), `length` (hex string), `class`, `bus`.

**`python3 /app/soc_analyzer.py resolve <config_file> <hex_address>`** — Determine which memory-mapped device handles the given address. Only devices in the bus `MapList` are reachable. Each device's address range is `[BaseAddress, BaseAddress+Length)`. When multiple mapped devices claim an address, the highest `Priority` attribute (default 0) wins. Output JSON: `address` (hex), `device` (string or null), `offset` (hex string or null), `read_only` (bool or null), `priority` (int or null). For addresses >= 2^`AddrWidth`, set `device` to null and include `"error": "address_out_of_range"`.

**`python3 /app/soc_analyzer.py crosscheck <config_file> <vhdl_file>`** — Cross-validate the functional simulation configuration against VHDL hardware constants. Output JSON with a `checks` array and `summary` object. Required cross-checks (use these exact `parameter` names):

- `vendor_id`: core0 `VendorID` vs `CFG_VENDOR_ID`
- `implementation_id`: core0 `ImplementationID` vs `CFG_IMPLEMENTATION_ID`
- `fpu_enabled`: whether `'D'` is in core0 `ListExtISA` vs `CFG_HW_FPU_ENABLE`
- `progbuf_total`: dmi0 `ProgbufTotal` vs `CFG_PROGBUF_REG_TOTAL`
- `data_reg_total`: dmi0 `DataregTotal` vs `CFG_DATA_REG_TOTAL`
- `stack_trace_size`: core0 `StackTraceSize` vs `2^CFG_LOG2_STACK_TRACE_ADDR`
- `reset_vector`: core0 `ResetVector` vs `CFG_NMI_RESET_VECTOR`

Each check: `parameter`, `json_value`, `vhdl_value`, `status` (`"match"` or `"mismatch"`). Summary: `total`, `matches`, `mismatches`.

All hex values in output must be `0x`-prefixed lowercase strings.