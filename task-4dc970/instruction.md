The quantization codec at `/app/codec.py` has multiple interacting defects across its subsystems. It implements a blockwise NormalFloat4 quantization pipeline but currently produces incorrect quantization levels, fails on certain input distributions, crashes when reading the reference checkpoint, and lacks C extension integration.

The environment provides:
- `/app/codec.py` — the defective codec (all public functions exist but several contain bugs)
- `/app/nibble_pack.c` — C source for an optimized nibble packing library (correct, not yet compiled or integrated)
- `/app/reference.nf4` — a correctly serialized binary checkpoint
- `/app/weights.bin` — 1024 little-endian float32 benchmark weights
- `/app/validate.py` — diagnostic script that checks each subsystem against reference data

Diagnose and fix every defect. The repaired codec must produce numerically correct results consistent with established NF4 quantization reference values and fully interoperate with the reference checkpoint format.