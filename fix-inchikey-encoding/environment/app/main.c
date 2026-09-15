/*
 *
 * InChIKey generator - command-line driver.
 *
 * Reads InChI strings from stdin (one per line), outputs the
 * corresponding InChIKey to stdout (one per line).
 */

#include <stdio.h>
#include <string.h>
#include "inchikey.h"

int main(void)
{
    char line[8192];
    char key[28];

    while (fgets(line, sizeof(line), stdin)) {
        /* Strip trailing newline / carriage return */
        size_t len = strlen(line);
        while (len > 0 && (line[len-1] == '\n' || line[len-1] == '\r'))
            line[--len] = '\0';

        if (len == 0) continue;
        if (line[0] == '#') continue;  /* skip comments */

        if (generate_inchikey(line, key) != 0) {
            fprintf(stderr, "Error processing: %s\n", line);
            return 1;
        }

        printf("%s\n", key);
    }

    return 0;
}
