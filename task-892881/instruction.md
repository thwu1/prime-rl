Build a Game Description Language (GDL) interpreter at `/app/gdl_engine.py` that delegates logical inference to the SWI-Prolog installation available at `/usr/bin/swipl`. GDL is a logic programming language used in General Game Playing that describes arbitrary games via declarative KIF rules. The engine must translate KIF game descriptions into Prolog source code, invoke `swipl` for backward-chaining inference, and present results through a JSON CLI.

Three game files are provided at `/app/games/`: `switches.kif` (single-player puzzle using negation-as-failure), `tictactoe.kif` (simultaneous-move game with disjunction and conflict resolution), and `connectfour.kif` (alternating-turn game with gravity mechanics and nested negation).

The engine CLI supports six commands:

```
python3 /app/gdl_engine.py <game.kif> roles
python3 /app/gdl_engine.py <game.kif> initial
python3 /app/gdl_engine.py <game.kif> legal --state <f.json> --role <name>
python3 /app/gdl_engine.py <game.kif> next --state <f.json> --moves <f.json>
python3 /app/gdl_engine.py <game.kif> terminal --state <f.json>
python3 /app/gdl_engine.py <game.kif> goal --state <f.json> --role <name>
```

State files are JSON arrays of s-expression strings, e.g. `["(cell 1 1 b)", "(step 1)"]`. Move files are JSON objects mapping role to move, e.g. `{"red": "(drop 4)", "black": "noop"}`. List outputs are sorted JSON arrays. `terminal` outputs `"true"` or `"false"`. `goal` outputs an integer.

The engine must include Prolog source file(s) (`.pl`) at `/app/` containing the inference logic, and `gdl_engine.py` must invoke `swipl` to perform logical reasoning. The KIF-to-Prolog translation must correctly handle GDL reserved keywords (`role`, `init`, `true`, `does`, `legal`, `next`, `terminal`, `goal`), negation-as-failure (`not`), disjunction (`or`), inequality (`distinct`), and KIF variable syntax (`?x` → Prolog variables). Game-defined predicates must be namespaced to avoid clashing with SWI-Prolog built-ins.