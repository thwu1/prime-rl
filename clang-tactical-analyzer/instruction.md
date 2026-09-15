Implement a parser and semantic analyzer for the RoboCup Soccer Simulation 2D **Standard Coach Language (CLang)** at `/app/clang_analyzer.py`.

CLang is an S-expression-based DSL used by online coaches to communicate tactical rules, formations, and advice to player agents during simulated soccer matches. The formal grammar is at `/app/clang_grammar.txt`. Sample message sequences are in `/app/scenarios/*.clang`.

## Invocation

```
python3 /app/clang_analyzer.py /app/scenarios/<file>.clang
```

Reads a sequence of CLang messages (one per line; lines starting with `#` are comments) and writes a JSON analysis object to stdout.

## Required Output Fields

- **`defined_conditions`**, **`defined_actions`**, **`defined_regions`**, **`defined_directives`**: sorted lists of names of currently-defined (non-deleted) entities of each type.
- **`active_rules`**: sorted list of currently active, non-deleted rule names.
- **`deleted_entities`**: sorted list of all deleted entity names.
- **`dependencies`**: dict mapping each non-deleted rule name to a sorted list of entity names (conditions, actions, regions, directives, other rules) directly referenced in its definition via `CLANG_STR` or rule-name identifiers.
- **`conflicts`**: sorted list of `[rule_a, rule_b]` pairs (`rule_a < rule_b` alphabetically) among **active** rules where the same player number receives different action types (e.g. `shoot` vs `pass`) under conditions that could be simultaneously true. Two conditions are **mutually exclusive** if: (a) they require `bowner` for different teams, (b) they require `bowner` for different specific players on the same team (neither being wildcard `{0}`), or (c) they require different `playm` modes. All `and`/`or`/`not` connectives must be resolved when checking exclusivity. Otherwise, assume potential overlap.
- **`player_coverage`**: dict mapping player number (string keys `"1"`-`"11"`) to a sorted list of active rule names containing `do`/`dont` directives targeting that player. Only include players that appear in at least one active rule.
- **`expanded_rules`**: for each active rule whose body references other rules by name (nested rules), provide the expansion after distributing the outer condition into each sub-rule's condition via `and`. Format: `{"num_clauses": N, "clauses": [{"directives": [{"team": "our"|"opp", "players": [int, ...], "actions": ["keyword", ...]}]}, ...]}`. Action keywords are the bare verb (e.g. `"pos"`, `"shoot"`, `"pass"`). Only include rules that actually have nested sub-rules.

The parser must handle all CLang message types (`define`, `rule`, `delete`, `freeform`), all condition/action/directive/region/point sub-expressions including recursive point arithmetic, `{0}` as wildcard for players 1-11, and string references to previously-defined entities in any grammar position.