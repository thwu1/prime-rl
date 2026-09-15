// ============================================================================
// Chronos: A Timing-Based Delta Prefetcher — LLC Cache Level
// DPC-3 Submission
//
// Implements a stream detector combined with region-based spatial tracking.
// Storage Budget Annotations:
//   Each struct field's hardware bit-width is annotated in comments.
//   The [NUM_CPUS] array dimension is NOT part of the per-core storage budget.
// ============================================================================


#include "cache.h"
#include <cassert>
#include <cstdint>

// ==========================================
// CONFIGURATION CONSTANTS
// ==========================================

#define LLC_PAGE_BLOCKS_BITS 6
#define LLC_PAGE_BLOCKS (1 << LLC_PAGE_BLOCKS_BITS)
#define LLC_PAGE_OFFSET_MASK (LLC_PAGE_BLOCKS - 1)

#define LLC_REGION_SIZE_BITS 10
#define LLC_REGION_SIZE (1 << LLC_REGION_SIZE_BITS)
#define LLC_REGION_OFFSET_MASK (LLC_REGION_SIZE - 1)

#define LLC_MAX_PREFETCH_DEGREE 2
#define LLC_STREAM_DISTANCE 4
#define LLC_CONFIDENCE_THRESHOLD 2

// Per-invocation state (excluded from budget)
uint32_t llc_cpu;

// ==========================================
// STREAM TRACKER TABLE
// Detects streaming access patterns (ascending/descending).
// ==========================================

#define LLC_STREAM_INDEX_BITS 6
#define LLC_STREAM_ENTRIES (1 << LLC_STREAM_INDEX_BITS)

typedef struct __llc_stream_entry {
    uint64_t region_addr;      // 42 bits (physical region address)
    uint64_t offset;           // 6 bits (last accessed offset within region)
    uint64_t direction;        // 1 bit (0 = ascending, 1 = descending)
    unsigned confidence;       // 3 bits
    bool active;               // 1 bit
    uint64_t lru;              // 6 bits
} llc_stream_entry;

llc_stream_entry llc_stream_table[NUM_CPUS][LLC_STREAM_ENTRIES];

void llc_init_stream() {
    for (int i = 0; i < LLC_STREAM_ENTRIES; i++) {
        llc_stream_table[llc_cpu][i].region_addr = 0;
        llc_stream_table[llc_cpu][i].offset = 0;
        llc_stream_table[llc_cpu][i].direction = 0;
        llc_stream_table[llc_cpu][i].confidence = 0;
        llc_stream_table[llc_cpu][i].active = false;
        llc_stream_table[llc_cpu][i].lru = i;
    }
}

uint64_t llc_find_stream(uint64_t region_addr) {
    for (int i = 0; i < LLC_STREAM_ENTRIES; i++) {
        if (llc_stream_table[llc_cpu][i].active &&
            llc_stream_table[llc_cpu][i].region_addr == region_addr) return i;
    }
    return LLC_STREAM_ENTRIES;
}

void llc_update_lru_stream(uint64_t index) {
    assert(index < LLC_STREAM_ENTRIES);
    for (int i = 0; i < LLC_STREAM_ENTRIES; i++) {
        if (llc_stream_table[llc_cpu][i].lru < llc_stream_table[llc_cpu][index].lru) {
            llc_stream_table[llc_cpu][i].lru++;
        }
    }
    llc_stream_table[llc_cpu][index].lru = 0;
}

uint64_t llc_get_lru_stream() {
    uint64_t lru = LLC_STREAM_ENTRIES;
    for (int i = 0; i < LLC_STREAM_ENTRIES; i++) {
        llc_stream_table[llc_cpu][i].lru++;
        if (llc_stream_table[llc_cpu][i].lru == LLC_STREAM_ENTRIES) {
            llc_stream_table[llc_cpu][i].lru = 0;
            lru = i;
        }
    }
    assert(lru != LLC_STREAM_ENTRIES);
    return lru;
}

// ==========================================
// REGION BITMAP TABLE
// Tracks spatial access patterns within memory regions.
// ==========================================

#define LLC_REGION_ENTRIES ((1 << 9) - (1 << 3))

typedef struct __llc_region_entry {
    uint64_t tag;              // 32 bits (truncated region tag)
    uint64_t access_bitmap;    // 64 bits (one bit per block in region)
    uint64_t lru;              // 9 bits
} llc_region_entry;

llc_region_entry llc_region_table[NUM_CPUS][LLC_REGION_ENTRIES];

void llc_init_region() {
    for (int i = 0; i < LLC_REGION_ENTRIES; i++) {
        llc_region_table[llc_cpu][i].tag = 0;
        llc_region_table[llc_cpu][i].access_bitmap = 0;
        llc_region_table[llc_cpu][i].lru = i;
    }
}

uint64_t llc_find_region(uint64_t region_tag) {
    uint64_t trunc_tag = region_tag & ((uint64_t)((1ULL << 32) - 1));
    for (int i = 0; i < LLC_REGION_ENTRIES; i++) {
        if (llc_region_table[llc_cpu][i].tag == trunc_tag &&
            llc_region_table[llc_cpu][i].access_bitmap != 0) return i;
    }
    return LLC_REGION_ENTRIES;
}

