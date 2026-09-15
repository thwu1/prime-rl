#ifndef IMPLICIT_WEIGHTS_H
#define IMPLICIT_WEIGHTS_H

#include <stdint.h>

typedef struct {
    uint32_t aaaa;
    uint32_t bbbb;
} ImplicitWeight;

typedef struct {
    uint32_t start;
    uint32_t end;
    uint32_t base;
} ImplicitRange;

/**
 * Compute implicit collation element weights for a code point not in the DUCET.
 *
 * @param cp          The Unicode code point
 * @param is_assigned 1 if the code point has a General_Category other than Cn, 0 otherwise
 * @param ranges      Array of @implicitweights ranges from allkeys.txt
 * @param num_ranges  Number of elements in the ranges array
 * @return            ImplicitWeight with AAAA (primary) and BBBB (secondary CE primary)
 */
ImplicitWeight compute_implicit_weight(uint32_t cp, int is_assigned,
                                        const ImplicitRange* ranges, int num_ranges);

#endif /* IMPLICIT_WEIGHTS_H */
