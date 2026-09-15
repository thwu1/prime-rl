A C parser for the XPROTO binary protocol is at `/app/target/target.c`. The protocol specification is at `/app/docs/protocol_spec.md` and a Python reference validator at `/app/validator/validate.py`. AFL++ is pre-installed.

Build a production-ready, structure-aware fuzzing pipeline for this parser. The completed pipeline must include:

- **`/app/mutator.py`** — A Python custom mutator implementing AFL++'s complete custom mutator interface. It must generate structurally valid XPROTO messages that pass the reference validator, correctly maintain the protocol's integrity mechanisms (including CRC and optional compression), and support structure-aware trimming of TLV payloads. Different RNG seeds must produce varied output.

- **`/app/build/target_afl`** — The target compiled with AFL++ source-level instrumentation. Must be executable and contain instrumentation markers.

- **`/app/build/target_cmplog`** — A separate CmpLog-instrumented build of the same target, distinct from `target_afl`.

- **`/app/corpus/`** — A seed corpus of at least 5 valid XPROTO messages covering at least 2 protocol versions and at least 3 distinct TLV type IDs.