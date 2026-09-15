// ============================================================================
// Chronos: A Timing-Based Delta Prefetcher — L1D Cache Level
// DPC-3 Submission
//
// Storage Budget Annotations:
//   Each struct field's hardware bit-width is annotated in comments.
//   Array fields annotated "K bits each" mean K bits PER element.
//   The [NUM_CPUS] array dimension exists only for multi-core simulation
//   and is NOT part of the per-core hardware storage budget.
// ============================================================================


#include "cache.h"
#include <cassert>
#include <cstdint>

// ==========================================
// CONFIGURATION CONSTANTS
// ==========================================

#define L1D_PAGE_BLOCKS_BITS (LOG2_PAGE_SIZE - LOG2_BLOCK_SIZE)
#define L1D_PAGE_BLOCKS (1 << L1D_PAGE_BLOCKS_BITS)
#define L1D_PAGE_OFFSET_MASK (L1D_PAGE_BLOCKS - 1)

#define L1D_MAX_BURST_PREFETCHES 3
#define L1D_DELTA_CONFIDENCE_THRESHOLD 2

#define L1D_TIME_BITS 16
#define L1D_TIME_OVERFLOW ((uint64_t)1 << L1D_TIME_BITS)
#define L1D_TIME_MASK (L1D_TIME_OVERFLOW - 1)

// Per-invocation CPU ID (not persistent state, excluded from budget)
uint32_t l1d_cpu;

// ==========================================
// UTILITY FUNCTIONS
// ==========================================

uint64_t l1d_compute_latency(uint64_t now, uint64_t before) {
    uint64_t now_masked = now & L1D_TIME_MASK;
    uint64_t before_masked = before & L1D_TIME_MASK;
    if (before_masked > now_masked) {
        return (now_masked + L1D_TIME_OVERFLOW) - before_masked;
    }
    return now_masked - before_masked;
}

int l1d_compute_delta(uint64_t prev_off, uint64_t curr_off) {
    int delta;
    if (curr_off > prev_off) {
        delta = curr_off - prev_off;
    } else {
        delta = -(int)(prev_off - curr_off);
    }
    return delta;
}

// ==========================================
// ACTIVE PAGE TABLE (APT)
// Tracks pages currently being accessed.
// ==========================================

#define L1D_APT_INDEX_BITS 7
#define L1D_APT_ENTRIES ((1 << L1D_APT_INDEX_BITS) - 1)
#define L1D_APT_NUM_DELTAS 12
#define L1D_APT_DELTAS_PER_ACCESS 8

typedef struct __l1d_apt_entry {
    uint64_t page_addr;                            // 52 bits
    uint64_t ip_tag;                               // 10 bits
    uint64_t access_bitmap;                        // 64 bits
    uint64_t first_offset;                         // 6 bits
    int deltas[L1D_APT_NUM_DELTAS];                // 7 bits each
    unsigned delta_scores[L1D_APT_NUM_DELTAS];     // 5 bits each
    uint64_t last_pf_offset;                       // 6 bits
    uint64_t lru;                                  // 7 bits
} l1d_apt_entry;

l1d_apt_entry l1d_active_page_table[NUM_CPUS][L1D_APT_ENTRIES];

void l1d_init_apt() {
    for (int i = 0; i < L1D_APT_ENTRIES; i++) {
        l1d_active_page_table[l1d_cpu][i].page_addr = 0;
        l1d_active_page_table[l1d_cpu][i].ip_tag = 0;
        l1d_active_page_table[l1d_cpu][i].access_bitmap = 0;
        l1d_active_page_table[l1d_cpu][i].last_pf_offset = 0;
        l1d_active_page_table[l1d_cpu][i].lru = i;
    }
}

uint64_t l1d_get_apt_entry(uint64_t page_addr) {
    for (int i = 0; i < L1D_APT_ENTRIES; i++) {
        if (l1d_active_page_table[l1d_cpu][i].page_addr == page_addr) return i;
    }
    return L1D_APT_ENTRIES;
}

