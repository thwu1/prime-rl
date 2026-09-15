A multi-file SystemVerilog SoC design is located at `/opt/soc_design/`:

```
/opt/soc_design/
├── pkg/soc_pkg.sv              # Package with shared types/parameters
├── include/soc_config.svh      # Preprocessor macro definitions
├── rtl/
│   ├── alu.sv                  # Combinational ALU using package-defined op codes
│   ├── regfile.sv              # Parameterized register file with reset
│   ├── cpu_core.sv             # CPU core instantiating ALU and regfile
│   ├── gpio_bank.sv            # GPIO controller with generate-based per-pin debounce
│   └── soc_top.sv              # Top-level SoC module
└── ip_lib/
    ├── fifo/sync_fifo.v        # Synchronous FIFO (Verilog-2005)
    └── serial/uart_tx.v        # UART transmitter with FSM (Verilog-2005)
```

Install the `slang` SystemVerilog compiler and configure it to compile this design. The Verilog-2005 IP modules (`.v` files in `ip_lib/` subdirectories) must be resolved through slang's library directory and file extension mechanism. The design uses `include` directives for preprocessor macros and imports a shared package.

Produce the following deliverables:

1. **`/app/compile.f`** — A slang command file that compiles the full design cleanly (exit code 0), correctly handling compilation order, include paths, library directories, library file extensions, and top-level module specification.

2. **`/app/analyze.py`** — A Python script that invokes slang with `--ast-json` to produce `/app/ast.json`, then programmatically traverses the elaborated AST to extract design structural metrics and writes `/app/analysis.json`.

3. **`/app/analysis.json`** — A JSON object with these keys and correct values:
   - `"top_module"`: name of the top-level module
   - `"total_instances"`: total count of module instantiations in the elaborated hierarchy
   - `"hierarchy"`: maps each parent module name to a sorted list of child module definition names it instantiates
   - `"module_ports"`: maps each module definition name to `{"inputs": N, "outputs": N}` port counts
   - `"instance_params"`: maps each instance name (e.g. `"u_cpu"`) to an object of its overridden parameter names and elaborated integer values
   - `"generate_blocks"`: maps modules containing generate-for constructs to a list of `{"name": "<block_label>", "count": N}` entries, where count reflects the elaborated iteration count after parameter resolution
   - `"fsm_states"`: maps modules containing FSM state-encoding localparams to an object of state name → integer value. Include only modules with three or more localparams forming a state encoding.
   - `"memory_arrays"`: maps modules containing memory array declarations to a list of `{"name": "<variable>", "depth": N, "width": N}` with elaborated dimensions after parameter resolution

All parameter values, generate iteration counts, array dimensions, and FSM state values must be derived from slang's elaborated AST output — not hardcoded. Expressions like `CLK_FREQ / BAUD_RATE` must appear as their computed integer result. Generate counts must reflect elaborated parameters, not source-level expressions.