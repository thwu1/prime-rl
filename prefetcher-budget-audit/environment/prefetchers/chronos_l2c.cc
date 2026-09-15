// ============================================================================
// Chronos: A Timing-Based Delta Prefetcher — L2C Cache Level
// DPC-3 Submission
//
// Implements a Signature Path Prefetcher with perceptron-based filtering.
// Storage Budget Annotations:
//   Each struct field's hardware bit-width is annotated in comments.
//   Array fields annotated "K bits each" or "K bits per weight" mean K bits
//   PER element. The [NUM_CPUS] array dimension is NOT part of the per-core
//   hardware storage budget.
// ============================================================================


#include "cache.h"
#include <cassert>
#include <cstdint>

// ==========================================
// CONFIGURATION CONSTANTS
// ==========================================

#define L2C_PAGE_BLOCKS_BITS 6
#define L2C_PAGE_BLOCKS (1 << L2C_PAGE_BLOCKS_BITS)
#define L2C_PAGE_OFFSET_MASK (L2C_PAGE_BLOCKS - 1)

#define L2C_SIG_BITS 12
#define L2C_SIG_MASK ((1 << L2C_SIG_BITS) - 1)
#define L2C_SIG_DELTA_BITS 7

#define L2C_MAX_PREFETCH_DEGREE 4
#define L2C_FILL_THRESHOLD 90
#define L2C_PF_THRESHOLD 25

// Per-invocation state (excluded from budget)
uint32_t l2c_cpu;

// ==========================================
// UTILITY FUNCTIONS
// ==========================================

uint64_t l2c_compute_signature(uint64_t old_sig, int delta) {
    uint64_t new_sig = old_sig;
    new_sig = ((new_sig << 3) ^ (delta & ((1 << L2C_SIG_DELTA_BITS) - 1))) & L2C_SIG_MASK;
    return new_sig;
}

// ==========================================
// SIGNATURE TABLE (ST)
// Maps page addresses to current signatures.
// ==========================================

#define L2C_ST_INDEX_BITS 9
#define L2C_ST_ENTRIES (1 << L2C_ST_INDEX_BITS)

typedef struct __l2c_st_entry {
    uint64_t tag;              // 16 bits
    uint64_t last_offset;      // 6 bits
    uint64_t signature;        // 12 bits
    uint64_t lru;              // 9 bits
} l2c_st_entry;

l2c_st_entry l2c_sig_table[NUM_CPUS][L2C_ST_ENTRIES];

void l2c_init_st() {
    for (int i = 0; i < L2C_ST_ENTRIES; i++) {
        l2c_sig_table[l2c_cpu][i].tag = 0;
        l2c_sig_table[l2c_cpu][i].last_offset = 0;
        l2c_sig_table[l2c_cpu][i].signature = 0;
        l2c_sig_table[l2c_cpu][i].lru = i;
    }
}

uint64_t l2c_find_st(uint64_t page_addr) {
    uint64_t tag = page_addr & ((1 << 16) - 1);
    for (int i = 0; i < L2C_ST_ENTRIES; i++) {
        if (l2c_sig_table[l2c_cpu][i].tag == tag) return i;
    }
    return L2C_ST_ENTRIES;
}

void l2c_update_lru_st(uint64_t index) {
    assert(index < L2C_ST_ENTRIES);
    for (int i = 0; i < L2C_ST_ENTRIES; i++) {
        if (l2c_sig_table[l2c_cpu][i].lru < l2c_sig_table[l2c_cpu][index].lru) {
            l2c_sig_table[l2c_cpu][i].lru++;
        }
    }
    l2c_sig_table[l2c_cpu][index].lru = 0;
}

// ==========================================
// PATTERN TABLE (PT)
// Records spatial access patterns indexed by signature.
// ==========================================

#define L2C_PT_INDEX_BITS 12
#define L2C_PT_ENTRIES (1 << L2C_PT_INDEX_BITS)

typedef struct __l2c_pt_entry {
    uint64_t spatial_pattern;  // 64 bits (bitmap of blocks accessed within page)
    unsigned confidence;       // 4 bits
} l2c_pt_entry;

l2c_pt_entry l2c_pattern_table[NUM_CPUS][L2C_PT_ENTRIES];