void l1d_update_lru_apt(uint64_t index) {
    assert(index < L1D_APT_ENTRIES);
    for (int i = 0; i < L1D_APT_ENTRIES; i++) {
        if (l1d_active_page_table[l1d_cpu][i].lru < l1d_active_page_table[l1d_cpu][index].lru) {
            l1d_active_page_table[l1d_cpu][i].lru++;
        }
    }
    l1d_active_page_table[l1d_cpu][index].lru = 0;
}

uint64_t l1d_get_lru_apt_entry() {
    uint64_t lru = L1D_APT_ENTRIES;
    for (int i = 0; i < L1D_APT_ENTRIES; i++) {
        l1d_active_page_table[l1d_cpu][i].lru++;
        if (l1d_active_page_table[l1d_cpu][i].lru == L1D_APT_ENTRIES) {
            l1d_active_page_table[l1d_cpu][i].lru = 0;
            lru = i;
        }
    }
    assert(lru != L1D_APT_ENTRIES);
    return lru;
}

int l1d_get_best_delta(uint64_t index, uint64_t &confidence) {
    assert(index < L1D_APT_ENTRIES);
    uint64_t max_score = 0;
    int best = 0;
    for (int i = 0; i < L1D_APT_NUM_DELTAS; i++) {
        uint64_t score = l1d_active_page_table[l1d_cpu][index].delta_scores[i];
        if (score > max_score) {
            best = l1d_active_page_table[l1d_cpu][index].deltas[i];
            max_score = score;
            confidence = score;
        }
    }
    return best;
}

void l1d_add_delta(uint64_t index, int delta) {
    assert(delta != 0);
    assert(index < L1D_APT_ENTRIES);
    for (int i = 0; i < L1D_APT_NUM_DELTAS; i++) {
        if (l1d_active_page_table[l1d_cpu][index].delta_scores[i] == 0) {
            l1d_active_page_table[l1d_cpu][index].deltas[i] = delta;
            l1d_active_page_table[l1d_cpu][index].delta_scores[i] = 1;
            break;
        } else if (l1d_active_page_table[l1d_cpu][index].deltas[i] == delta) {
            l1d_active_page_table[l1d_cpu][index].delta_scores[i]++;
            break;
        }
    }
    l1d_update_lru_apt(index);
}

bool l1d_offset_requested(uint64_t index, uint64_t offset) {
    assert(index < L1D_APT_ENTRIES);
    return l1d_active_page_table[l1d_cpu][index].access_bitmap & ((uint64_t)1 << offset);
}

// ==========================================
// HISTORY BUFFER (HB)
// Circular buffer recording recent demand requests.
// ==========================================

#define L1D_HB_INDEX_BITS 10
#define L1D_HB_ENTRIES (1 << L1D_HB_INDEX_BITS)
#define L1D_HB_MASK (L1D_HB_ENTRIES - 1)
#define L1D_HB_NULL_PTR L1D_APT_ENTRIES

typedef struct __l1d_hb_entry {
    uint64_t apt_pointer;      // 7 bits
    uint64_t offset;           // 6 bits
    uint64_t timestamp;        // 16 bits
} l1d_hb_entry;

l1d_hb_entry l1d_history_buffer[NUM_CPUS][L1D_HB_ENTRIES];
uint64_t l1d_hb_head[NUM_CPUS];   // 10 bits (circular buffer head)

void l1d_init_hb() {
    l1d_hb_head[l1d_cpu] = 0;
    for (int i = 0; i < L1D_HB_ENTRIES; i++) {
        l1d_history_buffer[l1d_cpu][i].apt_pointer = L1D_HB_NULL_PTR;
    }
}

uint64_t l1d_find_hb_entry(uint64_t pointer, uint64_t offset) {
    for (int i = 0; i < L1D_HB_ENTRIES; i++) {
        if (l1d_history_buffer[l1d_cpu][i].apt_pointer == pointer &&
            l1d_history_buffer[l1d_cpu][i].offset == offset) return i;
    }
    return L1D_HB_ENTRIES;
}

