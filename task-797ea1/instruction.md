Build `/app/vgdl_analyze.py` — a tool that parses VGDL (Video Game Description Language) game description files and level files from the GVGAI competition framework, performs semantic analysis, and stores all results in a SQLite database at `/app/games.db`.

**Usage**: `python3 /app/vgdl_analyze.py --db /app/games.db --games /app/games/ --levels /app/levels/`

Game files at `/app/games/` are named `<name>.txt`. Level files at `/app/levels/` are named `<name>_<suffix>.txt`. The tool must match level files to their game by filename prefix. Use the filename stem (without `.txt`) as identifiers in the database (e.g. `zelda` for a game, `zelda_0` for a level).

The GVGAI framework Java source at `/app/gvgai-src/` is the authoritative reference implementation for VGDL parsing semantics. The file `ontology_files.txt` lists the framework's complete sprite and effect class hierarchy.

The database must contain these tables with exact column names:

**sprites** `(game TEXT, name TEXT, parent TEXT, base_class TEXT, is_leaf INT)` — Full sprite hierarchy for each game. `base_class` is the resolved VGDL sprite class, accounting for inheritance when a sprite does not declare its own class. `parent` is NULL for root-level sprites. `is_leaf` is 1 for sprites with no children.

**sprite_params** `(game TEXT, sprite TEXT, key TEXT, value TEXT)` — Every parameter for each sprite, including values inherited from ancestor sprites.

**interactions** `(game TEXT, idx INT, sprite1 TEXT, sprite2_csv TEXT, effect TEXT, params_json TEXT)` — Collision/interaction rules in file order (0-indexed). `sprite2_csv` is a comma-separated list of all second-position sprites. `params_json` is a JSON object of the effect's parameters.

**terminations** `(game TEXT, idx INT, term_type TEXT, win INT, params_json TEXT)` — Termination conditions in file order (0-indexed). `win` is 1 for win conditions, 0 for loss.

**level_dims** `(game TEXT, level TEXT, rows INT, cols INT)` — Grid dimensions of each level.

**level_sprite_counts** `(game TEXT, level TEXT, sprite TEXT, count INT)` — Instance count of each sprite type placed by the level's character-to-sprite mapping.

**winnability** `(game TEXT, level TEXT, winnable INT, reason TEXT)` — Whether each level's win condition(s) can be satisfied given the game's sprite definitions, interaction rules, and the sprites present in that level. `winnable` is 1 or 0. Consider how sprites are created, destroyed, and transformed during gameplay when assessing satisfiability.