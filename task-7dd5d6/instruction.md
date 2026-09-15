The [Uiua](https://uiua.org) programming language includes an experimental geometric algebra (GA) system for multivector arithmetic in Clifford algebras Cl(p,q,r). Implement a Python module at `/app/clifford.py` whose functions exactly reproduce Uiua's internal GA conventions and computations.

Uiua's GA conventions are **non-standard** in several important ways — the blade ordering, metric index assignment, and product sign rules all differ from typical mathematical references and GA libraries. You must match Uiua's specific behavior, not textbook formulas.

## Available Resources

- `/app/reference/ga.rs` — Rust source of Uiua's GA parser module, defining the foundational data structures and conventions
- `/app/reference/test_ga.ua` — Uiua's own GA test suite written in Uiua's glyph-based syntax
- `/app/reference/ga_tool` — Compiled reference binary exercising the GA primitives from `ga.rs`; run it without arguments for usage help
- The Rust compiler (`rustc`) and Cargo are installed — you may compile and experiment with portions of the reference code directly

## Required Functions

Implement in `/app/clifford.py`. Multivectors are Python lists of `2^dims` floats, indexed by blade position in Uiua's ordering.

| Function | Signature | Returns |
|----------|-----------|---------|
| `mask_tables` | `(dims)` | `(mask_table, inv_mask_table)` — Uiua's blade-index ↔ bitmask mapping tables |
| `metric` | `(index, p, q, r)` | `int` — metric signature value (+1, −1, or 0) for a basis vector |
| `geo_product` | `(mv_a, mv_b, dims, p, q, r)` | `list[float]` — geometric (Clifford) product |
| `outer_product` | `(mv_a, mv_b, dims, p, q, r)` | `list[float]` — exterior (wedge) product |
| `inner_product` | `(mv_a, mv_b, dims, p, q, r)` | `list[float]` — left contraction |
| `grade_project` | `(mv, dims, grade)` | `list[float]` — grade extraction |
| `reverse_mv` | `(mv, dims)` | `list[float]` — grade reversal |
| `sandwich` | `(R, x, dims, p, q, r)` | `list[float]` — versor sandwich product |
| `exp_bivector` | `(B, dims, p, q, r)` | `list[float]` — exponential of a pure bivector |