void l1d_add_hb(uint64_t pointer, uint64_t offset, uint64_t cycle) {
    if (l1d_find_hb_entry(pointer, offset) != L1D_HB_ENTRIES) return;
    l1d_history_buffer[l1d_cpu][l1d_hb_head[l1d_cpu]].apt_pointer = pointer;
    l1d_history_buffer[l1d_cpu][l1d_hb_head[l1d_cpu]].offset = offset;
    l1d_history_buffer[l1d_cpu][l1d_hb_head[l1d_cpu]].timestamp = cycle & L1D_TIME_MASK;
    l1d_hb_head[l1d_cpu] = (l1d_hb_head[l1d_cpu] + 1) & L1D_HB_MASK;
}

uint64_t l1d_get_latency_hb(uint64_t pointer, uint64_t offset, uint64_t cycle) {
    uint64_t index = l1d_find_hb_entry(pointer, offset);
    if (index == L1D_HB_ENTRIES) return 0;
    return l1d_compute_latency(cycle, l1d_history_buffer[l1d_cpu][index].timestamp);
}

void l1d_get_deltas_from_hb(uint64_t pointer, uint64_t offset, uint64_t cycle, int *out_deltas) {
    int pos = 0;
    uint64_t extra_time = 0;
    uint64_t last_ts = l1d_history_buffer[l1d_cpu][(l1d_hb_head[l1d_cpu] + L1D_HB_MASK) & L1D_HB_MASK].timestamp;
    for (uint64_t i = (l1d_hb_head[l1d_cpu] + L1D_HB_MASK) & L1D_HB_MASK;
         i != l1d_hb_head[l1d_cpu];
         i = (i + L1D_HB_MASK) & L1D_HB_MASK) {
        if (last_ts < l1d_history_buffer[l1d_cpu][i].timestamp) {
            extra_time = L1D_TIME_OVERFLOW;
        }
        last_ts = l1d_history_buffer[l1d_cpu][i].timestamp;
        if (l1d_history_buffer[l1d_cpu][i].apt_pointer == pointer) {
            if (l1d_history_buffer[l1d_cpu][i].timestamp <= (cycle & L1D_TIME_MASK) + extra_time) {
                out_deltas[pos] = l1d_compute_delta(l1d_history_buffer[l1d_cpu][i].offset, offset);
                pos++;
                if (pos == L1D_APT_DELTAS_PER_ACCESS) return;
            }
        }
    }
    out_deltas[pos] = 0;
}

// ==========================================
// PENDING PREFETCH TABLE (PP)
// Circular buffer tracking outstanding prefetches.
// ==========================================

#define L1D_PP_INDEX_BITS 9
#define L1D_PP_ENTRIES (1 << L1D_PP_INDEX_BITS)
#define L1D_PP_MASK (L1D_PP_ENTRIES - 1)

typedef struct __l1d_pp_entry {
    uint64_t apt_pointer;      // 7 bits
    uint64_t offset;           // 6 bits
    uint64_t issue_cycle;      // 16 bits
    bool fulfilled;            // 1 bit
} l1d_pp_entry;

l1d_pp_entry l1d_pending_prefetch[NUM_CPUS][L1D_PP_ENTRIES];
uint64_t l1d_pp_head[NUM_CPUS];   // 9 bits (circular buffer head)

void l1d_init_pp() {
    l1d_pp_head[l1d_cpu] = 0;
    for (int i = 0; i < L1D_PP_ENTRIES; i++) {
        l1d_pending_prefetch[l1d_cpu][i].apt_pointer = L1D_HB_NULL_PTR;
    }
}

uint64_t l1d_find_pp_entry(uint64_t pointer, uint64_t offset) {
    for (int i = 0; i < L1D_PP_ENTRIES; i++) {
        if (l1d_pending_prefetch[l1d_cpu][i].apt_pointer == pointer &&
            l1d_pending_prefetch[l1d_cpu][i].offset == offset) return i;
    }
    return L1D_PP_ENTRIES;
}

