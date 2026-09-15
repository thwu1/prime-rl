# Crossbar Design Specification

## Parameterization Contract

All modules in this design must be fully parameterized. Hardcoded
constants that happen to match the default configuration are not
acceptable — they will produce incorrect behavior when parameters
are overridden.

### Address Decoding

The `addr_decoder` module extracts the slave-select bits from the
upper portion of the request address. The bit-range must be computed
from the module parameters:

- Select width: `SEL_W = $clog2(NUM_OUTPUTS)`
- Extraction range: `addr[ADDR_W-1 : ADDR_W-SEL_W]`

Using hardcoded bit indices (e.g. `[15:14]`) is a violation even if
it produces the correct result with default parameter values.

### Signal Naming

All struct field accesses must use the canonical names defined in
`xbar_pkg`:
- `xbar_req_t.addr` (not `.address`)
- `xbar_req_t.cmd`
- `xbar_resp_t.resp`

### Port Connections

Module instantiation port connections must reference the correct
declared signal name. SystemVerilog implicit net creation from
misspelled identifiers in port connections is a latent bug — the
compiler may silently create a dangling 1-bit net instead of
reporting an error.

## Module Hierarchy

- `top_xbar` (top level)
  - `addr_decoder` x N_MASTERS (address decode per master port)
  - `round_robin_arb` x N_SLAVES (arbitration per slave port)
  - `xbar_switch` (crossbar fabric)
    - `priority_enc` (library module, auto-discovered)

## Design Intent Notes

- `xbar_switch` has `clk` and `rst_n` ports reserved for future
  pipeline register insertion; they are intentionally unconnected
  in the current combinational implementation.
- `DATA_W` parameter in `xbar_switch` exists for documentation
  and external tool consumption; it is not used in RTL logic.
- `calc_sel_width` in `xbar_pkg` is a utility function available
  for use by downstream consumers; it is intentionally retained
  even if unused within this design.
