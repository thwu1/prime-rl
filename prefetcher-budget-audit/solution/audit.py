#!/usr/bin/env python3
"""
DPC-3 Prefetcher Storage Budget Auditor

Parses C++ prefetcher source files to extract data structure declarations,
resolves preprocessor macros, computes hardware bit-width budgets, and
writes a JSON audit report.

"""

import json
import os
import re
import ast
import operator


# ---------------------------------------------------------------------------
# Macro evaluator: resolves #define expressions involving integers, shifts,
# parentheses, and references to other macros.
# ---------------------------------------------------------------------------

def extract_macros(source_code):
    """Extract all #define NAME VALUE macros from source code."""
    macros = {}
    pattern = re.compile(r'^\s*#define\s+(\w+)\s+(.+?)(?:\s*//.*)?$', re.MULTILINE)
    for m in pattern.finditer(source_code):
        name = m.group(1)
        value = m.group(2).strip()
        # Remove trailing C-style comments
        value = re.sub(r'/\*.*?\*/', '', value).strip()
        # Remove trailing inline comments
        value = re.sub(r'//.*$', '', value).strip()
        macros[name] = value
    return macros


def evaluate_macro(expr, macros, resolved_cache=None):
    """Evaluate a macro expression to an integer."""
    if resolved_cache is None:
        resolved_cache = {}

    expr = expr.strip()

    # Remove C-style casts like (uint64_t)
    expr = re.sub(r'\(\s*(?:uint64_t|uint32_t|int|unsigned)\s*\)', '', expr)

    # Remove ULL/UL/U suffixes
    expr = re.sub(r'(\d+)\s*(?:ULL|UL|U|ull|ul|u)\b', r'\1', expr)

    # Substitute known macros (iterate to resolve chains)
    max_iter = 20
    for _ in range(max_iter):
        new_expr = expr
        for name, value in macros.items():
            # Only substitute whole words
            new_expr = re.sub(r'\b' + re.escape(name) + r'\b', f'({value})', new_expr)
        if new_expr == expr:
            break
        expr = new_expr
        # Re-clean casts and suffixes after substitution
        expr = re.sub(r'\(\s*(?:uint64_t|uint32_t|int|unsigned)\s*\)', '', expr)
        expr = re.sub(r'(\d+)\s*(?:ULL|UL|U|ull|ul|u)\b', r'\1', expr)

    # Replace << and >> with Python operators (they're the same in Python)
    # Clean up any remaining non-numeric, non-operator chars
    # Allowed: digits, +, -, *, /, (, ), <<, >>, whitespace
    try:
        result = eval(expr, {"__builtins__": {}}, {})
        return int(result)
    except Exception:
        raise ValueError(f"Cannot evaluate macro expression: {expr}")


def resolve_all_macros(macros):
    """Resolve all macros to integer values where possible."""
    resolved = {}
    for name, expr in macros.items():
        try:
            resolved[name] = evaluate_macro(expr, macros)
        except (ValueError, SyntaxError):
            pass  # Skip non-integer macros
    return resolved


# ---------------------------------------------------------------------------
# Struct field parser: extracts bit-width annotations from comments.
# ---------------------------------------------------------------------------

def extract_struct_fields(source_code, struct_pattern):
    """
    Extract fields from a typedef struct block.
    Returns list of (field_name, annotated_bits, array_size_or_1).
    """
    # Find the struct body
    match = re.search(struct_pattern, source_code, re.DOTALL)
    if not match:
        return []

    body = match.group(1)
    fields = []

    for line in body.split('\n'):
        line = line.strip()
        if not line or line.startswith('//') or line.startswith('{') or line.startswith('}'):
            continue

        # Look for bit-width annotation in comment
        # Patterns: "// N bits", "// N bits each", "// N bits per weight"
        bits_match = re.search(r'//\s*(\d+)\s+bits?\s*(each|per\s+\w+)?', line)
        if not bits_match:
            continue

        bits_per_elem = int(bits_match.group(1))
        is_per_element = bits_match.group(2) is not None

        # Check if this field is an array
        array_match = re.search(r'\w+\s+\w+\[([^\]]+)\]', line)
        if array_match and is_per_element:
            array_size_expr = array_match.group(1)
            fields.append((line, bits_per_elem, array_size_expr, True))
        else:
            fields.append((line, bits_per_elem, None, False))

    return fields


