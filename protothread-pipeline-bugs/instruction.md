The directory `/app/` contains a cooperative data processing pipeline built on the Contiki-NG protothread library (stackless coroutines for C). The source at `/app/pipeline.c` contains multiple defects preventing correct operation. The protothread library headers at `/app/include/` (`pt.h`, `lc-switch.h`, `lc.h`, `pt-sem.h`) are correct and must not be modified.

Fix `/app/pipeline.c` so that:

- `gcc -O2 -o /app/pipeline /app/pipeline.c -I/app/include` succeeds
- `/app/pipeline` completes within 10 seconds
- `/app/output.dat` contains correct results

**Pipeline topology** (fan-out / fan-in):

```
Reader -> Transformer -> Splitter -> EvenProc --\
                                  -> OddProc  --+--> Merger -> Writer
```

The pipeline reads 32-bit little-endian signed integers from `/app/input.dat` and processes them through seven cooperating protothread stages connected by bounded FIFO channels, driven by a round-robin cooperative scheduler.

**Stage transformations:**

- **Transformer**: `val = ((val & 0xFF) * 7 + 13) & 0xFF`
- **Splitter**: routes values with `(val & 1) == 0` to EvenProc, `(val & 1) == 1` to OddProc
- **EvenProc**: `val = val * 2`
- **OddProc**: `val = val + 50`
- **Merger**: forwards all values from both EvenProc and OddProc output channels to Writer without deadlocking. Must handle the two upstream channels closing independently and at different times. A sequential drain (fully reading one channel before the other) will deadlock due to bounded-channel backpressure in the fan-out topology.
- **Writer**: writes each value as `"%d\n"` to `/app/output.dat`

**Channel semantics:** bounded FIFO, capacity 4. Send blocks the protothread when full. Receive blocks when empty. A closed channel delivers any remaining buffered items, then signals end-of-stream to the receiver.

**Scheduler contract:** the cooperative scheduler drives all seven stages in round-robin until every stage has completed. No stage runs after it has finished.

**Correctness criteria:** for each input value `v`, the output must contain exactly one result: `((v & 0xFF) * 7 + 13) & 0xFF` processed through the appropriate path (even values multiplied by 2, odd values incremented by 50). Output ordering is unconstrained; the sorted multiset of output values must match expected. Empty input produces an empty output file. Negative input values must be handled correctly. No deadlock or data loss at any input size.
