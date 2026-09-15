The Intel 8088 CPU emulator at `/app/cpu8088.py` contains multiple conformance failures when compared against real 8088 hardware. Binary execution traces captured from a physical 8088 CPU are at `/app/traces.bin`, with format documentation at `/app/trace_format.md`.

Produce:

1. `/app/conformance_report.json` — a structured evaluation of the emulator's fidelity to the hardware traces. The report must contain:
   - `summary`: object with `total_traces`, `passing`, and `failing` counts
   - `traces`: array with one entry per trace, each containing `name`, `decoded_instruction` (disassembled mnemonic), `category` (instruction class), `status` (`"pass"` or `"fail"`), and `discrepancies` for failures
   - `failure_analysis`: object keyed by failure category, each with `root_cause` (detailed explanation of the underlying bug, minimum 10 words) and `affected_traces` (list of trace names), covering at least 4 distinct categories

2. A corrected `/app/cpu8088.py` that passes every hardware trace.