void l2c_init_pt() {
    for (int i = 0; i < L2C_PT_ENTRIES; i++) {
        l2c_pattern_table[l2c_cpu][i].spatial_pattern = 0;
        l2c_pattern_table[l2c_cpu][i].confidence = 0;
    }
}

void l2c_update_pt(uint64_t signature, uint64_t pattern) {
    uint64_t index = signature % L2C_PT_ENTRIES;
    if (l2c_pattern_table[l2c_cpu][index].confidence > 0) {
        l2c_pattern_table[l2c_cpu][index].spatial_pattern |= pattern;
        if (l2c_pattern_table[l2c_cpu][index].confidence < 15)
            l2c_pattern_table[l2c_cpu][index].confidence++;
    } else {
        l2c_pattern_table[l2c_cpu][index].spatial_pattern = pattern;
        l2c_pattern_table[l2c_cpu][index].confidence = 1;
    }
}

// ==========================================
// ACCUMULATION TABLE (ACCUM)
// Accumulates spatial patterns for pages currently being accessed.
// ==========================================

#define L2C_ACCUM_INDEX_BITS 7
#define L2C_ACCUM_ENTRIES ((1 << L2C_ACCUM_INDEX_BITS) + (1 << (L2C_ACCUM_INDEX_BITS - 2)))

typedef struct __l2c_accum_entry {
    uint64_t page_addr;        // 48 bits
    uint64_t spatial_pattern;  // 64 bits
    uint64_t last_offset;      // 6 bits
    uint64_t signature;        // 12 bits
    uint64_t lru;              // 8 bits
} l2c_accum_entry;

l2c_accum_entry l2c_accum_table[NUM_CPUS][L2C_ACCUM_ENTRIES];

void l2c_init_accum() {
    for (int i = 0; i < L2C_ACCUM_ENTRIES; i++) {
        l2c_accum_table[l2c_cpu][i].page_addr = 0;
        l2c_accum_table[l2c_cpu][i].spatial_pattern = 0;
        l2c_accum_table[l2c_cpu][i].lru = i;
    }
}

uint64_t l2c_find_accum(uint64_t page_addr) {
    for (int i = 0; i < L2C_ACCUM_ENTRIES; i++) {
        if (l2c_accum_table[l2c_cpu][i].page_addr == page_addr) return i;
    }
    return L2C_ACCUM_ENTRIES;
}

uint64_t l2c_get_lru_accum() {
    uint64_t lru = L2C_ACCUM_ENTRIES;
    for (int i = 0; i < L2C_ACCUM_ENTRIES; i++) {
        l2c_accum_table[l2c_cpu][i].lru++;
        if (l2c_accum_table[l2c_cpu][i].lru == L2C_ACCUM_ENTRIES) {
            l2c_accum_table[l2c_cpu][i].lru = 0;
            lru = i;
        }
    }
    return lru;
}

void l2c_evict_accum(uint64_t index) {
    if (l2c_accum_table[l2c_cpu][index].spatial_pattern) {
        l2c_update_pt(l2c_accum_table[l2c_cpu][index].signature,
                      l2c_accum_table[l2c_cpu][index].spatial_pattern);
    }
}

// ==========================================
// PREFETCH FILTER (PF)
// Filters redundant prefetch requests.
// ==========================================

#define L2C_PF_INDEX_BITS 10
#define L2C_PF_ENTRIES (1 << L2C_PF_INDEX_BITS)

typedef struct __l2c_pf_entry {
    uint64_t tag;              // 12 bits
    uint64_t useful;           // 2 bits
} l2c_pf_entry;

l2c_pf_entry l2c_prefetch_filter[NUM_CPUS][L2C_PF_ENTRIES];

void l2c_init_pf() {
    for (int i = 0; i < L2C_PF_ENTRIES; i++) {
        l2c_prefetch_filter[l2c_cpu][i].tag = 0;
        l2c_prefetch_filter[l2c_cpu][i].useful = 0;
    }
}

bool l2c_check_filter(uint64_t cl_addr) {
    uint64_t hash = cl_addr % L2C_PF_ENTRIES;
    uint64_t tag = (cl_addr >> L2C_PF_INDEX_BITS) & ((1 << 12) - 1);
    if (l2c_prefetch_filter[l2c_cpu][hash].tag == tag) {
        return true;
    }
    return false;
}

