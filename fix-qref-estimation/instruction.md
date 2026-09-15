A quantum eigenvalue transformation algorithm processes an N-dimensional quantum system using K polynomial terms. It consists of three sequential stages, each with specific resource costs:

**State Preparation** — operates on the system register (size N). Uses a local parameter n = ceil(log2(N)). Costs: T_gates = 4·n + 4·(N − 1), rotations = 2·n.

**Block Encoding** — operates on the system register (size N) and an ancilla register (size ceil(log2(K))). Decomposes internally into three sequential sub-operations:
- Prepare: operates on the ancilla. T_gates = 4·(k − 1), rotations = k, where k = ceil(log2(K)).
- Select: operates on both ancilla (as control) and system. Two competing implementation strategies exist:
  - Strategy A: T_gates = 2·K·n, rotations = K (n = ceil(log2(N)))
  - Strategy B: T_gates = 4·n² + K, rotations = n
- Unprepare: same interface and costs as Prepare.

**Signal Processing** — operates on system and ancilla. T_gates = 2·K·n, rotations = K + 1.

Data flows sequentially: the system register passes through all three stages in order. The ancilla register enters at block encoding and flows from block encoding into signal processing.

Using `bartiq` (pre-installed), construct compilable resource estimation models implementing both strategy variants. Compile and numerically evaluate both for these nine parameter pairs: (N, K) ∈ {(8, 5), (8, 8), (8, 15), (32, 10), (32, 12), (32, 20), (64, 13), (64, 14), (64, 25)}.

For each system size N ∈ {8, 32, 64}, determine the smallest integer K ≥ 2 at which strategy B first becomes strictly more T-gate-efficient than strategy A.

Write to `/app/`:
- `variant_a.json` — the strategy A resource estimation model
- `variant_b.json` — the strategy B resource estimation model
- `results.json` containing:
  - `"variant_a"`: maps `"{N}_{K}"` → `{"t_gates": <int>, "rotations": <int>}` for all 9 pairs
  - `"variant_b"`: same structure
  - `"better_variant"`: maps `"{N}_{K}"` → `"A"` or `"B"` (whichever yields fewer total T-gates)
  - `"crossover_k"`: maps `"{N}"` → the smallest K where B beats A