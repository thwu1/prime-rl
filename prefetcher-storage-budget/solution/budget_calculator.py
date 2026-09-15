#!/usr/bin/env python3
"""
IPC-1 Prefetcher Hardware Storage Budget Calculator

Reads D-JOLT, PIPS, and FNL+MMA prefetcher source files from /app/prefetchers/
and computes exact hardware storage budgets in bits.

"""

import json
import math
import re
import sys


def extract_constexpr(source, name):
    """Extract a constexpr size_t value from D-JOLT style source."""
    pattern = rf'(?:static\s+)?constexpr\s+size_t\s+{re.escape(name)}\s*=\s*(\d+)'
    m = re.search(pattern, source)
    if m:
        return int(m.group(1))
    return None


def extract_define(source, name):
    """Extract a #define value, handling simple expressions."""
    pattern = rf'#define\s+{re.escape(name)}\s+(.+?)(?:\s*//.*)?$'
    m = re.search(pattern, source, re.MULTILINE)
    if not m:
        return None
    expr = m.group(1).strip()
    # Handle parenthesized expressions
    expr = expr.strip('()')
    # Handle bit shift: 1<< (X+Y) or (1<<X)
    shift_match = re.match(r'1\s*<<\s*\(?\s*(\d+)\s*\+\s*(\w+)\s*\)?', expr)
    if shift_match:
        a = int(shift_match.group(1))
        b_name = shift_match.group(2)
        b_val = extract_define(source, b_name)
        if b_val is not None:
            return 1 << (a + b_val)
    shift_match2 = re.match(r'1\s*<<\s*(\d+)', expr)
    if shift_match2:
        return 1 << int(shift_match2.group(1))
    # Handle multiplication: A*B
    mul_match = re.match(r'(\d+)\s*\*\s*(\w+)', expr)
    if mul_match:
        a = int(mul_match.group(1))
        b_name = mul_match.group(2)
        b_val = extract_define(source, b_name)
        if b_val is not None:
            return a * b_val
    mul_match2 = re.match(r'(\w+)\s*\*\s*(\w+)', expr)
    if mul_match2:
        a_name = mul_match2.group(1)
        b_name = mul_match2.group(2)
        a_val = extract_define(source, a_name)
        b_val = extract_define(source, b_name)
        if a_val is not None and b_val is not None:
            return a_val * b_val
    # Plain integer
    try:
        return int(expr)
    except ValueError:
        return None


