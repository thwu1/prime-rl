The directory `/app` contains a closed-loop control simulation. A Q16.16 fixed-point PID controller drives a discrete second-order plant. All supporting code is complete and correct:

- `/app/fixpoint.h` — Q16.16 saturating arithmetic primitives
- `/app/plant.h`, `/app/plant.c` — discrete plant model
- `/app/sim_harness.c` — simulation loop writing trace output
- `/app/sim_params.h` — controller and plant parameters
- `/app/pid_controller.h` — controller data structure and function signatures
- `/app/Makefile` — build system

The file `/app/pid_controller.c` contains a stub: `pid_init` stores parameters into the struct, but `pid_step` returns zero. Implement `pid_step` so the closed-loop simulation produces the correct output trace. The controller's data structure and interface are defined in `/app/pid_controller.h`. Do not modify any other source files. All internal arithmetic must use the Q16.16 operations from `fixpoint.h` — floating-point computation will not produce bit-exact results.

Build and run:

```
cd /app && make clean && make && ./sim_harness
```

This writes `/app/trace_output.csv` with one line per simulation step (5000 total):

```
step_index,ref_hex,y_hex,u_hex,error_hex
```

Each hex field is the raw Q16.16 `int32_t` as 8-digit zero-padded lowercase hex (two's complement for negatives). The `error` column is `reference - plant_output` as computed by the harness after each plant step.

All `y`, `u`, and `error` values across all 5000 steps must match the verifier's golden reference within +/-2 Q16.16 LSBs.
