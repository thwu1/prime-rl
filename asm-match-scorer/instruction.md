In decompilation and recompilation workflows, two compilations of the same source function may produce object code that is functionally identical despite superficial differences in the generated assembly. A useful comparison tool must distinguish genuine structural divergence from cosmetic differences.

Create `/app/scorer.py` — a command-line tool that compares two x86-64 ELF relocatable object files (`.o`), each containing one function, and produces a similarity score reflecting the degree of structural divergence between them.

**Invocation:**

    python3 /app/scorer.py <target.o> <candidate.o>

**Output:** a single line of JSON to stdout:

    {"score": <int>, "num_target": <int>, "num_candidate": <int>, "register_mapping": {}}

- `score`: Non-negative integer. 0 when the functions are structurally equivalent; increases with divergence.
- `num_target` / `num_candidate`: Number of instructions in each disassembled function.
- `register_mapping`: The register correspondence discovered between the two functions, as `{"%src": "%dst", ...}`. Only include non-identity entries.

**Required behavioral properties:**
- Comparing a file to itself always yields score 0.
- Two functions that perform identical computation but happen to use different registers must score 0.
- `score(A, B) == score(B, A)` for all valid inputs.
- A pair with strictly more structural differences must score higher than a pair with fewer.

Reference materials and scaffolding code are available in `/app/`. Sample `.o` files are in `/app/objects/` for experimentation. Your implementation will be evaluated against fresh object files assembled at test time, not present in the initial environment.