void l2c_add_filter(uint64_t cl_addr) {
    uint64_t hash = cl_addr % L2C_PF_ENTRIES;
    uint64_t tag = (cl_addr >> L2C_PF_INDEX_BITS) & ((1 << 12) - 1);
    l2c_prefetch_filter[l2c_cpu][hash].tag = tag;
    l2c_prefetch_filter[l2c_cpu][hash].useful = 0;
}

// ==========================================
// PERCEPTRON FILTER
// Filters low-confidence prefetch candidates.
// ==========================================

#define L2C_PERC_NUM_FEATURES 6
#define L2C_PERC_HASH_BITS 8
#define L2C_PERC_ENTRIES_PER_FEATURE (1 << L2C_PERC_HASH_BITS)
#define L2C_PERC_WEIGHT_BITS 6
#define L2C_PERC_WEIGHT_MAX ((1 << (L2C_PERC_WEIGHT_BITS - 1)) - 1)
#define L2C_PERC_WEIGHT_MIN (-(1 << (L2C_PERC_WEIGHT_BITS - 1)))

int8_t l2c_perc_weights[NUM_CPUS][L2C_PERC_NUM_FEATURES][L2C_PERC_ENTRIES_PER_FEATURE]; // 6 bits per weight

int32_t l2c_perc_threshold_counter[NUM_CPUS]; // 10 bits

void l2c_init_perc() {
    for (int f = 0; f < L2C_PERC_NUM_FEATURES; f++) {
        for (int e = 0; e < L2C_PERC_ENTRIES_PER_FEATURE; e++) {
            l2c_perc_weights[l2c_cpu][f][e] = 0;
        }
    }
    l2c_perc_threshold_counter[l2c_cpu] = 0;
}

uint64_t l2c_perc_hash(uint64_t feature_val, int feature_id) {
    return (feature_val ^ (feature_val >> L2C_PERC_HASH_BITS) ^ feature_id) %
           L2C_PERC_ENTRIES_PER_FEATURE;
}

int l2c_perc_predict(uint64_t ip, uint64_t addr, uint64_t page_addr,
                     uint64_t signature, uint64_t confidence, int delta) {
    int sum = 0;
    uint64_t features[L2C_PERC_NUM_FEATURES] = {
        ip, addr >> 6, page_addr, signature, confidence, (uint64_t)(delta & 0x7F)
    };
    for (int f = 0; f < L2C_PERC_NUM_FEATURES; f++) {
        uint64_t h = l2c_perc_hash(features[f], f);
        sum += l2c_perc_weights[l2c_cpu][f][h];
    }
    return sum;
}

void l2c_perc_update(uint64_t ip, uint64_t addr, uint64_t page_addr,
                     uint64_t signature, uint64_t confidence, int delta, bool correct) {
    uint64_t features[L2C_PERC_NUM_FEATURES] = {
        ip, addr >> 6, page_addr, signature, confidence, (uint64_t)(delta & 0x7F)
    };
    for (int f = 0; f < L2C_PERC_NUM_FEATURES; f++) {
        uint64_t h = l2c_perc_hash(features[f], f);
        if (correct) {
            if (l2c_perc_weights[l2c_cpu][f][h] < L2C_PERC_WEIGHT_MAX)
                l2c_perc_weights[l2c_cpu][f][h]++;
        } else {
            if (l2c_perc_weights[l2c_cpu][f][h] > L2C_PERC_WEIGHT_MIN)
                l2c_perc_weights[l2c_cpu][f][h]--;
        }
    }
}

// ==========================================
// DPC-3 INTERFACE
// ==========================================

void CACHE::l2c_prefetcher_initialize() {
    l2c_cpu = cpu;
    l2c_init_st();
    l2c_init_pt();
    l2c_init_accum();
    l2c_init_pf();
    l2c_init_perc();
}

