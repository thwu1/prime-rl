/*
 *
 * Complete MESI protocol implementation.
 */
#include "simulator.h"

void process_access(Simulator *sim, int proc_id, char op, uint64_t addr) {
    Cache *cache = &sim->caches[proc_id];
    int set_idx   = cache_set_index(cache, addr);
    uint64_t tag  = cache_tag(cache, addr);

    sim->cycle++;

    int way = cache_lookup(cache, set_idx, tag);

    if (op == 'R') {
        cache->reads++;

        if (way >= 0) {
            /* ── Read HIT (M, E, or S) ── no bus traffic ── */
            cache->read_hits++;
            cache_touch(cache, set_idx, way, sim->cycle);
        } else {
            /* ── Read MISS ── issue BusRd ── */
            cache->read_misses++;
            sim->bus_rd++;

            /* Snoop: determine what other caches hold */
            int has_m = 0, has_e = 0, has_s = 0;
            for (int p = 0; p < sim->num_procs; p++) {
                if (p == proc_id) continue;
                int ow = cache_lookup(&sim->caches[p], set_idx, tag);
                if (ow >= 0) {
                    LineState st = cache_get_state(&sim->caches[p], set_idx, ow);
                    if (st == STATE_MODIFIED)  has_m = 1;
                    if (st == STATE_EXCLUSIVE) has_e = 1;
                    if (st == STATE_SHARED)    has_s = 1;
                }
            }

            /* Snoop side-effects on other caches */
            if (has_m) {
                /* Other M cache flushes dirty data, transitions M→S */
                sim->flushes++;
                for (int p = 0; p < sim->num_procs; p++) {
                    if (p == proc_id) continue;
                    int ow = cache_lookup(&sim->caches[p], set_idx, tag);
                    if (ow >= 0 &&
                        cache_get_state(&sim->caches[p], set_idx, ow) == STATE_MODIFIED) {
                        cache_set_state(&sim->caches[p], set_idx, ow, STATE_SHARED);
                    }
                }
            }
            if (has_e) {
                /* Other E cache transitions E→S (no flush, data is clean) */
                for (int p = 0; p < sim->num_procs; p++) {
                    if (p == proc_id) continue;
                    int ow = cache_lookup(&sim->caches[p], set_idx, tag);
                    if (ow >= 0 &&
                        cache_get_state(&sim->caches[p], set_idx, ow) == STATE_EXCLUSIVE) {
                        cache_set_state(&sim->caches[p], set_idx, ow, STATE_SHARED);
                    }
                }
            }
            /* Caches in S stay in S — no action needed */

            /* New state: E if no other cache had it, S otherwise */
            LineState new_state = (has_m || has_e || has_s)
                                  ? STATE_SHARED : STATE_EXCLUSIVE;

            /* Eviction: pick LRU victim */
            int victim = cache_find_lru(cache, set_idx);
            if (cache_line_valid(cache, set_idx, victim) &&
                cache_get_state(cache, set_idx, victim) == STATE_MODIFIED) {
                sim->flushes++;          /* write-back dirty evictee */
            }

            cache_install(cache, set_idx, victim, tag, new_state, sim->cycle);
        }

    } else {  /* op == 'W' */
        cache->writes++;

        if (way >= 0) {
            /* ── Write HIT ── */
            cache->write_hits++;
            LineState st = cache_get_state(cache, set_idx, way);

            switch (st) {
            case STATE_MODIFIED:
                /* Already M — just write, no bus traffic */
                cache_touch(cache, set_idx, way, sim->cycle);
                break;

            case STATE_EXCLUSIVE:
                /* Silent upgrade E→M — no bus traffic (MESI advantage) */
                cache_set_state(cache, set_idx, way, STATE_MODIFIED);
                cache_touch(cache, set_idx, way, sim->cycle);
                break;

            case STATE_SHARED:
                /* Need BusUpgr to invalidate other S copies */
                sim->bus_upgr++;
                for (int p = 0; p < sim->num_procs; p++) {
                    if (p == proc_id) continue;
                    int ow = cache_lookup(&sim->caches[p], set_idx, tag);
                    if (ow >= 0) {
                        cache_set_state(&sim->caches[p], set_idx, ow,
                                        STATE_INVALID);
                    }
                }
                cache_set_state(cache, set_idx, way, STATE_MODIFIED);
                cache_touch(cache, set_idx, way, sim->cycle);
                break;

            default:
                break;
            }

        } else {
            /* ── Write MISS ── issue BusRdX ── */
            cache->write_misses++;
            sim->bus_rdx++;

            /* Snoop: flush any M copy, then invalidate ALL other copies */
            for (int p = 0; p < sim->num_procs; p++) {
                if (p == proc_id) continue;
                int ow = cache_lookup(&sim->caches[p], set_idx, tag);
                if (ow >= 0) {
                    if (cache_get_state(&sim->caches[p], set_idx, ow)
                        == STATE_MODIFIED) {
                        sim->flushes++;
                    }
                    cache_set_state(&sim->caches[p], set_idx, ow,
                                    STATE_INVALID);
                }
            }

            /* Eviction: pick LRU victim */
            int victim = cache_find_lru(cache, set_idx);
            if (cache_line_valid(cache, set_idx, victim) &&
                cache_get_state(cache, set_idx, victim) == STATE_MODIFIED) {
                sim->flushes++;          /* write-back dirty evictee */
            }

            cache_install(cache, set_idx, victim, tag, STATE_MODIFIED,
                          sim->cycle);
        }
    }
}
