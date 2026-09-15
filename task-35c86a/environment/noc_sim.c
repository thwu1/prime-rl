/*
 * noc_sim.c - Wormhole NoC Link Congestion Simulator
 *
 * Simulates packet routing on a Tenstorrent Wormhole 10x12 toroidal
 * NoC grid and computes per-link congestion metrics.
 *
 * Usage: ./noc_sim <placements.csv>
 *
 * Input CSV format (with header line):
 *   bank_id,bank_x,bank_y,reader_x,reader_y,noc_id
 *
 * Output: JSON object with routes and congestion analysis.
 *
 * The two NoC fabrics route packets using dimension-ordered routing:
 *   NoC 0: horizontal (east) then vertical (south), with toroidal wrap
 *   NoC 1: horizontal (west) then vertical (north), with toroidal wrap
 *
 * Each fabric has its own independent set of physical links, so traffic
 * on NoC 0 does not interfere with traffic on NoC 1.
 */


#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define GRID_W 10
#define GRID_H 12
#define MAX_PLACEMENTS 12
#define MAX_HOPS 24
#define MAX_LINKS 512

typedef struct {
    int from_x, from_y;
    int to_x, to_y;
} LinkKey;

typedef struct {
    LinkKey key;
    int load;
} LinkEntry;

static LinkEntry link_table[MAX_LINKS];
static int link_count = 0;

static int hops_fx[MAX_PLACEMENTS][MAX_HOPS];
static int hops_fy[MAX_PLACEMENTS][MAX_HOPS];
static int hops_tx[MAX_PLACEMENTS][MAX_HOPS];
static int hops_ty[MAX_PLACEMENTS][MAX_HOPS];
static int hop_counts[MAX_PLACEMENTS];
static int bank_ids[MAX_PLACEMENTS];
static int noc_ids[MAX_PLACEMENTS];

static int find_or_create_link(int noc, int fx, int fy, int tx, int ty) {
    int i;
    for (i = 0; i < link_count; i++) {
        if (link_table[i].key.from_x == fx &&
            link_table[i].key.from_y == fy &&
            link_table[i].key.to_x == tx &&
            link_table[i].key.to_y == ty) {
            return i;
        }
    }
    if (link_count >= MAX_LINKS) {
        fprintf(stderr, "Error: link table overflow\n");
        exit(1);
    }
    link_table[link_count].key.from_x = fx;
    link_table[link_count].key.from_y = fy;
    link_table[link_count].key.to_x = tx;
    link_table[link_count].key.to_y = ty;
    link_table[link_count].load = 0;
    return link_count++;
}

static void compute_route(int idx, int bx, int by, int rx, int ry, int noc_id) {
    int cx = bx, cy = by;
    int n = 0;

    if (noc_id == 0) {
        /* NoC 0: east then south */
        while (cx != rx) {
            int nx = (cx + 1) % GRID_W;
            hops_fx[idx][n] = cx; hops_fy[idx][n] = cy;
            hops_tx[idx][n] = nx; hops_ty[idx][n] = cy;
            n++;
            cx = nx;
        }
        while (cy != ry) {
            int ny = (cy + 1) % GRID_H;
            hops_fx[idx][n] = cx; hops_fy[idx][n] = cy;
            hops_tx[idx][n] = cx; hops_ty[idx][n] = ny;
            n++;
            cy = ny;
        }
    } else {
        /* NoC 1: horizontal then vertical */
        while (cx != rx) {
            int nx = (cx + 1) % GRID_W;
            hops_fx[idx][n] = cx; hops_fy[idx][n] = cy;
            hops_tx[idx][n] = nx; hops_ty[idx][n] = cy;
            n++;
            cx = nx;
        }
        while (cy != ry) {
            int ny = (cy - 1 + GRID_H) % GRID_H;
            hops_fx[idx][n] = cx; hops_fy[idx][n] = cy;
            hops_tx[idx][n] = cx; hops_ty[idx][n] = ny;
            n++;
            cy = ny;
        }
    }
    hop_counts[idx] = n;
}

int main(int argc, char *argv[]) {
    FILE *f;
    char line[256];
    int count = 0;
    int i, h, idx;
    int max_load, total_shared, total_excess;

    if (argc < 2) {
        fprintf(stderr, "Usage: %s <placements.csv>\n", argv[0]);
        return 1;
    }

    f = fopen(argv[1], "r");
    if (!f) {
        fprintf(stderr, "Error: cannot open %s\n", argv[1]);
        return 1;
    }

    /* skip header */
    if (!fgets(line, sizeof(line), f)) {
        fprintf(stderr, "Error: empty input\n");
        fclose(f);
        return 1;
    }

    while (fgets(line, sizeof(line), f) && count < MAX_PLACEMENTS) {
        int bid, bx, by, rx, ry, noc;
        if (sscanf(line, "%d,%d,%d,%d,%d,%d", &bid, &bx, &by, &rx, &ry, &noc) == 6) {
            bank_ids[count] = bid;
            noc_ids[count] = noc;
            compute_route(count, bx, by, rx, ry, noc);
            count++;
        }
    }
    fclose(f);

    /* accumulate link loads */
    link_count = 0;
    for (i = 0; i < count; i++) {
        for (h = 0; h < hop_counts[i]; h++) {
            idx = find_or_create_link(noc_ids[i],
                hops_fx[i][h], hops_fy[i][h],
                hops_tx[i][h], hops_ty[i][h]);
            link_table[idx].load++;
        }
    }

    /* compute congestion metrics */
    max_load = 0;
    total_shared = 0;
    total_excess = 0;
    for (i = 0; i < link_count; i++) {
        if (link_table[i].load > max_load)
            max_load = link_table[i].load;
        if (link_table[i].load > 1) {
            total_shared++;
            total_excess += link_table[i].load - 1;
        }
    }
    if (max_load == 0 && count > 0) max_load = 1;

    /* output JSON */
    printf("{\n");
    printf("  \"route_count\": %d,\n", count);
    printf("  \"routes\": [\n");
    for (i = 0; i < count; i++) {
        printf("    {\"bank_id\": %d, \"noc_id\": %d, \"hops\": [", bank_ids[i], noc_ids[i]);
        for (h = 0; h < hop_counts[i]; h++) {
            if (h > 0) printf(", ");
            printf("[[%d,%d],[%d,%d]]",
                hops_fx[i][h], hops_fy[i][h],
                hops_tx[i][h], hops_ty[i][h]);
        }
        printf("]}");
        if (i < count - 1) printf(",");
        printf("\n");
    }
    printf("  ],\n");
    printf("  \"link_count\": %d,\n", link_count);
    printf("  \"max_link_load\": %d,\n", max_load);
    printf("  \"total_shared_links\": %d,\n", total_shared);
    printf("  \"total_excess_load\": %d\n", total_excess);
    printf("}\n");

    return 0;
}
