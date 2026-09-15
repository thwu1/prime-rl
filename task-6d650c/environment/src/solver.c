/*
 * 15-Puzzle Solver - Manhattan Distance + IDA*
 * Prototype implementation
 *
 * Usage: ./solver <puzzle_file>
 * Input format: first line is puzzle count, then 16 tiles per line
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#define N 4
#define NN 16
#define MAX_DEPTH 85
#define INF 9999

static int board[NN], tpos[NN], blank_pos;
static int solution[MAX_DEPTH], sol_length;
static int found;
static clock_t start_clock;

static const int dr[] = {-1, 1, 0, 0};
static const int dc[] = {0, 0, -1, 1};
static const char dname[] = {'U', 'D', 'L', 'R'};
static const int opposite[] = {1, 0, 3, 2};

static int manhattan(void) {
    int dist = 0;
    for (int pos = 0; pos < NN; pos++) {
        int tile = board[pos];
        if (tile == 0) continue;
        dist += abs(tile / N - pos / N) + abs(tile % N - pos % N);
    }
    return dist;
}

static int dfs(int g, int threshold, int last_dir) {
    if ((clock() - start_clock) > 30 * CLOCKS_PER_SEC) return -2;

    int h = manhattan();
    int f = g + h;
    if (f > threshold) return f;
    if (h == 0) { sol_length = g; found = 1; return -1; }

    int min_next = INF;
    int br = blank_pos / N, bc = blank_pos % N;

    for (int d = 0; d < 4; d++) {
        if (last_dir >= 0 && d == opposite[last_dir]) continue;
        int nr = br + dr[d], nc = bc + dc[d];
        if (nr < 0 || nr >= N || nc < 0 || nc >= N) continue;
        int np = nr * N + nc;

        int tile = board[np];
        board[blank_pos] = tile; board[np] = 0;
        tpos[tile] = blank_pos; tpos[0] = np;
        int ob = blank_pos; blank_pos = np;
        solution[g] = d;

        int r = dfs(g + 1, threshold, d);
        if (found) return -1;
        if (r == -2) return -2;
        if (r < min_next) min_next = r;

        blank_pos = ob;
        board[np] = tile; board[ob] = 0;
        tpos[tile] = np; tpos[0] = ob;
    }
    return min_next;
}

int main(int argc, char **argv) {
    if (argc < 2) {
        fprintf(stderr, "Usage: %s <puzzle_file>\n", argv[0]);
        return 1;
    }

    FILE *fp = fopen(argv[1], "r");
    if (!fp) { fprintf(stderr, "Cannot open %s\n", argv[1]); return 1; }

    int count;
    if (fscanf(fp, "%d", &count) != 1) {
        fprintf(stderr, "Error: failed to read puzzle count from input\n");
        fclose(fp);
        return 1;
    }

    for (int p = 0; p < count; p++) {
        for (int i = 0; i < NN; i++) {
            if (fscanf(fp, "%d", &board[i]) != 1) {
                fprintf(stderr, "Error: parse failure at puzzle %d, tile %d\n", p + 1, i);
                fclose(fp);
                return 1;
            }
            tpos[board[i]] = i;
        }
        blank_pos = tpos[0];

        start_clock = clock();
        found = 0;
        int h = manhattan();
        int threshold = h;

        if (h == 0) {
            printf("Puzzle %d: 0 moves (already solved)\n", p + 1);
            continue;
        }

        while (!found) {
            int r = dfs(0, threshold, -1);
            if (found) break;
            if (r == -2) {
                printf("Puzzle %d: TIMEOUT after 30s (last threshold=%d)\n", p + 1, threshold);
                break;
            }
            if (r >= INF) {
                printf("Puzzle %d: NO SOLUTION\n", p + 1);
                break;
            }
            threshold = r;
        }

        if (found) {
            printf("Puzzle %d: %d moves:", p + 1, sol_length);
            for (int i = 0; i < sol_length; i++)
                printf(" %c", dname[solution[i]]);
            printf("\n");
        }
    }

    fclose(fp);
    return 0;
}
