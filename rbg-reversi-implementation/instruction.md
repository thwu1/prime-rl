The Regular Boardgames (RBG) system at `/app/rbg` is a domain-specific language for formally describing board games using regular expressions. Game descriptions compile to C++ via `rbg2cpp`, producing a game engine with move generation, state management, and performance testing infrastructure (perft).

The RBG toolchain is pre-built:
- Compiler: `/app/rbg/rbg2cpp/bin/rbg2cpp`
- Perft test source: `/app/rbg/rbg2cpp/test/perft.cpp`
- Reference `.rbg` game files for learning the syntax: `/app/examples/`

Write a complete, correct RBG game description for **6x6 Reversi (Othello)** at `/app/reversi6x6.rbg`.

**Game rules:** 6x6 board. Initial center 2x2 has alternating pieces (0-indexed: white at (2,2) and (3,3), black at (2,3) and (3,2)). Black moves first. A player places a piece on an empty square that brackets at least one contiguous line of opponent pieces (in any of 8 directions) between the new piece and an existing piece of the same color; all bracketed opponent pieces flip. If a player has no legal placement, they pass (the pass still counts as their turn in the game's move sequence). The game ends when neither player can place. The player with more pieces scores 100, the other 0; if equal, both score 50.

The file must parse and compile without errors, and the compiled game must produce correct perft (performance test) counts at depths 1 through 4.