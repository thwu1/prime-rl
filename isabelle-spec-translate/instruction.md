Two Isabelle/HOL theory files (`.thy`) from the Archive of Formal Proofs are at `/app/theories/`: `AVL.thy` (an AVL tree formalization) and `Dijkstra.thy` (a Dijkstra's algorithm specification). These files use Isabelle's formal syntax to define datatypes, functions, lemmas, theorems, locales, and proofs.

Produce two Python modules:

## `/app/parser.py`

Class `IsabelleParser` with method `parse(filepath: str) -> dict` returning:

- `theory_name` (str): the theory identifier from the header
- `imports` (list[str]): imported theory names
- `datatypes` (list[dict]): each with `name` (str) and `constructors` (list[str])
- `functions` (list[dict]): each with `name` (str) and `kind` (str) — the exact Isabelle keyword that introduces the definition
- `lemmas` (list[dict]): named proof obligations only, each with `name` (str) and `kind` (str)
- `locales` (list[str]): locale names

The parser must correctly handle all syntactic constructs present in the provided theory files.

## `/app/avl.py`

An executable Python translation of `/app/theories/AVL.thy`. Read the formal specification carefully — the implementation must be structurally faithful to it. Tests compare exact tree structures after specific operation sequences, so a generic textbook AVL implementation will not pass.

Required exports: `ht`, `mkt`, `mkt_bal_l`, `mkt_bal_r`, `avl_insert`, `delete_max`, `delete_root`, `avl_delete`, `is_in`, `set_of`, `is_avl`. Use `avl_insert` and `avl_delete` (prefixed) to avoid Python built-in conflicts.