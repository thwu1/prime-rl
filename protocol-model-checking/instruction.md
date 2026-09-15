PVS formal specifications in `/app/specs/` describe a dual-channel flight guidance system's "pilot flying" protocol — a safety-critical protocol ensuring exactly one channel controls the aircraft at any time. Two protocol variants are specified:

- **Synchronous** (`synchronous.pvs`): Two sides connected by two buses; all components share a single clock. A single boolean input (Transfer Switch) controls the system. The `Pilot_Flying_System_Requirements` and `Pilot_Flying_System_Requirements2` theories formally define safety requirements R1–R5, `Reachable_States_Valid`, and `Switching_Transient` as theorems over reachable states.

- **Asynchronous** (`asynchronous.pvs`): Same two-side/two-bus architecture, but each of the four components (two sides, two buses) has an independent clock, and inter-component communication uses `Message` records instead of booleans. No requirements theory is provided in this file — the same R1–R5 safety requirements from the synchronous specification apply, appropriately lifted to the asynchronous system's state representation and output types.

Your task: determine whether each safety requirement holds universally over all reachable states of both protocol variants, using the concrete (LLR) theories rather than the abstract (HLR) axioms. Report the total number of distinct reachable system states for each variant.

Write results to `/app/results.json`:

```json
{
  "synchronous": {
    "reachable_state_count": <int>,
    "requirements": {
      "R1": <bool>, "R2": <bool>, "R3a": <bool>, "R3b": <bool>,
      "R4": <bool>, "R5a": <bool>, "R5b": <bool>,
      "Reachable_States_Valid": <bool>, "Switching_Transient": <bool>
    }
  },
  "asynchronous": {
    "reachable_state_count": <int>,
    "requirements": {
      "R1": <bool>, "R2": <bool>, "R3a": <bool>, "R3b": <bool>,
      "R4": <bool>, "R5a": <bool>, "R5b": <bool>
    }
  }
}
```

Each requirement value is `true` if the property holds universally over all reachable states and all applicable input combinations; `false` otherwise.