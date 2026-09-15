/*
 * Fast Sudoku solution counter using backtracking with bitmask constraints.
 *
 * Usage: ./sudoku_solver <puzzle_string> [limit]
 *   puzzle_string: 81 characters, digits 1-9 for clues, 0 or . for blanks
 *   limit: stop counting after this many solutions (default: 2)
 *
 * Output: prints the solution count (up to limit) to stdout.
 */

#include <stdio.h>
#include <string.h>
#include <stdlib.h>

static int rows[9], cols[9], boxes[9];
static int blanks[81], nblanks;
static int solution_count, solution_limit;

static inline int box_index(int pos) {
    int r = pos / 9, c = pos % 9;
    return (r / 3) * 3 + c / 3;
}

static inline void set_cell(int pos, int val) {
    int r = pos / 9, c = pos % 9;
    int b = (r / 3) * 3 + c / 3;
    int mask = 1 << val;
    rows[r] |= mask;
    cols[c] |= mask;
    boxes[b] |= mask;
}

static inline void clear_cell(int pos, int val) {
    int r = pos / 9, c = pos % 9;
    int b = (r / 3) * 3 + c / 3;
    int mask = 1 << val;
    rows[r] &= ~mask;
    cols[c] &= ~mask;
    boxes[b] &= ~mask;
}

static void solve(int idx) {
    int pos, r, c, b, used, v;
    if (solution_count >= solution_limit) return;
    if (idx == nblanks) {
        solution_count++;
        return;
    }
    pos = blanks[idx];
    r = pos / 9;
    c = pos % 9;
    b = (r / 3) * 3 + c / 3;
    used = rows[r] | cols[c] | boxes[b];
    for (v = 1; v <= 9; v++) {
        if (!(used & (1 << v))) {
            set_cell(pos, v);
            solve(idx + 1);
            clear_cell(pos, v);
            if (solution_count >= solution_limit) return;
        }
    }
}

int main(int argc, char *argv[]) {
    char *puzzle;
    int i;
    char ch;

    if (argc < 2) {
        fprintf(stderr, "Usage: %s <puzzle_string> [limit]\n", argv[0]);
        return 1;
    }
    puzzle = argv[1];
    if (strlen(puzzle) != 81) {
        fprintf(stderr, "Error: puzzle must be exactly 81 characters, got %lu\n",
                (unsigned long)strlen(puzzle));
        return 1;
    }

    solution_limit = 2;
    if (argc >= 3) {
        solution_limit = atoi(argv[2]);
        if (solution_limit < 1) solution_limit = 2;
    }

    memset(rows, 0, sizeof(rows));
    memset(cols, 0, sizeof(cols));
    memset(boxes, 0, sizeof(boxes));
    nblanks = 0;
    solution_count = 0;

    for (i = 0; i < 81; i++) {
        ch = puzzle[i];
        if (ch == '0' || ch == '.') {
            blanks[nblanks++] = i;
        } else if (ch >= '1' && ch <= '9') {
            set_cell(i, ch - '0');
        } else {
            fprintf(stderr, "Error: invalid character '%c' at position %d\n", ch, i);
            return 1;
        }
    }

    solve(0);
    printf("%d\n", solution_count);
    return 0;
}
