/*
 *
 * Duplicate molecule detector using open-addressing hash table.
 */
#ifndef DEDUP_H
#define DEDUP_H

typedef struct {
    char key[28];       /* InChIKey (27 chars + NUL) */
    int  record_index;  /* Record number (0-based) of first occurrence */
    int  occupied;      /* 1 if this slot is in use, 0 otherwise */
} dedup_entry;

typedef struct {
    dedup_entry *entries;
    int capacity;
    int count;
} dedup_table;

/*
 * Create a dedup table with the given capacity.
 * Capacity should be at least 2x the expected number of entries.
 * Returns NULL on allocation failure.
 */
dedup_table *dedup_create(int capacity);

/*
 * Insert an InChIKey into the dedup table.
 *
 * table:        the dedup table
 * key:          27-character InChIKey string
 * record_index: 0-based index of the SDF record
 *
 * If the key is already in the table, returns the record_index of
 * the first occurrence (the duplicate's original).
 * If the key is new, inserts it and returns -1.
 * Returns -2 on error (table full or invalid input).
 */
int dedup_insert(dedup_table *table, const char *key, int record_index);

/*
 * Free a dedup table and all associated memory.
 */
void dedup_free(dedup_table *table);

#endif /* DEDUP_H */
