A TypeScript force-directed graph simulation engine at `/app/` has several broken or incomplete components. Fix all bugs and implement all stubs so the simulation produces correct deterministic output.

**Files**:
- `/app/src/simulation.ts` — Simulation loop with alpha cooling and velocity-Verlet integration
- `/app/src/quadtree.ts` — Quadtree spatial index with add, cover, visit, visitAfter
- `/app/src/forces/manyBody.ts` — N-body repulsive force using Barnes-Hut quadtree approximation
- `/app/src/forces/collide.ts` — Collision detection with quadtree broad-phase
- `/app/src/forces/link.ts` — Spring link constraints with degree-biased strength
- `/app/src/forces/center.ts`, `x.ts`, `y.ts` — Positioning forces (working)
- `/app/src/lcg.ts`, `jiggle.ts`, `constant.ts` — Utilities (working)
- `/app/src/run.ts` — Scenario runner outputting JSON

**Setup**: Run `cd /app && npm install` to install dependencies.

**Commands**: `npx ts-node src/run.ts <scenario>` runs a named scenario. `npx ts-node src/run.ts all` runs all scenarios. `bash /tests/test.sh` runs verification.

**Behavior**: The engine uses a deterministic LCG (a=1664525, c=1013904223, m=2^32, seed=1) for reproducibility. Nodes initialize in phyllotaxis positions. Each tick applies all forces, then integrates velocities with decay and updates positions, respecting fixed-position constraints (fx/fy). The quadtree supports spatial partitioning with extent doubling via cover(), pre-order visit(), and post-order visitAfter(). Forces use the quadtree for efficient spatial queries during N-body and collision computations.

**Success**: `bash /tests/test.sh` writes reward 1.0 to `/logs/verifier/reward.txt`.
