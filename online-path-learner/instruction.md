Build an interactive solver for routing queries on a 30x30 grid graph where edge weights are unknown. A judge program at `/app/judge` generates random grid instances from a seed and evaluates your solver's routing quality over 1000 sequential queries.

For each query, the judge sends a source-destination pair via stdin. Your solver must output a valid path (a string of U/D/L/R moves) to stdout, then read a noisy integer measurement of the path's actual cost from stdin. By accumulating these observations, your solver should progressively learn the graph's edge structure and route closer to optimally.

A partial protocol specification is at `/app/problem.txt`. Critical details are absent from the documentation: the scoring formula (how per-query optimality ratios are temporally weighted and scaled into the final integer score) and the noise model (the exact multiplicative distribution governing feedback perturbation). The stripped judge binary at `/app/judge` is the authoritative source for these parameters. Recovering the temporal weighting scheme from the binary is essential for designing an effective learning strategy, since it determines which queries carry the most weight in the final score.

## Files

- `/app/judge` -- Judge program (stripped ELF binary). Usage: `/app/judge <seed> /app/solver`
- `/app/problem.txt` -- Partial interaction protocol and constraints

## Deliverable

Create an executable solver at `/app/solver` that achieves an average score of at least 650,000,000 across test seeds 42, 137, and 256.