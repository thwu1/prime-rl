The file `/app/tablex.lua` exports a Lua module with table utilities and a lazy iterator library. It contains bugs across all subsystems. Fix every bug so the module conforms to the specification below.

**Sentinels:** `EMPTY_DICT` — unique marker distinguishing empty dicts from `{}`. `empty_dict()` returns new instances sharing the sentinel metatable.

**Table utilities:**
- `islist(t)` — true iff contiguous integer keys 1..n with no extras. Must use raw access; metatables must not influence the result.
- `tbl_count(t)`, `deep_equal(a, b)` — entry count and recursive equality.
- `deepcopy(val)` — deep-clone preserving shared metatables, self-referencing cycles, functions by reference, and `EMPTY_DICT` identity. Error containing `"Cannot deepcopy object of type thread"` on thread values at any depth.
- `tbl_keys(t)`, `tbl_values(t)`, `tbl_map(f,t)`, `tbl_filter(f,t)`, `tbl_contains(t, val, opts)` — standard helpers; `{predicate=true}` opts treats `val` as predicate.
- `tbl_deep_extend(behavior, ...)` — recursive merge of 2+ tables. `"keep"`: first wins; `"force"`: last wins; `function(k, prev, new)`: returns winner. Dict+dict recurses; lists/scalars resolve. EMPTY_DICT merged with `{}` preserves first argument's type. Errors on nil behavior, insufficient args, non-table args.
- `tbl_deep_diff(a, b)` — returns `{added={}, removed={}, changed={}}`. Keys in `b` absent from `a` are `added`; vice versa `removed`. Differing scalars: `{old=va, new=vb}`. Nested table pairs recurse; only non-empty sub-diffs appear in `changed`.

**Iterator — `tablex.iter(src)`:**
Sources: list-table, dict-table, callable. Array-backed supports `rev()`, `pop()`, `rpeek()`, `slice()`, `rskip()`, `rfind()`, `nth(-n)`, `flatten()`. Function-backed rejects these with `"requires an array%-like table"`.

Transforms (`filter`, `map`, `enumerate`) are lazy and compose. All consuming operations must honor the full transform pipeline.

Methods: `filter(f)`, `map(f)`, `totable()`, `join(sep)`, `next()`, `rev()`, `skip(n_or_pred)`, `rskip(n)`, `take(n_or_pred)`, `nth(n)`, `slice(from,to)`, `peek()`, `pop()`, `rpeek()`, `find(v_or_f)`, `rfind(v_or_f)`, `any(f)`, `all(f)`, `last()`, `enumerate()`, `fold(init,f)`, `flatten(depth)`, `unique(key_fn)`, `chain(other)`, `zip(other)`, `scan(init,f)`, `group_by(key_fn)`, `partition(pred)`.

Contracts: `enumerate()` is 1-based. `peek()` is non-consuming and preserves multi-value returns. `fold(init,f)` reduces to a single value using the accumulator function. `chain(other)` concatenates; `zip(other)` stops when either exhausts. `scan(init,f)` yields the initial value then each running accumulator. `flatten(depth)` flattens nested tables to the given depth. `group_by(key_fn)` consumes the iterator, applies pending transforms, and returns `{key = {values...}}`. `partition(pred)` returns two tables: matching elements first, non-matching second.

The iterator must be callable via `for`-`in` loops.

All code: `/app/tablex.lua`.
