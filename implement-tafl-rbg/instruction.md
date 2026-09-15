The Regular Boardgames (RBG) system at `/app/rbg_system/` provides a domain-specific language for declaratively describing board games using regular-expression-based path algebra. The compiler `rbg2cpp` (pre-built at `/app/rbg_system/rbg2cpp/bin/rbg2cpp`) translates `.rbg` game descriptions into optimized C++ game reasoners. Example game descriptions are in `/app/rbg_system/rbgGames/` and language documentation is in the rbg2cpp README. The perft (performance test) infrastructure for verifying move generation correctness is at `/tests/perft.cpp`.

Implement the game described below in the RBG language and save it to `/app/isolation_breakthrough.rbg`. Compile it using rbg2cpp, build the generated C++ reasoner (requires Boost headers and g++ with C++17 or later), and verify correctness by running perft at depths 1 through 4.

## Game: Isolation Breakthrough (6x6)

**Board:** 6x6 rectangular grid. White pieces fill the bottom two rows (rows 5 and 4). Black pieces fill the top two rows (rows 0 and 1). The middle two rows start empty.

**Players:** White moves first. White's forward direction is up; black's is down.

**Movement:** On their turn a player picks up one of their pieces and moves it exactly one square forward. The piece may move straight-forward onto an empty square, or diagonally-forward (one square forward plus one square left or right) onto a square that is either empty or occupied by an opponent's piece. Landing on an opponent replaces (captures) it.

**Isolation custodial capture:** After a piece is placed at its destination, an additional capture pass is performed. An opponent's piece is removed if it satisfies **both**:

1. **Isolated** — none of its four orthogonal neighbors contain a piece of the same color.
2. **Sandwiched** — the current player has a piece on both ends of the same orthogonal axis through it (i.e., the left AND right neighbors are both the mover's pieces, or the up AND down neighbors are both the mover's pieces).

Removals are resolved iteratively: after removing all qualifying pieces, the board is checked again for newly qualifying pieces (a removal may expose a previously shielded piece), repeating until no more removals apply.

**Victory conditions** (checked in order after captures are resolved):

1. If any of the current player's pieces occupies the opponent's back row (the row farthest from the player's starting side), the current player wins.
2. If no opponent pieces remain on the board, the current player wins.
3. Otherwise play continues. If a player has no legal moves on their turn, the opponent wins.

## Deliverables

Save the completed game description to `/app/isolation_breakthrough.rbg`.