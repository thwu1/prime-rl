/*
 * BSP map analyser — main entry point.
 * Opens a WAD file, loads BSP data, and processes geometric queries.
 */


#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "fixed_math.h"
#include "wad_reader.h"
#include "bsp.h"

int main(int argc, char **argv)
{
    if (argc != 4) {
        fprintf(stderr, "Usage: %s <wad_file> <query_file> <output_file>\n",
                argv[0]);
        return 1;
    }

    /* ---- Load WAD and BSP data ---- */
    if (wad_open(argv[1]) != 0) {
        fprintf(stderr, "Error: cannot open WAD '%s'\n", argv[1]);
        return 1;
    }

    node_t      *nodes       = NULL;
    subsector_t *subsectors  = NULL;
    int          num_nodes   = 0;
    int          num_ss      = 0;

    if (wad_load_nodes(&nodes, &num_nodes) != 0) {
        fprintf(stderr, "Error: failed to load NODES lump\n");
        wad_close();
        return 1;
    }
    if (wad_load_subsectors(&subsectors, &num_ss) != 0) {
        fprintf(stderr, "Error: failed to load SSECTORS lump\n");
        wad_close();
        free(nodes);
        return 1;
    }

    bsp_set_data(nodes, num_nodes, subsectors, num_ss);
    wad_close();

    /* ---- Process queries ---- */
    FILE *qf = fopen(argv[2], "r");
    FILE *of = fopen(argv[3], "w");
    if (!qf || !of) {
        fprintf(stderr, "Error: cannot open query/output files\n");
        return 1;
    }

    char line[512];
    while (fgets(line, sizeof(line), qf)) {
        char cmd[32];
        if (sscanf(line, "%31s", cmd) != 1)
            continue;

        if (strcmp(cmd, "LOCATE") == 0) {
            int32_t x, y;
            sscanf(line, "%*s %d %d", &x, &y);
            fprintf(of, "%d\n", bsp_locate(x, y));
        }
        else if (strcmp(cmd, "TRAVERSE") == 0) {
            int32_t x, y;
            sscanf(line, "%*s %d %d", &x, &y);
            int buf[4096];
            int n = bsp_traverse(x, y, buf, 4096);
            for (int i = 0; i < n; i++) {
                if (i > 0) fprintf(of, ",");
                fprintf(of, "%d", buf[i]);
            }
            fprintf(of, "\n");
        }
        else if (strcmp(cmd, "ANGLE") == 0) {
            int32_t x1, y1, x2, y2;
            sscanf(line, "%*s %d %d %d %d", &x1, &y1, &x2, &y2);
            fprintf(of, "%u\n", R_PointToAngle2(x1, y1, x2, y2));
        }
        else if (strcmp(cmd, "SIDE") == 0) {
            int32_t px, py, nx, ny, ndx, ndy;
            sscanf(line, "%*s %d %d %d %d %d %d",
                   &px, &py, &nx, &ny, &ndx, &ndy);
            node_t tmp;
            memset(&tmp, 0, sizeof(tmp));
            tmp.x = nx; tmp.y = ny; tmp.dx = ndx; tmp.dy = ndy;
            fprintf(of, "%d\n", R_PointOnSide(px, py, &tmp));
        }
        else if (strcmp(cmd, "HASH") == 0) {
            char name[16];
            sscanf(line, "%*s %15s", name);
            fprintf(of, "%u\n", W_LumpNameHash(name));
        }
        else if (strcmp(cmd, "MUL") == 0) {
            int32_t a, b;
            sscanf(line, "%*s %d %d", &a, &b);
            fprintf(of, "%d\n", FixedMul(a, b));
        }
        else if (strcmp(cmd, "DIV") == 0) {
            int32_t a, b;
            sscanf(line, "%*s %d %d", &a, &b);
            fprintf(of, "%d\n", FixedDiv(a, b));
        }
        else if (strcmp(cmd, "DIRHASH") == 0) {
            fprintf(of, "%u\n", wad_directory_hash());
        }
    }

    fclose(qf);
    fclose(of);
    free(nodes);
    free(subsectors);
    return 0;
}
