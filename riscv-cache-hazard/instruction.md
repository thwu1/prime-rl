You are given SystemVerilog source files from the CORE-V Wally RISC-V processor in `/app/src/`. The file `cache.sv` implements a parameterized set-associative cache subsystem, and `hazard.sv` implements the 5-stage pipeline hazard resolution unit.

Produce `/app/results.json` with three sections:

**1. Cache Geometry** (`cache_geometry`): For each of the 6 data cache configurations in `/app/configs.json`, determine the address decomposition parameters as defined by the localparam declarations in `cache.sv`. The required output fields are listed in `/app/schema.json`.

**2. Cache Simulation** (`cache_simulation`): Simulate each cache configuration against the 50-access memory trace in `/app/trace.json`. Study the processor source to determine the replacement policy used by the cache subsystem, then implement a faithful simulator. Report hit/miss statistics and identify conflict misses — misses that are attributable to limited associativity rather than limited capacity.

**3. Hazard Analysis** (`hazard_analysis`): For each of the 8 scenarios in `/app/scenarios.json`, compute all stall and flush output signals for every cycle by faithfully implementing the combinational logic defined in `hazard.sv`. Pay careful attention to every signal gating, priority interaction, and conditional suppression in the source.

The expected output fields for each section are documented in `/app/schema.json`. All signal values must be integers (0 or 1). Miss rate must be a float rounded to 4 decimal places.