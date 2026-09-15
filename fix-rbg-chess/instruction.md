The Regular Boardgames (RBG) system at `/app/rbg/` provides a domain-specific language for declaratively describing board game rules using regular-expression-like patterns. The RBG-to-C++ compiler (`/app/rbg/rbg2cpp/bin/rbg2cpp`) translates `.rbg` game descriptions into optimized C++ reasoners that enumerate all legal moves and game states via perft (performance test) counting.

Write a complete English Draughts (8x8 American Checkers) game description in the RBG DSL and save it as `/app/draughts.rbg`. The description must implement all of the following rules precisely:

**Board and Setup**: 8×8 board using dark squares only. Each side starts with 12 men placed on the dark squares of their nearest three rows. Black occupies the top three rows; white occupies the bottom three rows.

**Pieces**: Each player has men and kings. All pieces start as men. Use single-character piece names (e.g., `b`, `w` for men, `B`, `W` for kings, `e` for empty).

**Men**: Move forward diagonally one square to an unoccupied square. Capture by jumping forward diagonally over an adjacent opponent piece (man or king) to an unoccupied square beyond it. The captured piece is removed immediately.

**Kings**: Move one square diagonally in any of the four diagonal directions to an unoccupied square. Capture by jumping diagonally in any direction over an adjacent opponent piece to an unoccupied square beyond it.

**Mandatory Capture**: If any capture is available to the current player, a capture must be made. Non-capture moves are illegal when any capture exists for any of the player's pieces.

**Multi-Jump Sequences**: After a capture, if the capturing piece can immediately make another capture from its landing square, it must continue jumping. The sequence continues until no further captures are available from the current position.

**King Promotion**: A man reaching the opposite back rank is promoted to king. If a man reaches the back rank during a multi-jump sequence, the sequence ends immediately upon promotion — the newly crowned king does not continue jumping on that turn.

**Turn Order**: Black moves first.

**Game End**: A player who cannot make any legal move on their turn loses (opponent scores 100).

The file must produce these exact perft leaf-node counts from the initial position:

| Depth | Leaves  |
|-------|---------|
| 1     | 7       |
| 2     | 49      |
| 3     | 302     |
| 4     | 1,469   |
| 5     | 7,361   |
| 6     | 36,768  |
| 7     | 179,740 |

Reference `.rbg` game descriptions for various other games are available at `/app/rbg/rbgGames/`. Study these to learn the RBG language syntax — macros, piece sets, board definitions, movement patterns, direction repetition operators, lookaheads (`{? ...}` / `{! ...}`), iteration, keeper transitions (`->>`), etc. No draughts or checkers reference exists in the environment.

To compile and test your description: from `/app/`, run `/app/rbg/rbg2cpp/bin/rbg2cpp -o reasoner draughts.rbg`, then `g++ -std=c++23 -O2 reasoner.cpp /app/rbg/rbg2cpp/test/perft.cpp -I. -o perft_test`, then `./perft_test <depth>`.