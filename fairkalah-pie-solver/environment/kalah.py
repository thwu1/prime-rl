"""
Kalah Game Engine - Standard Rules

Implements Kalah(n,s): n pits per side, s initial stones per pit.

Board layout (example n=3):

       [N2] [N1] [N0]
  [NS]                 [SS]
       [S0] [S1] [S2]

Internal board array of length 2*(n+1):
  board[0..n-1]       : South pits (S0, S1, ..., S_{n-1})
  board[n]            : South store (SS)
  board[n+1..2n]      : North pits (N0, N1, ..., N_{n-1})
  board[2n+1]         : North store (NS)

Sowing order (counter-clockwise):
  S0 -> S1 -> ... -> S_{n-1} -> SS -> N0 -> N1 -> ... -> N_{n-1} -> NS -> S0 -> ...
  Skip opponent's store during sowing.

Standard Kalah rules:
  1. Pick up all stones from one of your non-empty pits.
  2. Sow counter-clockwise, one stone per pit/store, skipping opponent's store.
  3. If last stone lands in your store: extra turn.
  4. If last stone lands in an empty pit on your side and the opposite pit
     has stones: capture -- move the landing stone and all opposite stones
     to your store.
  5. Game ends when all pits on one side are empty.
  6. Remaining stones go to the respective side's store.
  7. Higher store total wins.
"""


class KalahState:
    SOUTH = 0
    NORTH = 1

    def __init__(self, pits_per_side, board=None, seeds_per_pit=None, side_to_move=0):
        self.n = pits_per_side
        self.side = side_to_move
        if board is not None:
            self.board = list(board)
        else:
            self.board = [0] * (2 * (pits_per_side + 1))
            if seeds_per_pit is not None:
                for i in range(pits_per_side):
                    self.board[i] = seeds_per_pit
                    self.board[pits_per_side + 1 + i] = seeds_per_pit

    def clone(self):
        st = KalahState.__new__(KalahState)
        st.n = self.n
        st.side = self.side
        st.board = list(self.board)
        return st

    def key(self):
        return (tuple(self.board), self.side)

    def south_store_idx(self):
        return self.n

    def north_store_idx(self):
        return 2 * self.n + 1

    def own_store_idx(self):
        return self.n if self.side == 0 else 2 * self.n + 1

    def opp_store_idx(self):
        return 2 * self.n + 1 if self.side == 0 else self.n

    def own_pit_indices(self):
        if self.side == 0:
            return range(0, self.n)
        else:
            return range(self.n + 1, 2 * self.n + 1)

    def legal_moves(self):
        return [i for i in self.own_pit_indices() if self.board[i] > 0]

    def is_terminal(self):
        south_empty = all(self.board[i] == 0 for i in range(self.n))
        north_empty = all(self.board[i] == 0 for i in range(self.n + 1, 2 * self.n + 1))
        return south_empty or north_empty

    def terminal_score(self):
        """Collect remaining stones and return south_store - north_store."""
        s = self.board[self.n]
        n = self.board[2 * self.n + 1]
        for i in range(self.n):
            s += self.board[i]
        for i in range(self.n + 1, 2 * self.n + 1):
            n += self.board[i]
        return s - n

    def make_move(self, pit_idx):
        """
        Execute a sowing move from the given pit index.
        Returns True if the current player gets an extra turn.
        Implements standard Kalah rules with captures on empty pits.
        """
        n = self.n
        stones = self.board[pit_idx]
        self.board[pit_idx] = 0
        total_slots = 2 * (n + 1)
        opp_store = self.opp_store_idx()
        own_store = self.own_store_idx()

        idx = pit_idx
        for _ in range(stones):
            idx = (idx + 1) % total_slots
            if idx == opp_store:
                idx = (idx + 1) % total_slots
            self.board[idx] += 1

        # Extra turn: last stone in own store
        if idx == own_store:
            return True

        # Capture: last stone in an empty own pit, opposite has stones
        if self.side == 0:
            is_own_pit = 0 <= idx < n
        else:
            is_own_pit = n + 1 <= idx <= 2 * n

        if is_own_pit and self.board[idx] == 1:
            opp_idx = 2 * n - idx
            if self.board[opp_idx] > 0:
                self.board[own_store] += self.board[idx] + self.board[opp_idx]
                self.board[idx] = 0
                self.board[opp_idx] = 0

        self.side = 1 - self.side
        return False

    def display(self):
        n = self.n
        north_pits = [self.board[2 * n - i] for i in range(n)]
        south_pits = [self.board[i] for i in range(n)]
        ns = self.board[2 * n + 1]
        ss = self.board[n]
        pit_w = 4
        header = "  " + "".join(f"{v:>{pit_w}}" for v in north_pits)
        stores = f"{ns:>2}" + " " * (pit_w * n) + f"  {ss:>2}"
        footer = "  " + "".join(f"{v:>{pit_w}}" for v in south_pits)
        side_str = "South" if self.side == 0 else "North"
        return f"{header}\n{stores}\n{footer}\nTo move: {side_str}"
