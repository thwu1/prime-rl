/*
 * trace_reader - Binary halo exchange trace inspection tool
 *
 * Reads .trace files containing reference communication patterns
 * for 3D structured grid halo exchanges.
 */


#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

#pragma pack(push, 1)
typedef struct {
    char     magic[4];
    uint32_t version;
    uint32_t num_procs;
    uint32_t Nx, Ny, Nz;
    uint32_t stencil_type;
    uint32_t halo_depth;
    uint32_t elem_bytes;
    uint32_t Px, Py, Pz;
    uint64_t per_process_volume;
    uint64_t total_volume;
    double   estimated_time_us;
    uint32_t num_records;
} TraceHeader;
#pragma pack(pop)

static void print_usage(const char *prog) {
    fprintf(stderr, "Usage: %s <trace_file> [command] [args...]\n\n", prog);
    fprintf(stderr, "Commands:\n");
    fprintf(stderr, "  info              Trace header and configuration\n");
    fprintf(stderr, "  decomposition     Optimal process decomposition\n");
    fprintf(stderr, "  volumes           Communication volume data\n");
    fprintf(stderr, "  timing            Exchange time estimate\n");
    fprintf(stderr, "  neighbors <rank>  Neighbor list for a specific rank\n");
    fprintf(stderr, "  graph             Neighbor graph summary statistics\n");
    fprintf(stderr, "\nWith no command, shows info.\n");
}

static int read_header(FILE *fp, TraceHeader *hdr) {
    if (fread(hdr, sizeof(TraceHeader), 1, fp) != 1) {
        fprintf(stderr, "Error: failed to read trace header\n");
        return -1;
    }
    if (memcmp(hdr->magic, "HXTR", 4) != 0) {
        fprintf(stderr, "Error: invalid magic (expected HXTR)\n");
        return -1;
    }
    if (hdr->version != 1) {
        fprintf(stderr, "Error: unsupported trace version %u\n", hdr->version);
        return -1;
    }
    return 0;
}

static void cmd_info(const TraceHeader *hdr) {
    printf("Trace Format Version: %u\n", hdr->version);
    printf("Processes: %u\n", hdr->num_procs);
    printf("Global Domain: %u x %u x %u\n", hdr->Nx, hdr->Ny, hdr->Nz);
    printf("Stencil Type: %u-point\n", hdr->stencil_type);
    printf("Halo Depth: %u\n", hdr->halo_depth);
    printf("Element Size: %u bytes\n", hdr->elem_bytes);
    printf("Records: %u\n", hdr->num_records);
}

static void cmd_decomposition(const TraceHeader *hdr) {
    printf("Optimal Decomposition: %u x %u x %u\n", hdr->Px, hdr->Py, hdr->Pz);
    printf("Subdomain Dimensions: %u x %u x %u\n",
           hdr->Nx / hdr->Px, hdr->Ny / hdr->Py, hdr->Nz / hdr->Pz);
    printf("Product Check: %u x %u x %u = %u (expected %u)\n",
           hdr->Px, hdr->Py, hdr->Pz,
           hdr->Px * hdr->Py * hdr->Pz, hdr->num_procs);
}

static void cmd_volumes(const TraceHeader *hdr) {
    printf("Per-Process Volume: %lu bytes\n", (unsigned long)hdr->per_process_volume);
    printf("Total Volume: %lu bytes\n", (unsigned long)hdr->total_volume);
    printf("Volume Check: %lu x %u = %lu (expected %lu)\n",
           (unsigned long)hdr->per_process_volume, hdr->num_procs,
           (unsigned long)(hdr->per_process_volume * hdr->num_procs),
           (unsigned long)hdr->total_volume);
}

static void cmd_timing(const TraceHeader *hdr) {
    printf("Estimated Exchange Time: %.6f us\n", hdr->estimated_time_us);
}

