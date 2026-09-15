The application at `/app/` classifies chess puzzles by tactical theme. A `Puzzle` (defined in `/app/model.py`) wraps a `python-chess` game tree representing a forced tactical sequence. The puzzle's `pov` is the winning side; `mainline` is the list of `ChildNode` moves starting from the opponent's blunder.

Eight detection functions in `/app/tagger.py` each take a `Puzzle` and return `True` if the corresponding tactical pattern is present in the solution line:

- **fork**: a non-king piece attacks two or more valuable/hanging pieces simultaneously
- **skewer**: a ray piece forces a valuable piece to move, revealing a capture behind it
- **discovered_attack**: moving one piece reveals check or an attack by a ray piece behind it
- **pin_prevents_attack**: a pinned opponent piece cannot execute an otherwise available attack on a valuable target
- **pin_prevents_escape**: a pinned opponent piece cannot escape capture
- **back_rank_mate**: checkmate on the back rank where the king is trapped by its own pieces
- **smothered_mate**: knight delivers checkmate with all king escape squares blocked by same-color pieces
- **trapped_piece**: a captured piece had no safe square to move to before being taken

The utility library `/app/util.py` and data model `/app/model.py` are complete and correct. The current implementations in `/app/tagger.py` are stubs that return `False`.

Implement all eight detectors in `/app/tagger.py` so that the validation test suite passes.