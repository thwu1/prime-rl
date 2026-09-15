/*
 *
 * SDF file parser implementation.
 *
 * Parses V2000 SDF files and extracts molecule names and InChI annotations
 * from the data block following the MOL block (after M  END).
 *
 * SDF record structure:
 *   - Line 1: molecule name
 *   - Lines 2-3: program info and comment
 *   - MOL block (atom/bond data)
 *   - M  END marker
 *   - Data fields: > <FIELD_NAME> followed by value on next line
 *   - $$$$ record terminator
 */

#define _POSIX_C_SOURCE 200809L

#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include "sdf_parser.h"

/* Strip trailing newline and carriage return from a line */
static void strip_newline(char *s)
{
    size_t len = strlen(s);
    while (len > 0 && (s[len-1] == '\n' || s[len-1] == '\r'))
        s[--len] = '\0';
}

/*
 * Check if a line is a data field header for an InChI field.
 * Accepts headers like:
 *   > <InChI>
 *   > <PUBCHEM_NIST_INCHI>
 * by looking for a tag name that is exactly "InChI" or ends with "INCHI"/"InChI".
 */
static int is_inchi_header(const char *line)
{
    const char *lt = strchr(line, '<');
    if (!lt) return 0;
    const char *gt = strchr(lt, '>');
    if (!gt || gt <= lt + 1) return 0;

    size_t namelen = (size_t)(gt - lt - 1);
    const char *name = lt + 1;

    if (namelen == 5 && strncmp(name, "InChI", 5) == 0) return 1;
    if (namelen >= 5) {
        const char *suffix = name + namelen - 5;
        if (strncmp(suffix, "INCHI", 5) == 0 ||
            strncmp(suffix, "InChI", 5) == 0) return 1;
    }
    return 0;
}

int sdf_parse_file(const char *filename, sdf_record **records_out, int *count_out)
{
    FILE *fp = fopen(filename, "r");
    if (!fp) return -1;

    int capacity = 64;
    sdf_record *records = calloc((size_t)capacity, sizeof(sdf_record));
    if (!records) { fclose(fp); return -1; }

    int count = 0;
    char line[4096];
    int line_in_record = 0;
    int past_mol_block = 0;

    while (fgets(line, sizeof(line), fp)) {
        strip_newline(line);

        /* First line of a new record is the molecule name */
        if (line_in_record == 0) {
            if (count >= capacity) {
                capacity *= 2;
                sdf_record *tmp = realloc(records,
                                          (size_t)capacity * sizeof(sdf_record));
                if (!tmp) { free(records); fclose(fp); return -1; }
                records = tmp;
                memset(&records[count], 0,
                       (size_t)(capacity - count) * sizeof(sdf_record));
            }
            strncpy(records[count].name, line, SDF_MAX_NAME - 1);
            records[count].name[SDF_MAX_NAME - 1] = '\0';
            records[count].inchi[0] = '\0';
            line_in_record++;
            continue;
        }

        /* Detect end of MOL block */
        if (strncmp(line, "M  END", 6) == 0) {
            past_mol_block = 1;
            line_in_record++;
            continue;
        }

        /* Detect record terminator */
        if (strncmp(line, "$$$$", 4) == 0) {
            count++;
            line_in_record = 0;
            past_mol_block = 0;
            continue;
        }

        /* In the data section, look for InChI field header */
        if (past_mol_block && is_inchi_header(line)) {
            /*
             * Read the InChI value from the next line.
             * fgets includes the trailing newline; we copy the raw
             * value into the record's inchi buffer.
             */
            char value_line[4096];
            if (fgets(value_line, sizeof(value_line), fp)) {
                strncpy(records[count].inchi, value_line,
                        SDF_MAX_INCHI - 1);
                records[count].inchi[SDF_MAX_INCHI - 1] = '\0';
            }
            line_in_record++;
            continue;
        }

        line_in_record++;
    }

    fclose(fp);
    *records_out = records;
    *count_out = count;
    return 0;
}

void sdf_free_records(sdf_record *records, int count)
{
    (void)count;
    free(records);
}
