"""
SameGame Reference Engine

Board representation:
  - grid[row][col] where row 0 is the bottom row, row 14 is the top
  - Colors are integers 0-4; empty cells are -1
  - Coordinates (col, row) with (0, 0) at bottom-left

Board file format:
  - 15 lines of 15 space-separated integers
  - First line = row 14 (top), last line = row 0 (bottom)
"""



class SameGameEngine:
    ROWS = 15
    COLS = 15

    def __init__(self, grid):
        self.grid = [list(row) for row in grid]
        self.score = 0

    @classmethod
    def from_file(cls, filename):
        with open(filename) as f:
            lines = [line.strip() for line in f if line.strip()]
        assert len(lines) == 15, f"Expected 15 lines, got {len(lines)}"
        grid = []
        for line in reversed(lines):
            row = [int(x) for x in line.split()]
            assert len(row) == 15, f"Expected 15 columns, got {len(row)}"
            grid.append(row)
        return cls(grid)

    def copy(self):
        eng = SameGameEngine.__new__(SameGameEngine)
        eng.grid = [row[:] for row in self.grid]
        eng.score = self.score
        return eng

    def get(self, col, row):
        if 0 <= col < self.COLS and 0 <= row < self.ROWS:
            return self.grid[row][col]
        return -1

    def find_group(self, col, row):
        color = self.get(col, row)
        if color < 0:
            return []
        visited = set()
        stack = [(col, row)]
        group = []
        while stack:
            c, r = stack.pop()
            if (c, r) in visited:
                continue
            if not (0 <= c < self.COLS and 0 <= r < self.ROWS):
                continue
            if self.grid[r][c] != color:
                continue
            visited.add((c, r))
            group.append((c, r))
            stack.append((c + 1, r))
            stack.append((c - 1, r))
            stack.append((c, r + 1))
            stack.append((c, r - 1))
        return group

    def is_valid_move(self, col, row):
        if not (0 <= col < self.COLS and 0 <= row < self.ROWS):
            return False
        if self.grid[row][col] < 0:
            return False
        return len(self.find_group(col, row)) >= 2

    def apply_move(self, col, row):
        group = self.find_group(col, row)
        if len(group) < 2:
            raise ValueError(
                f"Invalid move at ({col}, {row}): group size {len(group)}"
            )

        n = len(group)
        move_score = (n - 2) ** 2
        self.score += move_score

        # Remove cells
        for c, r in group:
            self.grid[r][c] = -1

        # Gravity: cells fall down within each column
        for c in range(self.COLS):
            filled = [self.grid[r][c] for r in range(self.ROWS) if self.grid[r][c] >= 0]
            for r in range(self.ROWS):
                self.grid[r][c] = filled[r] if r < len(filled) else -1

        # Column collapse: shift non-empty columns to the left
        non_empty = [c for c in range(self.COLS) if self.grid[0][c] >= 0]
        new_grid = [[-1] * self.COLS for _ in range(self.ROWS)]
        for new_c, old_c in enumerate(non_empty):
            for r in range(self.ROWS):
                new_grid[r][new_c] = self.grid[r][old_c]
        self.grid = new_grid

        return move_score

    def is_cleared(self):
        return self.grid[0][0] < 0

    def is_game_over(self):
        for r in range(self.ROWS):
            for c in range(self.COLS):
                if self.grid[r][c] >= 0:
                    color = self.grid[r][c]
                    for dc, dr in [(1, 0), (0, 1)]:
                        nc, nr = c + dc, r + dr
                        if 0 <= nc < self.COLS and 0 <= nr < self.ROWS:
                            if self.grid[nr][nc] == color:
                                return False
        return True

    def final_score(self):
        return self.score + (1000 if self.is_cleared() else 0)

    def get_all_groups(self):
        visited = set()
        groups = []
        for r in range(self.ROWS):
            for c in range(self.COLS):
                if (c, r) not in visited and self.grid[r][c] >= 0:
                    group = self.find_group(c, r)
                    for cell in group:
                        visited.add(cell)
                    if len(group) >= 2:
                        groups.append(group)
        return groups
