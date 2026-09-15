/*
 *
 * SDF file parser header.
 *
 * Parses V2000 SDF (Structure Data Format) files and extracts molecule
 * names and InChI annotations from the data block.
 */
#ifndef SDF_PARSER_H
#define SDF_PARSER_H

#define SDF_MAX_NAME  256
#define SDF_MAX_INCHI 2048

typedef struct {
    char name[SDF_MAX_NAME];
    char inchi[SDF_MAX_INCHI];
} sdf_record;

/*
 * Parse an SDF file and extract molecule names and InChI annotations.
 *
 * filename:    path to the SDF file
 * records_out: pointer to receive the allocated array of records
 * count_out:   pointer to receive the number of records
 *
 * Returns 0 on success, non-zero on error.
 * Caller must free the records with sdf_free_records().
 */
int sdf_parse_file(const char *filename, sdf_record **records_out, int *count_out);

/*
 * Free an array of SDF records allocated by sdf_parse_file().
 */
void sdf_free_records(sdf_record *records, int count);

#endif /* SDF_PARSER_H */