static int cmd_neighbors(FILE *fp, const TraceHeader *hdr, uint32_t target) {
    uint32_t i, j;
    if (target >= hdr->num_procs) {
        fprintf(stderr, "Error: rank %u out of range [0, %u)\n", target, hdr->num_procs);
        return -1;
    }
    for (i = 0; i < hdr->num_records; i++) {
        uint32_t rank, nn;
        uint32_t *nbs = NULL;
        if (fread(&rank, 4, 1, fp) != 1 || fread(&nn, 4, 1, fp) != 1) {
            fprintf(stderr, "Error: truncated record %u\n", i);
            return -1;
        }
        if (nn > 0) {
            nbs = (uint32_t *)malloc(nn * sizeof(uint32_t));
            if (!nbs || fread(nbs, 4, nn, fp) != nn) {
                fprintf(stderr, "Error: truncated neighbors for rank %u\n", rank);
                free(nbs);
                return -1;
            }
        }
        if (rank == target) {
            printf("Rank %u: %u neighbors\n", rank, nn);
            if (nn > 0) {
                printf("Neighbors:");
                for (j = 0; j < nn; j++)
                    printf(" %u", nbs[j]);
                printf("\n");
            }
            free(nbs);
            return 0;
        }
        free(nbs);
    }
    fprintf(stderr, "Rank %u not found\n", target);
    return -1;
}

static int cmd_graph(FILE *fp, const TraceHeader *hdr) {
    uint32_t i;
    uint64_t total_edges = 0;
    uint32_t min_nb = UINT32_MAX, max_nb = 0;

    for (i = 0; i < hdr->num_records; i++) {
        uint32_t rank, nn;
        if (fread(&rank, 4, 1, fp) != 1 || fread(&nn, 4, 1, fp) != 1) {
            fprintf(stderr, "Error: truncated record %u\n", i);
            return -1;
        }
        if (nn < min_nb) min_nb = nn;
        if (nn > max_nb) max_nb = nn;
        total_edges += nn;
        if (nn > 0)
            fseek(fp, (long)nn * 4, SEEK_CUR);
    }

    printf("Total Directed Edges: %lu\n", (unsigned long)total_edges);
    printf("Undirected Pairs: %lu\n", (unsigned long)(total_edges / 2));
    printf("Min Neighbors: %u\n", min_nb);
    printf("Max Neighbors: %u\n", max_nb);
    return 0;
}

int main(int argc, char *argv[]) {
    FILE *fp;
    TraceHeader hdr;
    const char *cmd;

    if (argc < 2) {
        print_usage(argv[0]);
        return 1;
    }

    fp = fopen(argv[1], "rb");
    if (!fp) {
        fprintf(stderr, "Error: cannot open '%s'\n", argv[1]);
        return 1;
    }

    if (read_header(fp, &hdr) != 0) {
        fclose(fp);
        return 1;
    }

    cmd = (argc >= 3) ? argv[2] : "info";

    if (strcmp(cmd, "info") == 0) {
        cmd_info(&hdr);
    } else if (strcmp(cmd, "decomposition") == 0) {
        cmd_decomposition(&hdr);
    } else if (strcmp(cmd, "volumes") == 0) {
        cmd_volumes(&hdr);
    } else if (strcmp(cmd, "timing") == 0) {
        cmd_timing(&hdr);
    } else if (strcmp(cmd, "neighbors") == 0) {
        int rc;
        if (argc < 4) {
            fprintf(stderr, "Usage: %s <file> neighbors <rank>\n", argv[0]);
            fclose(fp);
            return 1;
        }
        rc = cmd_neighbors(fp, &hdr, (uint32_t)atoi(argv[3]));
        fclose(fp);
        return rc != 0 ? 1 : 0;
    } else if (strcmp(cmd, "graph") == 0) {
        int rc = cmd_graph(fp, &hdr);
        fclose(fp);
        return rc != 0 ? 1 : 0;
    } else {
        fprintf(stderr, "Unknown command: %s\n", cmd);
        print_usage(argv[0]);
        fclose(fp);
        return 1;
    }

    fclose(fp);
    return 0;
}