# ---------------------------------------------------------------------------
# L1D Audit
# ---------------------------------------------------------------------------

def audit_l1d(source_code, macros):
    resolved = resolve_all_macros(macros)

    structures = {}

    # 1. Active Page Table (APT)
    apt_entries = resolved['L1D_APT_ENTRIES']  # (1<<7)-1 = 127
    num_deltas = resolved['L1D_APT_NUM_DELTAS']  # 12
    # Fields: page_addr(52) + ip_tag(10) + access_bitmap(64) + first_offset(6)
    #       + deltas[12](7 each) + delta_scores[12](5 each) + last_pf_offset(6) + lru(7)
    bits_per_entry = 52 + 10 + 64 + 6 + (num_deltas * 7) + (num_deltas * 5) + 6 + 7
    structures['active_page_table'] = apt_entries * bits_per_entry

    # 2. History Buffer (HB)
    hb_entries = resolved['L1D_HB_ENTRIES']  # 1<<10 = 1024
    # Fields: apt_pointer(7) + offset(6) + timestamp(16)
    bits_per_entry = 7 + 6 + 16
    structures['history_buffer'] = hb_entries * bits_per_entry

    # 3. Pending Prefetch (PP)
    pp_entries = resolved['L1D_PP_ENTRIES']  # 1<<9 = 512
    # Fields: apt_pointer(7) + offset(6) + issue_cycle(16) + fulfilled(1)
    bits_per_entry = 7 + 6 + 16 + 1
    structures['pending_prefetch'] = pp_entries * bits_per_entry

    # 4. Archive Table (AT)
    at_entries = resolved['L1D_AT_ENTRIES']  # ((1<<10)+(1<<8)+(1<<6))-1 = 1343
    # Fields: page_addr(32) + access_bitmap(64) + first_offset(6) + best_delta(7) + lru(11)
    bits_per_entry = 32 + 64 + 6 + 7 + 11
    structures['archive_table'] = at_entries * bits_per_entry

    # 5. IP Table
    ip_entries = resolved['L1D_IP_TABLE_ENTRIES']  # 1<<10 = 1024
    # 11 bits per entry
    structures['ip_table'] = ip_entries * 11

    # 6. Auxiliary: head pointers
    hb_head_bits = resolved['L1D_HB_INDEX_BITS']  # 10
    pp_head_bits = resolved['L1D_PP_INDEX_BITS']  # 9
    structures['auxiliary'] = hb_head_bits + pp_head_bits

    total = sum(structures.values())
    return total, structures


# ---------------------------------------------------------------------------
# L2C Audit
# ---------------------------------------------------------------------------

def audit_l2c(source_code, macros):
    resolved = resolve_all_macros(macros)

    structures = {}

    # 1. Signature Table (ST)
    st_entries = resolved['L2C_ST_ENTRIES']  # 1<<9 = 512
    # Fields: tag(16) + last_offset(6) + signature(12) + lru(9)
    bits_per_entry = 16 + 6 + 12 + 9
    structures['signature_table'] = st_entries * bits_per_entry

    # 2. Pattern Table (PT)
    pt_entries = resolved['L2C_PT_ENTRIES']  # 1<<12 = 4096
    # Fields: spatial_pattern(64) + confidence(4)
    bits_per_entry = 64 + 4
    structures['pattern_table'] = pt_entries * bits_per_entry

    # 3. Accumulation Table (ACCUM)
    accum_entries = resolved['L2C_ACCUM_ENTRIES']  # (1<<7)+(1<<5) = 160
    # Fields: page_addr(48) + spatial_pattern(64) + last_offset(6) + signature(12) + lru(8)
    bits_per_entry = 48 + 64 + 6 + 12 + 8
    structures['accumulation_table'] = accum_entries * bits_per_entry

    # 4. Prefetch Filter (PF)
    pf_entries = resolved['L2C_PF_ENTRIES']  # 1<<10 = 1024
    # Fields: tag(12) + useful(2)
    bits_per_entry = 12 + 2
    structures['prefetch_filter'] = pf_entries * bits_per_entry

    # 5. Perceptron Weights
    num_features = resolved['L2C_PERC_NUM_FEATURES']  # 6
    entries_per_feature = resolved['L2C_PERC_ENTRIES_PER_FEATURE']  # 1<<8 = 256
    weight_bits = resolved.get('L2C_PERC_WEIGHT_BITS', 6)  # 6
    structures['perceptron_weights'] = num_features * entries_per_feature * weight_bits

    # 6. Auxiliary: threshold counter
    # l2c_perc_threshold_counter annotated as 10 bits
    structures['auxiliary'] = 10

    total = sum(structures.values())
    return total, structures


