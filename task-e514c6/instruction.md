Build a General Game Playing (GDL) reasoner at `/app/gdl_reasoner.py` that parses Game Description Language files and implements the GDL state machine interface.

GDL is a first-order logic language for describing arbitrary board games. Game descriptions in `.kif` format are located at `/app/games/` and use S-expression syntax with these constructs:

- `role` — declares players in the game
- `init` — defines facts true in the initial game state
- `<=` — rules (head implied by body conjuncts)
- `true` — references a fact in the current game state (appears only in rule bodies)
- `does` — references a player's chosen action (appears only in rule bodies for `next`/`legal` rules)
- `legal` — defines which moves are available to a role in the current state
- `next` — defines what facts hold in the successor state given current state and chosen moves
- `terminal` — conditions under which the game ends
- `goal` — payoff values per role (integers 0–100)
- `not` — negation-as-failure
- `or` — disjunction within a rule body
- `distinct` — inequality constraint between two ground terms
- Variables begin with `?`

The reasoner must expose this command-line interface:

```
python3 /app/gdl_reasoner.py <game.kif> <command> [args...]
```

| Command | Arguments | JSON stdout |
|---------|-----------|-------------|
| `roles` | — | `["role1", ...]` |
| `initial_state` | — | `["(fact arg)", "atom", ...]` |
| `legal_moves` | `<role> '<state_json>'` | `["move1", "(move arg)", ...]` |
| `next_state` | `'<state_json>' '<moves_json>'` | `["(fact arg)", ...]` |
| `is_terminal` | `'<state_json>'` | `true` / `false` |
| `goal` | `<role> '<state_json>'` | integer |

**State** is a JSON array of fact strings. Atomic propositions (no arguments) are bare strings: `"h1"`. Relations with arguments use parentheses: `"(cell 1 1 b)"`. All output arrays must be sorted lexicographically.

**Moves** is a JSON object mapping role name to move string: `{"robot": "move"}` or `{"xplayer": "(mark 1 1)", "oplayer": "(mark 2 2)"}`.

The games at `/app/games/` include single-player navigation (maze), simultaneous two-player (tictictoe), turn-based two-player with gravity mechanics (connectFour), and a game using complex derived predicates with nested negation (simpleMutex). The reasoner must handle all of them correctly.