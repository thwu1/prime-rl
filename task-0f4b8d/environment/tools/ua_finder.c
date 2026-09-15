/*
 * ua_finder - Unavoidable set finder for 9x9 sudoku solution grids
 *
 * Finds 2-digit unavoidable sets using column permutation cycle analysis.
 * Based on McGuire, Tugemann, Civario (2014).
 *
 * Reads grid from stdin (9 lines of 9 digits).
 * Outputs one set per line: comma-separated cell indices (0-80, row-major).
 *
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdbool.h>

#define N 9
#define MAX_SETS 2000

int grid[N][N];
int pos[10][N]; /* pos[d][r] = column of digit d in row r */

typedef struct {
    int cells[24];
    int size;
} UASet;

UASet found[MAX_SETS];
int nfound = 0;
int max_size = 12;

void read_grid(void) {
    char line[256];
    for (int r = 0; r < N; r++) {
        if (!fgets(line, sizeof(line), stdin)) {
            fprintf(stderr, "Error reading row %d\n", r);
            exit(1);
        }
        for (int c = 0; c < N; c++) {
            grid[r][c] = line[c] - '0';
            pos[grid[r][c]][r] = c;
        }
    }
}

int box_of(int r, int c) { return (r / 3) * 3 + c / 3; }

bool check_box_balance(int da, int db, int *rows, int nr) {
    int ca[N] = {0}, cb[N] = {0};
    for (int i = 0; i < nr; i++) {
        int r = rows[i];
        ca[box_of(r, pos[da][r])]++;
        cb[box_of(r, pos[db][r])]++;
    }
    for (int b = 0; b < N; b++)
        if (ca[b] != cb[b]) return false;
    return true;
}

void sort_cells(int *cells, int n) {
    for (int i = 0; i < n - 1; i++)
        for (int j = i + 1; j < n; j++)
            if (cells[i] > cells[j]) {
                int t = cells[i]; cells[i] = cells[j]; cells[j] = t;
            }
}

bool is_duplicate(int *cells, int size) {
    for (int i = 0; i < nfound; i++) {
        if (found[i].size != size) continue;
        bool same = true;
        for (int j = 0; j < size; j++)
            if (found[i].cells[j] != cells[j]) { same = false; break; }
        if (same) return true;
    }
    return false;
}

void add_set(int da, int db, int *rows, int nr) {
    if (nfound >= MAX_SETS) return;
    int cells[24];
    int sz = 0;
    for (int i = 0; i < nr; i++) {
        cells[sz++] = rows[i] * N + pos[da][rows[i]];
        cells[sz++] = rows[i] * N + pos[db][rows[i]];
    }
    sort_cells(cells, sz);
    if (!is_duplicate(cells, sz)) {
        memcpy(found[nfound].cells, cells, sz * sizeof(int));
        found[nfound].size = sz;
        nfound++;
    }
}

void find_sets(void) {
    for (int da = 1; da <= 9; da++) {
        for (int db = da + 1; db <= 9; db++) {
            int row_of_col[N];
            for (int r = 0; r < N; r++)
                row_of_col[pos[da][r]] = r;

            int perm[N];
            for (int c = 0; c < N; c++)
                perm[c] = pos[db][row_of_col[c]];

            bool visited[N] = {false};
            int cycles[N][N], clen[N] = {0};
            int ncyc = 0;

            for (int s = 0; s < N; s++) {
                if (visited[s]) continue;
                int c = s;
                while (!visited[c]) {
                    visited[c] = true;
                    cycles[ncyc][clen[ncyc]++] = c;
                    c = perm[c];
                }
                if (clen[ncyc] >= 2) ncyc++;
                else clen[ncyc] = 0;
            }

            /* Enumerate valid unavoidable sets from permutation cycles.
             * Each individual cycle that satisfies the box balance
             * condition gives a minimal 2-digit unavoidable set. */
            for (int ci = 0; ci < ncyc; ci++) {
                int rows[N], nr = 0;
                for (int j = 0; j < clen[ci]; j++)
                    rows[nr++] = row_of_col[cycles[ci][j]];
                if (nr < 2 || nr * 2 > max_size) continue;
                if (check_box_balance(da, db, rows, nr))
                    add_set(da, db, rows, nr);
            }
        }
    }
}

int main(int argc, char *argv[]) {
    if (argc > 1) max_size = atoi(argv[1]);
    read_grid();
    find_sets();
    for (int i = 0; i < nfound; i++) {
        for (int j = 0; j < found[i].size; j++) {
            if (j > 0) printf(",");
            printf("%d", found[i].cells[j]);
        }
        printf("\n");
    }
    fprintf(stderr, "Found %d 2-digit unavoidable sets\n", nfound);
    return 0;
}