void CACHE::l2c_prefetcher_operate(uint64_t addr, uint64_t ip,
                                    uint8_t cache_hit, uint8_t type) {
    l2c_cpu = cpu;
    uint64_t line_addr = addr >> LOG2_BLOCK_SIZE;
    uint64_t page_addr = line_addr >> L2C_PAGE_BLOCKS_BITS;
    uint64_t offset = line_addr & L2C_PAGE_OFFSET_MASK;

    // Update accumulation table
    uint64_t accum_idx = l2c_find_accum(page_addr);
    uint64_t old_sig = 0;
    int delta = 0;

    if (accum_idx < L2C_ACCUM_ENTRIES) {
        old_sig = l2c_accum_table[l2c_cpu][accum_idx].signature;
        delta = (int)offset - (int)l2c_accum_table[l2c_cpu][accum_idx].last_offset;
        l2c_accum_table[l2c_cpu][accum_idx].spatial_pattern |= ((uint64_t)1 << offset);
        l2c_accum_table[l2c_cpu][accum_idx].last_offset = offset;
        l2c_accum_table[l2c_cpu][accum_idx].signature = l2c_compute_signature(old_sig, delta);
    } else {
        accum_idx = l2c_get_lru_accum();
        l2c_evict_accum(accum_idx);
        l2c_accum_table[l2c_cpu][accum_idx].page_addr = page_addr;
        l2c_accum_table[l2c_cpu][accum_idx].spatial_pattern = (uint64_t)1 << offset;
        l2c_accum_table[l2c_cpu][accum_idx].last_offset = offset;

        // Check signature table
        uint64_t st_idx = l2c_find_st(page_addr);
        if (st_idx < L2C_ST_ENTRIES) {
            old_sig = l2c_sig_table[l2c_cpu][st_idx].signature;
            delta = (int)offset - (int)l2c_sig_table[l2c_cpu][st_idx].last_offset;
            l2c_accum_table[l2c_cpu][accum_idx].signature = l2c_compute_signature(old_sig, delta);
        } else {
            l2c_accum_table[l2c_cpu][accum_idx].signature = 0;
        }
    }

    // Generate prefetch candidates from pattern table
    uint64_t cur_sig = l2c_accum_table[l2c_cpu][accum_idx].signature;
    int pf_issued = 0;

    for (int depth = 0; depth < 3 && pf_issued < L2C_MAX_PREFETCH_DEGREE; depth++) {
        uint64_t pt_idx = cur_sig % L2C_PT_ENTRIES;
        uint64_t pattern = l2c_pattern_table[l2c_cpu][pt_idx].spatial_pattern;
        unsigned conf = l2c_pattern_table[l2c_cpu][pt_idx].confidence;

        if (conf == 0 || pattern == 0) break;

        for (int b = 0; b < L2C_PAGE_BLOCKS && pf_issued < L2C_MAX_PREFETCH_DEGREE; b++) {
            if (pattern & ((uint64_t)1 << b)) {
                uint64_t pf_addr = ((page_addr << L2C_PAGE_BLOCKS_BITS) + b) << LOG2_BLOCK_SIZE;
                if (!l2c_check_filter(pf_addr >> LOG2_BLOCK_SIZE)) {
                    int perc_score = l2c_perc_predict(ip, addr, page_addr, cur_sig, conf, delta);
                    if (perc_score >= 0) {
                        int fill_level = (conf > 8) ? FILL_L2 : FILL_LLC;
                        prefetch_line(ip, addr, pf_addr, fill_level, 0);
                        l2c_add_filter(pf_addr >> LOG2_BLOCK_SIZE);
                        pf_issued++;
                    }
                }
            }
        }

        // Follow signature path
        cur_sig = l2c_compute_signature(cur_sig, delta);
    }

    // Update signature table
    uint64_t st_idx = l2c_find_st(page_addr);
    if (st_idx < L2C_ST_ENTRIES) {
        l2c_sig_table[l2c_cpu][st_idx].last_offset = offset;
        l2c_sig_table[l2c_cpu][st_idx].signature = l2c_accum_table[l2c_cpu][accum_idx].signature;
        l2c_update_lru_st(st_idx);
    }
}

void CACHE::l2c_prefetcher_cache_fill(uint64_t addr, uint32_t set,
                                       uint32_t way, uint8_t prefetch,
                                       uint64_t evicted_addr) {
    l2c_cpu = cpu;
    if (prefetch) {
        uint64_t cl_addr = addr >> LOG2_BLOCK_SIZE;
        uint64_t hash = cl_addr % L2C_PF_ENTRIES;
        uint64_t tag = (cl_addr >> L2C_PF_INDEX_BITS) & ((1 << 12) - 1);
        if (l2c_prefetch_filter[l2c_cpu][hash].tag == tag) {
            l2c_prefetch_filter[l2c_cpu][hash].useful = 1;
        }
    }
}

void CACHE::l2c_prefetcher_final_stats() {
    // No final stats for L2C
}
