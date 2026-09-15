`/app/hazard.sv` is the 5-stage pipeline hazard unit from the CORE-V Wally RISC-V processor -- a purely combinational module (13 binary inputs, 5 stall outputs, 4 flush outputs). `/app/trace.csv` has 200 cycles of input stimulus. `/app/schema.json` defines the required output format.

Produce `/app/results.json` conforming to the schema. The environment provides Verilator and Yosys; both must be used.

## RTL Simulation (Verilator)

Compile `hazard.sv` with Verilator and write a C++ testbench to drive the trace through actual RTL simulation and exhaustively enumerate all 2^13 input combinations. Do not substitute a hand-written behavioral model for trace statistics. From the simulation data, derive:

- Trace statistics: `per_stage_stall_counts`, `per_stage_flush_counts`, `longest_full_stall_streak`, `cycles_with_stall_flush_conflict`
- Trace optimization: `critical_input` (single input whose forcing-to-0 maximally reduces total stall-cycles across all stages and cycles), `minimum_stall_elimination_set` (minimum-cardinality sorted subset eliminating all pipeline stalls when forced to 0)
- Output analysis: `unique_output_count` (distinct 9-element output vectors across all 8192 inputs), `functional_equivalences` (sorted pairs of outputs with identical truth tables over all inputs)

## Logic Synthesis (Yosys)

Synthesize `hazard.sv` to AND/OR/NOT basis gates using Yosys. From the gate-level netlist JSON, extract:

- `total_cells` and `cells_by_type` (gate counts after technology mapping)
- `output_fan_in`: for each of the 9 outputs, the sorted list of primary input port names structurally reachable through the synthesized netlist (backward cone-of-influence traversal through the gate-level connectivity graph)

## Property Verification

| Key | Property |
|-----|----------|
| `P1_stall_monotonicity` | StallF >= StallD >= StallE >= StallM >= StallW |
| `P2_no_simultaneous_stall_flush` | No stage (D,E,M,W) has both Stall and Flush active |
| `P3_trap_guarantees_flush` | TrapM=1 implies FlushD=1 AND FlushE=1 AND FlushM=1 |
| `P4_division_protection` | (DivBusyE=1 AND BPWrongE=1) implies FlushE=0 |
| `P5_wfi_stall_guarantee` | (wfiM=1 AND IntPendingM=0) implies StallM=1 |
| `P6_stallf_equals_stalld` | StallF = StallD for all inputs |

For each, determine whether it holds universally over all 8192 input combinations. For failing properties, provide a minimal-weight counterexample (input assignment with fewest bits set to 1; all 13 input values as 0/1 integers).