#include "zset.h"
#include "common.h"
#include <stdlib.h>

// TODO: Implement sorted set operations.
// See zset.h for the API declarations and documentation.

bool zset_insert(ZSet *, const char *, size_t, double) {
    abort();    // not implemented
}

ZNode *zset_lookup(ZSet *, const char *, size_t) {
    abort();    // not implemented
}

void zset_delete(ZSet *, ZNode *) {
    abort();    // not implemented
}

ZNode *zset_seekge(ZSet *, double, const char *, size_t) {
    abort();    // not implemented
}

void zset_clear(ZSet *) {
    abort();    // not implemented
}

ZNode *znode_offset(ZNode *, int64_t) {
    abort();    // not implemented
}