def compute_djolt_budget(source):
    """
    D-JOLT budget is computed from constexpr parameters and the budget comments.

    Components:
    1. Long-range miss table
    2. Long-range siggen (Siggen_FifoRetCnt<7>)
    3. Long-range sig queue (SignatureQueue<12>)
    4. Short-range miss table
    5. Short-range siggen (Siggen_FifoRetCnt<4>)
    6. Short-range sig queue (SignatureQueue<4>)
    7. Extra miss table
    8. Upper bit table
    9. Training table (WindowBasedStreamPrefetcher)
    10. Monitoring table (WindowBasedStreamPrefetcher)
    """
    # Extract parameters
    sig_bits = extract_constexpr(source, 'SignatureBits')  # 23
    ubp_bits = extract_constexpr(source, 'UpperBitPtrBits')  # 4

    lr_sets = extract_constexpr(source, 'LongRangePrefetcher_N_Sets')  # 2048
    lr_ways = extract_constexpr(source, 'LongRangePrefetcher_N_Ways')  # 4
    lr_nvec = extract_constexpr(source, 'LongRangePrefetcher_N_Vectors')  # 2
    lr_vsz = extract_constexpr(source, 'LongRangePrefetcher_VectorSize')  # 8
    lr_tag = extract_constexpr(source, 'LongRangePrefetcher_TagBits')  # 12
    lr_dist = extract_constexpr(source, 'LongRangePrefetcherDistance')  # 12

    sr_sets = extract_constexpr(source, 'ShortRangePrefetcher_N_Sets')  # 1024
    sr_ways = extract_constexpr(source, 'ShortRangePrefetcher_N_Ways')  # 4
    sr_nvec = extract_constexpr(source, 'ShortRangePrefetcher_N_Vectors')  # 2
    sr_vsz = extract_constexpr(source, 'ShortRangePrefetcher_VectorSize')  # 8
    sr_tag = extract_constexpr(source, 'ShortRangePrefetcher_TagBits')  # 13
    sr_dist = extract_constexpr(source, 'ShortRangePrefetcherDistance')  # 4

    ex_sets = extract_constexpr(source, 'ExtraMissTable_N_Sets')  # 128
    ex_ways = extract_constexpr(source, 'ExtraMissTable_N_Ways')  # 4
    ex_nvec = extract_constexpr(source, 'ExtraMissTable_N_Vectors')  # 2
    ex_vsz = extract_constexpr(source, 'ExtraMissTable_VectorSize')  # 8
    ex_tag = extract_constexpr(source, 'ExtraMissTable_TagBits')  # 16

    # Extract siggen history lengths from #define macros
    lr_siggen_match = re.search(r'#define\s+LongRangePrefetcherSiggen\s+Siggen_FifoRetCnt<(\d+)>', source)
    lr_hist = int(lr_siggen_match.group(1))  # 7

    sr_siggen_match = re.search(r'#define\s+ShortRangePrefetcherSiggen\s+Siggen_FifoRetCnt<(\d+)>', source)
    sr_hist = int(sr_siggen_match.group(1))  # 4

    def miss_table_bits(n_sets, n_ways, n_vectors, vector_size, tag_bits):
        """Compute miss table storage in bits."""
        total_entries = n_sets * n_ways
        tag_total = tag_bits * total_entries
        # Each vector: compressed upper address (ubp_bits) + lower address (18 bits) + bit vector (vector_size)
        vec_per_entry = (ubp_bits + 18 + vector_size) * n_vectors
        vec_total = vec_per_entry * total_entries
        # LRU bits: ceil(log2(n_ways)) per entry
        lru_per_entry = math.ceil(math.log2(n_ways))
        lru_total = lru_per_entry * total_entries
        return tag_total + vec_total + lru_total

    def siggen_bits(hist_len):
        """Siggen_FifoRetCnt storage: address queue + head pointer + return counter."""
        addr_bits = 32 * hist_len
        head_bits = math.ceil(math.log2(hist_len))
        ret_counter = 32
        return addr_bits + head_bits + ret_counter

    def sig_queue_bits(distance):
        """SignatureQueue storage: signature array + head pointer."""
        sig_total = sig_bits * distance
        head_bits = math.ceil(math.log2(distance))
        return sig_total + head_bits

    def upper_bit_table_bits():
        """Upper bit table: (2^UpperBitPtrBits - 1) entries with 40-bit upper + 1 valid."""
        entries = (1 << ubp_bits) - 1  # 15
        return (40 + 1) * entries

    def training_table_bits():
        """WindowBasedStreamPrefetcher training table: 16 entries."""
        size = 16
        # line_address(58) + valid(1) + counter(2) + lru(ceil(log2(16))=4)
        per_entry = 58 + 1 + 2 + math.ceil(math.log2(size))
        return per_entry * size

    def monitoring_table_bits():
        """WindowBasedStreamPrefetcher monitoring table: 16 entries."""
        size = 16
        # line_address(58) + valid(1) + lru(ceil(log2(16))=4)
        per_entry = 58 + 1 + math.ceil(math.log2(size))
        return per_entry * size

    # Compute all components
    lr_miss = miss_table_bits(lr_sets, lr_ways, lr_nvec, lr_vsz, lr_tag)
    lr_sig = siggen_bits(lr_hist)
    lr_sq = sig_queue_bits(lr_dist)
    sr_miss = miss_table_bits(sr_sets, sr_ways, sr_nvec, sr_vsz, sr_tag)
    sr_sig = siggen_bits(sr_hist)
    sr_sq = sig_queue_bits(sr_dist)
    ex_miss = miss_table_bits(ex_sets, ex_ways, ex_nvec, ex_vsz, ex_tag)
    ubt = upper_bit_table_bits()
    train = training_table_bits()
    monitor = monitoring_table_bits()

    total = lr_miss + lr_sig + lr_sq + sr_miss + sr_sig + sr_sq + ex_miss + ubt + train + monitor

    return total


def compute_pips_budget(source):
    """
    PIPS budget from LHT and SCC tables.

    LHT_ENTRY::size() = NTARGETS * OFFSETBITS + (NTARGETS+1) * CBITS
    LINE_HISTORY_TABLE::size() = (LHT_ENTRY::size() + TAGBITS + rpbits) * n
    where n = numways << logsets
    """
    ntargets = extract_define(source, 'NTARGETS')  # 3
    offsetbits = extract_define(source, 'OFFSETBITS')  # 22
    cbits = extract_define(source, 'CBITS')  # 4
    tagbits = extract_define(source, 'TAGBITS')  # 16

    lht_logsets = extract_define(source, 'LHT_LOGSETS')  # 10
    lht_numways = extract_define(source, 'LHT_NUMWAYS')  # 10
    lht_rpbits = extract_define(source, 'LHT_RPBITS')  # 2

    scc_logsets = extract_define(source, 'SCC_LOGSETS')  # 5
    scc_numways = extract_define(source, 'SCC_NUMWAYS')  # 3
    scc_rpbits = extract_define(source, 'SCC_RPBITS')  # 2

    # LHT_ENTRY::size() = NTARGETS * OFFSETBITS + (NTARGETS+1) * CBITS
    entry_size = ntargets * offsetbits + (ntargets + 1) * cbits

    # LHT
    lht_n = lht_numways << lht_logsets
    lht_per_entry = entry_size + tagbits + lht_rpbits
    lht_bits = lht_per_entry * lht_n

    # SCC (same entry format, different table params)
    scc_n = scc_numways << scc_logsets
    scc_per_entry = entry_size + tagbits + scc_rpbits
    scc_bits = scc_per_entry * scc_n

    # Total (excluding minor global state, per IPC-1 convention)
    total = lht_bits + scc_bits

    return total