void l1d_add_pp(uint64_t pointer, uint64_t offset, uint64_t cycle) {
    if (l1d_find_pp_entry(pointer, offset) != L1D_PP_ENTRIES) return;
    l1d_pending_prefetch[l1d_cpu][l1d_pp_head[l1d_cpu]].apt_pointer = pointer;
    l1d_pending_prefetch[l1d_cpu][l1d_pp_head[l1d_cpu]].offset = offset;
    l1d_pending_prefetch[l1d_cpu][l1d_pp_head[l1d_cpu]].issue_cycle = cycle & L1D_TIME_MASK;
    l1d_pending_prefetch[l1d_cpu][l1d_pp_head[l1d_cpu]].fulfilled = false;
    l1d_pp_head[l1d_cpu] = (l1d_pp_head[l1d_cpu] + 1) & L1D_PP_MASK;
}

uint64_t l1d_get_pf_latency(uint64_t pointer, uint64_t offset, uint64_t cycle) {
    uint64_t index = l1d_find_pp_entry(pointer, offset);
    if (index == L1D_PP_ENTRIES) return 0;
    if (!l1d_pending_prefetch[l1d_cpu][index].fulfilled) {
        l1d_pending_prefetch[l1d_cpu][index].issue_cycle =
            l1d_compute_latency(cycle, l1d_pending_prefetch[l1d_cpu][index].issue_cycle);
        l1d_pending_prefetch[l1d_cpu][index].fulfilled = true;
    }
    return l1d_pending_prefetch[l1d_cpu][index].issue_cycle;
}

// ==========================================
// ARCHIVE TABLE (AT)
// Long-term page access history for prediction.
// ==========================================

#define L1D_AT_ENTRIES (((1 << 10) + (1 << 8) + (1 << 6)) - 1)
#define L1D_TRUNC_ADDR_BITS 32
#define L1D_TRUNC_ADDR_MASK (((uint64_t)1 << L1D_TRUNC_ADDR_BITS) - 1)

typedef struct __l1d_at_entry {
    uint64_t page_addr;        // 32 bits (truncated physical page address)
    uint64_t access_bitmap;    // 64 bits
    uint64_t first_offset;     // 6 bits
    int best_delta;            // 7 bits
    uint64_t lru;              // 11 bits
} l1d_at_entry;

l1d_at_entry l1d_archive_table[NUM_CPUS][L1D_AT_ENTRIES];

void l1d_init_at() {
    for (int i = 0; i < L1D_AT_ENTRIES; i++) {
        l1d_archive_table[l1d_cpu][i].page_addr = 0;
        l1d_archive_table[l1d_cpu][i].access_bitmap = 0;
        l1d_archive_table[l1d_cpu][i].lru = i;
    }
}

uint64_t l1d_get_lru_at_entry() {
    uint64_t lru = L1D_AT_ENTRIES;
    for (int i = 0; i < L1D_AT_ENTRIES; i++) {
        l1d_archive_table[l1d_cpu][i].lru++;
        if (l1d_archive_table[l1d_cpu][i].lru == L1D_AT_ENTRIES) {
            l1d_archive_table[l1d_cpu][i].lru = 0;
            lru = i;
        }
    }
    assert(lru != L1D_AT_ENTRIES);
    return lru;
}

void l1d_update_lru_at(uint64_t index) {
    assert(index < L1D_AT_ENTRIES);
    for (int i = 0; i < L1D_AT_ENTRIES; i++) {
        if (l1d_archive_table[l1d_cpu][i].lru < l1d_archive_table[l1d_cpu][index].lru) {
            l1d_archive_table[l1d_cpu][i].lru++;
        }
    }
    l1d_archive_table[l1d_cpu][index].lru = 0;
}

void l1d_add_at(uint64_t index, uint64_t page_addr, uint64_t bitmap,
                uint64_t first_off, int delta) {
    assert(index < L1D_AT_ENTRIES);
    l1d_archive_table[l1d_cpu][index].page_addr = page_addr & L1D_TRUNC_ADDR_MASK;
    l1d_archive_table[l1d_cpu][index].access_bitmap = bitmap;
    l1d_archive_table[l1d_cpu][index].first_offset = first_off;
    l1d_archive_table[l1d_cpu][index].best_delta = delta;
    l1d_update_lru_at(index);
}