void llc_update_lru_region(uint64_t index) {
    assert(index < LLC_REGION_ENTRIES);
    for (int i = 0; i < LLC_REGION_ENTRIES; i++) {
        if (llc_region_table[llc_cpu][i].lru < llc_region_table[llc_cpu][index].lru) {
            llc_region_table[llc_cpu][i].lru++;
        }
    }
    llc_region_table[llc_cpu][index].lru = 0;
}

uint64_t llc_get_lru_region() {
    uint64_t lru = LLC_REGION_ENTRIES;
    for (int i = 0; i < LLC_REGION_ENTRIES; i++) {
        llc_region_table[llc_cpu][i].lru++;
        if (llc_region_table[llc_cpu][i].lru == LLC_REGION_ENTRIES) {
            llc_region_table[llc_cpu][i].lru = 0;
            lru = i;
        }
    }
    assert(lru != LLC_REGION_ENTRIES);
    return lru;
}

// ==========================================
// DPC-3 INTERFACE
// ==========================================

void CACHE::llc_prefetcher_initialize() {
    llc_cpu = cpu;
    llc_init_stream();
    llc_init_region();
}

void CACHE::llc_prefetcher_operate(uint64_t addr, uint64_t ip,
                                    uint8_t cache_hit, uint8_t type) {
    llc_cpu = cpu;
    uint64_t line_addr = addr >> LOG2_BLOCK_SIZE;
    uint64_t page_addr = line_addr >> LLC_PAGE_BLOCKS_BITS;
    uint64_t page_offset = line_addr & LLC_PAGE_OFFSET_MASK;

    uint64_t region_addr = line_addr >> LLC_REGION_SIZE_BITS;
    uint64_t region_offset = line_addr & LLC_REGION_OFFSET_MASK;
    uint64_t region_tag = region_addr;

    // Update region bitmap
    uint64_t reg_idx = llc_find_region(region_tag);
    if (reg_idx < LLC_REGION_ENTRIES) {
        llc_region_table[llc_cpu][reg_idx].access_bitmap |= ((uint64_t)1 << (region_offset & 63));
        llc_update_lru_region(reg_idx);
    } else {
        reg_idx = llc_get_lru_region();
        llc_region_table[llc_cpu][reg_idx].tag = region_tag & ((uint64_t)((1ULL << 32) - 1));
        llc_region_table[llc_cpu][reg_idx].access_bitmap = (uint64_t)1 << (region_offset & 63);
        llc_update_lru_region(reg_idx);
    }

    // Stream detection
    uint64_t stream_idx = llc_find_stream(region_addr);
    if (stream_idx < LLC_STREAM_ENTRIES) {
        uint64_t prev_offset = llc_stream_table[llc_cpu][stream_idx].offset;
        bool ascending = (page_offset > prev_offset);
        bool cur_dir = llc_stream_table[llc_cpu][stream_idx].direction;

        if ((ascending && !cur_dir) || (!ascending && cur_dir)) {
            if (llc_stream_table[llc_cpu][stream_idx].confidence < 7)
                llc_stream_table[llc_cpu][stream_idx].confidence++;
        } else {
            if (llc_stream_table[llc_cpu][stream_idx].confidence > 0)
                llc_stream_table[llc_cpu][stream_idx].confidence--;
            else
                llc_stream_table[llc_cpu][stream_idx].direction = ascending ? 0 : 1;
        }
        llc_stream_table[llc_cpu][stream_idx].offset = page_offset;
        llc_update_lru_stream(stream_idx);

        // Issue stream prefetches if confident
        if (llc_stream_table[llc_cpu][stream_idx].confidence >= LLC_CONFIDENCE_THRESHOLD) {
            int dir = llc_stream_table[llc_cpu][stream_idx].direction ? -1 : 1;
            for (int d = 1; d <= LLC_STREAM_DISTANCE && d <= LLC_MAX_PREFETCH_DEGREE; d++) {
                int target = (int)page_offset + dir * d;
                if (target >= 0 && target < LLC_PAGE_BLOCKS) {
                    uint64_t pf_addr = ((page_addr << LLC_PAGE_BLOCKS_BITS) + target) << LOG2_BLOCK_SIZE;
                    prefetch_line(ip, addr, pf_addr, FILL_LLC, 0);
                }
            }
        }
    } else {
        // Allocate new stream entry
        stream_idx = llc_get_lru_stream();
        llc_stream_table[llc_cpu][stream_idx].region_addr = region_addr;
        llc_stream_table[llc_cpu][stream_idx].offset = page_offset;
        llc_stream_table[llc_cpu][stream_idx].direction = 0;
        llc_stream_table[llc_cpu][stream_idx].confidence = 0;
        llc_stream_table[llc_cpu][stream_idx].active = true;
        llc_update_lru_stream(stream_idx);
    }
}

void CACHE::llc_prefetcher_cache_fill(uint64_t addr, uint32_t set,
                                       uint32_t way, uint8_t prefetch,
                                       uint64_t evicted_addr) {
    llc_cpu = cpu;
    // No action on fill for LLC prefetcher
}

void CACHE::llc_prefetcher_final_stats() {
    // No final stats for LLC
}
