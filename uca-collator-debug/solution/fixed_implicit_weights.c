/*
 * Implicit collation element weight computation for the Unicode Collation Algorithm.
 *
 * Derives AAAA (primary weight of first CE) and BBBB (primary weight of second CE)
 * for code points that do not appear in the DUCET (allkeys.txt).
 *
 * Categories checked in order:
 *   1. Siniform ideographic scripts (via @implicitweights ranges)
 *   2. Core Han Unified Ideographs (U+4E00-U+9FFF + 12 compatibility ideographs)
 *   3. Other Han Unified Ideographs (CJK extensions A-I)
 *   4. All other / unassigned code points
 */

#include "implicit_weights.h"

static int is_core_han(uint32_t cp) {
    if (cp >= 0x4E00 && cp <= 0x9FFF) return 1;
    switch (cp) {
        case 0xFA0E: case 0xFA0F: case 0xFA11: case 0xFA13: case 0xFA14:
        case 0xFA1F: case 0xFA21: case 0xFA23: case 0xFA24:
        case 0xFA27: case 0xFA28: case 0xFA29:
            return 1;
        default:
            return 0;
    }
}

static int is_other_han(uint32_t cp) {
    return (cp >= 0x3400 && cp <= 0x4DBF) ||
           (cp >= 0x20000 && cp <= 0x2A6DF) ||
           (cp >= 0x2A700 && cp <= 0x2B739) ||
           (cp >= 0x2B740 && cp <= 0x2B81D) ||
           (cp >= 0x2B820 && cp <= 0x2CEA1) ||
           (cp >= 0x2CEB0 && cp <= 0x2EBE0) ||
           (cp >= 0x30000 && cp <= 0x3134A) ||
           (cp >= 0x31350 && cp <= 0x323AF);
}

ImplicitWeight compute_implicit_weight(uint32_t cp, int is_assigned,
                                        const ImplicitRange* ranges, int num_ranges) {
    ImplicitWeight result;

    /* Check siniform ideographic script ranges (@implicitweights) */
    if (is_assigned) {
        for (int i = 0; i < num_ranges; i++) {
            if (cp >= ranges[i].start && cp <= ranges[i].end) {
                result.aaaa = ranges[i].base;
                result.bbbb = (cp - ranges[i].start) | 0x8000;
                return result;
            }
        }
    }

    /* Core Han Unified Ideographs */
    if (is_assigned && is_core_han(cp)) {
        result.aaaa = 0xFB40 + (cp >> 15);
        result.bbbb = (cp & 0x7FFF) | 0x8000;
        return result;
    }

    /* Other Han Unified Ideographs (CJK extensions) */
    if (is_assigned && is_other_han(cp)) {
        result.aaaa = 0xFB80 + (cp >> 15);
        result.bbbb = (cp & 0x7FFF) | 0x8000;
        return result;
    }

    /* Unassigned and everything else */
    result.aaaa = 0xFBC0 + (cp >> 15);
    result.bbbb = (cp & 0x7FFF) | 0x8000;
    return result;
}