uint64_t l1d_find_at_entry(uint64_t page_addr, uint64_t first_offset) {
    uint64_t trunc = page_addr & L1D_TRUNC_ADDR_MASK;
    for (int i = 0; i < L1D_AT_ENTRIES; i++) {
        if (l1d_archive_table[l1d_cpu][i].page_addr == trunc &&
            l1d_archive_table[l1d_cpu][i].first_offset == first_offset) {
            return i;
        }
    }
    return L1D_AT_ENTRIES;
}

// ==========================================
// IP MAPPING TABLE
// Maps instruction pointer hash to archive table entry.
// ==========================================

#define L1D_IP_TABLE_INDEX_BITS 10
#define L1D_IP_TABLE_ENTRIES (1 << L1D_IP_TABLE_INDEX_BITS)
#define L1D_IP_TABLE_INDEX_MASK (L1D_IP_TABLE_ENTRIES - 1)
#define L1D_IP_TABLE_NULL_PTR L1D_AT_ENTRIES

uint64_t l1d_ip_table[NUM_CPUS][L1D_IP_TABLE_ENTRIES];   // 11 bits per entry

void l1d_init_ip_table() {
    for (int i = 0; i < L1D_IP_TABLE_ENTRIES; i++) {
        l1d_ip_table[l1d_cpu][i] = L1D_IP_TABLE_NULL_PTR;
    }
}

// ==========================================
// TABLE MOVEMENTS
// Evicts current page data to archive for long-term storage.
// ==========================================

void l1d_archive_current_page(uint64_t apt_index) {
    if (l1d_active_page_table[l1d_cpu][apt_index].access_bitmap) {
        uint64_t ip_hash = l1d_active_page_table[l1d_cpu][apt_index].ip_tag & L1D_IP_TABLE_INDEX_MASK;
        uint64_t at_index = l1d_ip_table[l1d_cpu][ip_hash];
        assert(at_index < L1D_AT_ENTRIES);
        uint64_t conf;
        l1d_add_at(at_index,
                    l1d_active_page_table[l1d_cpu][apt_index].page_addr,
                    l1d_active_page_table[l1d_cpu][apt_index].access_bitmap,
                    l1d_active_page_table[l1d_cpu][apt_index].first_offset,
                    l1d_get_best_delta(apt_index, conf));
    }
}

// ==========================================
// DPC-3 INTERFACE
// ==========================================

void CACHE::l1d_prefetcher_initialize() {
    l1d_cpu = cpu;
    l1d_init_apt();
    l1d_init_hb();
    l1d_init_pp();
    l1d_init_at();
    l1d_init_ip_table();
}