# ---------------------------------------------------------------------------
# LLC Audit
# ---------------------------------------------------------------------------

def audit_llc(source_code, macros):
    resolved = resolve_all_macros(macros)

    structures = {}

    # 1. Stream Tracker Table
    stream_entries = resolved['LLC_STREAM_ENTRIES']  # 1<<6 = 64
    # Fields: region_addr(42) + offset(6) + direction(1) + confidence(3) + active(1) + lru(6)
    bits_per_entry = 42 + 6 + 1 + 3 + 1 + 6
    structures['stream_table'] = stream_entries * bits_per_entry

    # 2. Region Bitmap Table
    region_entries = resolved['LLC_REGION_ENTRIES']  # (1<<9)-(1<<3) = 504
    # Fields: tag(32) + access_bitmap(64) + lru(9)
    bits_per_entry = 32 + 64 + 9
    structures['region_table'] = region_entries * bits_per_entry

    total = sum(structures.values())
    return total, structures


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    prefetcher_dir = '/app/prefetchers'

    # Read source files
    with open(os.path.join(prefetcher_dir, 'chronos_l1d.cc'), 'r') as f:
        l1d_source = f.read()
    with open(os.path.join(prefetcher_dir, 'chronos_l2c.cc'), 'r') as f:
        l2c_source = f.read()
    with open(os.path.join(prefetcher_dir, 'chronos_llc.cc'), 'r') as f:
        llc_source = f.read()

    # Extract and resolve macros from each file
    l1d_macros = extract_macros(l1d_source)
    l2c_macros = extract_macros(l2c_source)
    llc_macros = extract_macros(llc_source)

    # Compute budgets
    l1d_total, l1d_structures = audit_l1d(l1d_source, l1d_macros)
    l2c_total, l2c_structures = audit_l2c(l2c_source, l2c_macros)
    llc_total, llc_structures = audit_llc(llc_source, llc_macros)

    grand_total = l1d_total + l2c_total + llc_total
    budget_limit = 524288  # 64 KB in bits
    compliant = grand_total <= budget_limit
    over_budget = max(0, grand_total - budget_limit)

    # Print detailed breakdown
    print("=" * 60)
    print("DPC-3 Storage Budget Audit — Chronos Prefetcher")
    print("=" * 60)

    print(f"\nL1D Prefetcher ({l1d_total} bits):")
    for name, bits in l1d_structures.items():
        print(f"  {name}: {bits} bits")

    print(f"\nL2C Prefetcher ({l2c_total} bits):")
    for name, bits in l2c_structures.items():
        print(f"  {name}: {bits} bits")

    print(f"\nLLC Prefetcher ({llc_total} bits):")
    for name, bits in llc_structures.items():
        print(f"  {name}: {bits} bits")

    print(f"\n{'=' * 60}")
    print(f"Grand Total:    {grand_total} bits ({grand_total / 8:.1f} bytes)")
    print(f"Budget Limit:   {budget_limit} bits ({budget_limit / 8:.0f} bytes)")
    print(f"Compliant:      {compliant}")
    if not compliant:
        print(f"Over Budget:    {over_budget} bits ({over_budget / 8:.1f} bytes)")
    print(f"{'=' * 60}")

    # Write audit JSON
    audit = {
        "l1d_total_bits": l1d_total,
        "l2c_total_bits": l2c_total,
        "llc_total_bits": llc_total,
        "grand_total_bits": grand_total,
        "budget_limit_bits": budget_limit,
        "compliant": compliant,
        "over_budget_bits": over_budget,
    }

    output_path = '/app/storage_audit.json'
    with open(output_path, 'w') as f:
        json.dump(audit, f, indent=2)

    print(f"\nAudit written to {output_path}")


if __name__ == '__main__':
    main()
