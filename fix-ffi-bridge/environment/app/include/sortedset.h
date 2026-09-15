#ifndef SORTEDSET_H
#define SORTEDSET_H

#include <stddef.h>
#include <stdint.h>

/* Opaque sorted set handle. All functions are thread-safe:
 * multiple threads may operate on the same SortedSet* concurrently. */
typedef struct SortedSet SortedSet;

/* Result of a range query.
 * The caller MUST call zset_range_free() when done. */
typedef struct ZRangeResult {
    size_t count;        /* Number of entries */
    char** members;      /* Array of null-terminated member strings */
    double* scores;      /* Array of scores, parallel to members */
} ZRangeResult;

/* Callback for iteration over sorted set members.
 * member: null-terminated UTF-8 string (valid only during callback invocation)
 * score:  the member's score
 * user_data: opaque pointer passed through from zset_foreach
 * Return 0 to continue iteration, non-zero to stop early. */
typedef int (*zset_iter_callback)(const char* member, double score, void* user_data);

/* Create a new empty sorted set. Returns NULL on allocation failure. */
SortedSet* zset_new(void);

/* Free a sorted set and all its contents. NULL-safe. */
void zset_free(SortedSet* zs);

/* Create a deep copy of a sorted set. Returns NULL on failure.
 * The clone is fully independent of the original. */
SortedSet* zset_clone(const SortedSet* zs);

/* Add a member with the given score. Updates score if member exists.
 * Returns 1 if newly added, 0 if updated, -1 on error. */
int32_t zset_add(SortedSet* zs, const char* member, double score);

/* Remove a member. Returns 1 if removed, 0 if not found, -1 on error. */
int32_t zset_remove(SortedSet* zs, const char* member);

/* Get the score of a member. Returns 1 if found (writes score to *out_score),
 * 0 if not found. */
int32_t zset_score(const SortedSet* zs, const char* member, double* out_score);

/* Return the number of members. */
size_t zset_card(const SortedSet* zs);

/* Get the 0-based rank (position in score-ascending order) of a member.
 * Returns 1 if found (writes rank to *out_rank), 0 if not found. */
int32_t zset_rank(const SortedSet* zs, const char* member, size_t* out_rank);

/* Return all members with min <= score <= max, in ascending score order.
 * Caller must call zset_range_free() on the result. Returns NULL on error. */
ZRangeResult* zset_range_by_score(const SortedSet* zs, double min, double max);

/* Return members at rank positions [start, stop] (0-based, inclusive),
 * in ascending score order.
 * Caller must call zset_range_free() on the result. Returns NULL on error. */
ZRangeResult* zset_range_by_rank(const SortedSet* zs, size_t start, size_t stop);

/* Free a range result returned by zset_range_by_score or zset_range_by_rank.
 * NULL-safe. */
void zset_range_free(ZRangeResult* result);

/* Iterate over all members in score-ascending order, calling cb for each.
 * Stops early if cb returns non-zero.
 * Returns the number of members visited.
 * The member string passed to cb is valid only during the callback invocation. */
size_t zset_foreach(const SortedSet* zs, zset_iter_callback cb, void* user_data);

#endif /* SORTEDSET_H */
