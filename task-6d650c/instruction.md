A sliding tile puzzle research project is at `/app/`. It contains benchmark data and an incomplete solver. Some data files may include configurations that are mathematically unsolvable.

Produce `/app/results.json` — a JSON array of objects, one per solvable 4×4 puzzle instance found across all data files under `/app/benchmarks/`:

- `tiles`: array of 16 integers (initial board, row-major, 0 = blank)
- `length`: integer optimal move count
- `moves`: space-separated U/D/L/R characters (direction the blank moves)

Goal state: `[0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15]`. All solutions must be provably optimal. Total solver time under 5 minutes. Exclude unsolvable instances.