def compute_fnlmma_budget(source):
    """
    FNL+MMA budget from the printf expressions in l1i_prefetcher_final_stats().

    Components:
    1. MMA table (AHEAD): 72 bits * 4 banks * SIZEWAYNEXTMISS entries per bank
    2. I-Shadow cache: SIZESHADOWICACHE * 17 bits
    3. Touched + WorthPF tables: FNL_NBENTRIES * 3 bits
    4. MMA filter (PREVPRED): MMA_FILT_SIZE * 58 bits
    5. FNL filter: SIZEFILTERFNL * 17 bits
    """
    logmultsize = extract_define(source, 'LOGMULTSIZE')  # 0
    mma_filt_size = extract_define(source, 'MMA_FILT_SIZE')  # 13
    nbwayishadow = extract_define(source, 'NBWAYISHADOW')  # 4
    nbwayfilterfnl = extract_define(source, 'NBWAYFILTERFNL')  # 4
    sizewayfilterfnl = extract_define(source, 'SIZEWAYFILTERFNL')  # 32

    # Derived values
    # AHEAD.init(DISTAHEAD, 11) -> LOGWAYNEXTMISS = 11 + LOGMULTSIZE
    logwaynextmiss = 11 + logmultsize  # 11
    sizewaynextmiss = 1 << logwaynextmiss  # 2048

    sizeshadowicache = 64 * nbwayishadow  # 192

    # FNL_NBENTRIES = 1 << (16 + LOGMULTSIZE)
    fnl_nbentries = 1 << (16 + logmultsize)  # 65536

    sizefilterfnl = sizewayfilterfnl * nbwayfilterfnl  # 128

    # Compute bits for each component (from printf formulas in final_stats)
    # MMA table: 72 bits per entry, 4 banks, sizewaynextmiss entries per bank
    # 72 = LOGTAGNEXTMISS(12) + NBlock(58) + U(1) + valid(1)
    mma_bits = 72 * 4 * sizewaynextmiss

    # I-Shadow cache: (15-bit tag + 2-bit LRU) per entry
    ishadow_bits = sizeshadowicache * (15 + 2)

    # Touched + WorthPF: 1 bit + 2 bits = 3 bits per entry
    touched_worthpf_bits = fnl_nbentries * 3

    # MMA filter (PREVPRED): 58-bit addresses
    mma_filter_bits = mma_filt_size * 58

    # FNL filter: (15-bit tag + 2-bit LRU) per entry
    fnl_filter_bits = sizefilterfnl * (15 + 2)

    total = mma_bits + ishadow_bits + touched_worthpf_bits + mma_filter_bits + fnl_filter_bits

    return total


def main():
    # Read source files
    with open('/app/prefetchers/DJOLT_prefetcher.cc', 'r') as f:
        djolt_source = f.read()
    with open('/app/prefetchers/PIPS_prefetcher.cc', 'r') as f:
        pips_source = f.read()
    with open('/app/prefetchers/FNLMMA_prefetcher.cc', 'r') as f:
        fnlmma_source = f.read()

    # Compute budgets
    djolt_bits = compute_djolt_budget(djolt_source)
    pips_bits = compute_pips_budget(pips_source)
    fnlmma_bits = compute_fnlmma_budget(fnlmma_source)

    budget_128kb = 1048576  # 128 * 1024 * 8

    results = {
        "DJOLT": {
            "total_bits": djolt_bits,
            "under_128kb": djolt_bits <= budget_128kb
        },
        "PIPS": {
            "total_bits": pips_bits,
            "under_128kb": pips_bits <= budget_128kb
        },
        "FNLMMA": {
            "total_bits": fnlmma_bits,
            "under_128kb": fnlmma_bits <= budget_128kb
        }
    }

    with open('/app/budgets.json', 'w') as f:
        json.dump(results, f, indent=2)

    print("Budget calculation complete:")
    for name, info in results.items():
        kb = info["total_bits"] / 8192
        print(f"  {name}: {info['total_bits']} bits ({kb:.2f} KB) - {'PASS' if info['under_128kb'] else 'FAIL'}")


if __name__ == '__main__':
    main()
