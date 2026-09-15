/*
 *
 * InChI Processing Pipeline - main driver
 *
 * Usage:
 *   inchi_pipeline --keys                Read InChI from stdin, output InChIKeys
 *   inchi_pipeline --sdf <file>          Parse SDF, extract InChI, output InChIKeys
 *   inchi_pipeline --dedup <file>        Parse SDF, find duplicate molecules
 */

#define _POSIX_C_SOURCE 200809L

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "inchikey.h"
#include "sdf_parser.h"
#include "dedup.h"

static int mode_keys(void)
{
    char line[8192];
    char key[28];

    while (fgets(line, sizeof(line), stdin)) {
        size_t len = strlen(line);
        while (len > 0 && (line[len-1] == '\n' || line[len-1] == '\r'))
            line[--len] = '\0';
        if (len == 0) continue;
        if (line[0] == '#') continue;

        if (generate_inchikey(line, key) != 0) {
            fprintf(stderr, "Error processing: %s\n", line);
            return 1;
        }
        printf("%s\n", key);
    }
    return 0;
}

static int mode_sdf(const char *filename)
{
    sdf_record *records = NULL;
    int count = 0;

    if (sdf_parse_file(filename, &records, &count) != 0) {
        fprintf(stderr, "Failed to parse SDF file: %s\n", filename);
        return 1;
    }

    char key[28];
    int errors = 0;
    for (int i = 0; i < count; i++) {
        if (records[i].inchi[0] == '\0') {
            fprintf(stderr, "Record %d (%s): no InChI annotation\n",
                    i + 1, records[i].name);
            errors++;
            continue;
        }
        if (generate_inchikey(records[i].inchi, key) != 0) {
            fprintf(stderr, "Record %d (%s): InChIKey generation failed\n",
                    i + 1, records[i].name);
            errors++;
            continue;
        }
        printf("%s\t%s\n", key, records[i].name);
    }

    sdf_free_records(records, count);
    return errors > 0 ? 1 : 0;
}

static int mode_dedup(const char *filename)
{
    sdf_record *records = NULL;
    int count = 0;

    if (sdf_parse_file(filename, &records, &count) != 0) {
        fprintf(stderr, "Failed to parse SDF file: %s\n", filename);
        return 1;
    }

    dedup_table *table = dedup_create(count * 2 + 1);
    if (!table) {
        fprintf(stderr, "Failed to create dedup table\n");
        sdf_free_records(records, count);
        return 1;
    }

    char key[28];
    int dup_count = 0;

    for (int i = 0; i < count; i++) {
        if (records[i].inchi[0] == '\0') continue;
        if (generate_inchikey(records[i].inchi, key) != 0) continue;

        int first = dedup_insert(table, key, i);
        if (first >= 0) {
            printf("DUPLICATE: records %d (%s) and %d (%s) share InChIKey %s\n",
                   first + 1, records[first].name,
                   i + 1, records[i].name, key);
            dup_count++;
        }
    }

    if (dup_count == 0) {
        printf("No duplicates found.\n");
    } else {
        printf("Total: %d duplicate pair(s) found.\n", dup_count);
    }

    dedup_free(table);
    sdf_free_records(records, count);
    return 0;
}

int main(int argc, char *argv[])
{
    if (argc < 2) {
        fprintf(stderr,
                "Usage: %s --keys | --sdf <file> | --dedup <file>\n",
                argv[0]);
        return 1;
    }

    if (strcmp(argv[1], "--keys") == 0) {
        return mode_keys();
    } else if (strcmp(argv[1], "--sdf") == 0) {
        if (argc < 3) {
            fprintf(stderr, "Usage: %s --sdf <file>\n", argv[0]);
            return 1;
        }
        return mode_sdf(argv[2]);
    } else if (strcmp(argv[1], "--dedup") == 0) {
        if (argc < 3) {
            fprintf(stderr, "Usage: %s --dedup <file>\n", argv[0]);
            return 1;
        }
        return mode_dedup(argv[2]);
    } else {
        fprintf(stderr, "Unknown option: %s\n", argv[1]);
        return 1;
    }
}
