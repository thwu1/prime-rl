# PCST Optimization Project

Write an ASP-Core-2 encoding for the combinatorial graph optimization problem
described in `docs/problem.md`.

## Project Structure

- `docs/problem.md` — Problem definition and mathematical formulation
- `docs/notes.md` — ASP encoding tips and common pitfalls
- `instances/` — Test instances and expected-results manifest
- `legacy/steiner.lp` — Reference encoding for the standard Steiner Tree problem
- `checker/verify.py` — Validation script (requires clingo Python package)
- `encoding.lp` — Your encoding goes here

## Validation

```
pip3 install clingo
python3 checker/verify.py
```
