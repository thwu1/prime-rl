/*
 *
 * InChIKey generator header.
 */
#ifndef INCHIKEY_H
#define INCHIKEY_H

/*
 * Generate an InChIKey from an InChI string.
 *
 * inchi:    null-terminated InChI string (e.g., "InChI=1S/C2H6O/c1-2-3/h3H,2H2,1H3")
 * key_out:  output buffer, must be at least 28 bytes (27 chars + NUL)
 *
 * Returns 0 on success, non-zero on error.
 */
int generate_inchikey(const char *inchi, char *key_out);

#endif /* INCHIKEY_H */
