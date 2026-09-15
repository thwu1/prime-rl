/*
 *
 * Duplicate molecule detector implementation.
 *
 * Uses an open-addressing hash table with linear probing to detect
 * duplicate InChIKeys in an SDF file.
 */

#include <stdlib.h>
#include <string.h>
#include "dedup.h"

dedup_table *dedup_create(int capacity)
{
    if (capacity <= 0) return NULL;

    dedup_table *table = malloc(sizeof(dedup_table));
    if (!table) return NULL;

    table->entries = calloc((size_t)capacity, sizeof(dedup_entry));
    if (!table->entries) { free(table); return NULL; }

    table->capacity = capacity;
    table->count = 0;
    return table;
}

int dedup_insert(dedup_table *table, const char *key, int record_index)
{
    /*
     * TODO: Implement open-addressing hash table insertion with
     * linear probing.
     *
     * Hash the key string to determine a starting slot index.
     * Probe linearly until finding either:
     *   - An occupied slot with matching key: return that slot's
     *     record_index (duplicate detected).
     *   - An unoccupied slot: store the key and record_index,
     *     mark as occupied, return -1 (new entry).
     * If all slots have been probed without a match or empty slot,
     * return -2 (table full).
     */
    (void)table;
    (void)key;
    (void)record_index;
    return -1;  /* Stub: always reports "no duplicate" */
}

void dedup_free(dedup_table *table)
{
    if (table) {
        free(table->entries);
        free(table);
    }
}
