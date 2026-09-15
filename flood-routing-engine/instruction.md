The project at `/app/` is a flood routing simulator that propagates an inflow hydrograph through a sequential network of channel reaches and reservoirs, producing a routed outflow hydrograph. The project uses CMake.

The simulator has multiple defects:

- The CMake build configuration contains errors that prevent successful compilation. Fix the build so it produces the binary `/app/build/flood_router`.
- The source files in `/app/src/` contain several interacting computational defects. The program compiles (once the build is fixed) and runs without crashing, but produces physically incorrect output.

Diagnose and fix all defects so the simulator builds and produces correct results.

**Build and run:**
```
cd /app && cmake -B build && cmake --build build
./build/flood_router data/scenario.txt output.csv
```

**Requirements for `/app/output.csv`:**
- CSV header: `time_s,flow_m3s`. One data row per computation timestep.
- No NaN, Inf, or negative flow values.
- Mass conservation: total outflow volume within 2% of total inflow volume for channel-only routing.
- Peak attenuation: output peak flow must be less than 90% of input peak.
- Peak delay: output peak must occur at a later timestep than input peak.
- Smoothness: no successive timestep flow change exceeds 20% of peak flow.
- Accuracy: routed hydrographs match independently computed reference values within 5% NRMSE (normalized by peak flow).

Source: `/app/src/`. Scenario data: `/app/data/scenario.txt`.