void CACHE::l1d_prefetcher_operate(uint64_t addr, uint64_t ip,
                                    uint8_t cache_hit, uint8_t type) {
    l1d_cpu = cpu;
    uint64_t line_addr = addr >> LOG2_BLOCK_SIZE;
    uint64_t page_addr = line_addr >> L1D_PAGE_BLOCKS_BITS;
    uint64_t offset = line_addr & L1D_PAGE_OFFSET_MASK;

    uint64_t apt_index = l1d_get_apt_entry(page_addr);

    if (apt_index == L1D_APT_ENTRIES ||
        !l1d_offset_requested(apt_index, offset)) {

        if (apt_index < L1D_APT_ENTRIES) {
            l1d_active_page_table[l1d_cpu][apt_index].access_bitmap |= ((uint64_t)1 << offset);
            l1d_update_lru_apt(apt_index);

            if (cache_hit) {
                uint64_t pf_lat = l1d_get_pf_latency(apt_index, offset, current_core_cycle[cpu]);
                if (pf_lat != 0) {
                    int found_deltas[L1D_APT_DELTAS_PER_ACCESS];
                    l1d_get_deltas_from_hb(apt_index, offset,
                                           current_core_cycle[cpu] - pf_lat, found_deltas);
                    for (int i = 0; i < L1D_APT_DELTAS_PER_ACCESS; i++) {
                        if (found_deltas[i] == 0) break;
                        l1d_add_delta(apt_index, found_deltas[i]);
                    }
                }
            }
        } else {
            // Allocate new APT entry
            uint64_t lru_idx = l1d_get_lru_apt_entry();
            l1d_archive_current_page(lru_idx);
            l1d_active_page_table[l1d_cpu][lru_idx].page_addr = page_addr;
            l1d_active_page_table[l1d_cpu][lru_idx].ip_tag = ip & ((1 << 10) - 1);
            l1d_active_page_table[l1d_cpu][lru_idx].access_bitmap = (uint64_t)1 << offset;
            l1d_active_page_table[l1d_cpu][lru_idx].first_offset = offset;
            for (int i = 0; i < L1D_APT_NUM_DELTAS; i++) {
                l1d_active_page_table[l1d_cpu][lru_idx].delta_scores[i] = 0;
            }
            l1d_active_page_table[l1d_cpu][lru_idx].last_pf_offset = 0;

            // Check archive for historical delta
            uint64_t at_idx = l1d_find_at_entry(page_addr, offset);
            if (at_idx < L1D_AT_ENTRIES) {
                int hist_delta = l1d_archive_table[l1d_cpu][at_idx].best_delta;
                if (hist_delta != 0) {
                    int target = (int)offset + hist_delta;
                    if (target >= 0 && target < L1D_PAGE_BLOCKS) {
                        prefetch_line(ip, addr, ((addr >> LOG2_BLOCK_SIZE) + hist_delta) << LOG2_BLOCK_SIZE, FILL_L1, 0);
                        l1d_add_pp(lru_idx, target, current_core_cycle[cpu]);
                    }
                }
            }

            // Allocate IP table entry
            uint64_t ip_hash = ip & L1D_IP_TABLE_INDEX_MASK;
            if (l1d_ip_table[l1d_cpu][ip_hash] == L1D_IP_TABLE_NULL_PTR) {
                l1d_ip_table[l1d_cpu][ip_hash] = l1d_get_lru_at_entry();
            }
            apt_index = lru_idx;
        }

        // Record demand in history buffer
        l1d_add_hb(apt_index, offset, current_core_cycle[cpu]);

        // Issue prefetches based on current best delta
        uint64_t conf;
        int best = l1d_get_best_delta(apt_index, conf);
        if (best != 0 && conf >= L1D_DELTA_CONFIDENCE_THRESHOLD) {
            int pf_count = 0;
            int target = (int)offset;
            while (pf_count < L1D_MAX_BURST_PREFETCHES) {
                target += best;
                if (target < 0 || target >= L1D_PAGE_BLOCKS) break;
                if (!l1d_offset_requested(apt_index, target)) {
                    prefetch_line(ip, addr, ((page_addr << L1D_PAGE_BLOCKS_BITS) + target) << LOG2_BLOCK_SIZE, FILL_L1, 0);
                    l1d_add_pp(apt_index, target, current_core_cycle[cpu]);
                    pf_count++;
                }
            }
            l1d_active_page_table[l1d_cpu][apt_index].last_pf_offset = (target >= 0) ? target : 0;
        }
    }
}

void CACHE::l1d_prefetcher_cache_fill(uint64_t addr, uint32_t set,
                                       uint32_t way, uint8_t prefetch,
                                       uint64_t evicted_addr) {
    l1d_cpu = cpu;
    if (prefetch) {
        uint64_t line_addr = addr >> LOG2_BLOCK_SIZE;
        uint64_t page_addr = line_addr >> L1D_PAGE_BLOCKS_BITS;
        uint64_t offset = line_addr & L1D_PAGE_OFFSET_MASK;
        uint64_t apt_index = l1d_get_apt_entry(page_addr);
        if (apt_index < L1D_APT_ENTRIES) {
            l1d_get_pf_latency(apt_index, offset, current_core_cycle[cpu]);
        }
    }
}

void CACHE::l1d_prefetcher_final_stats() {
    // No final stats for L1D
}
