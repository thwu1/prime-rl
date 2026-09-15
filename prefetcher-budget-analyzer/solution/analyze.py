#!/usr/bin/env python3
"""
ChampSim IPC-1 Prefetcher Storage Budget Analyzer

Resolves C preprocessor #define macros from ChampSim framework headers and
IPC-1 competition prefetcher source files, then computes hardware storage
budgets for the FNLMMA and PIPS prefetchers.

"""
import os
import re
import json
import glob


def parse_defines(filepath):
    """Extract object-like #define macros from a C/C++ file.

    Skips function-like macros (#define NAME(...) ...) and flag defines
    (#define NAME with no value). Strips trailing C/C++ comments.
    """
    macros = {}
    with open(filepath) as f:
        for raw_line in f:
            line = raw_line.strip()
            # Match #define NAME ...
            m = re.match(r'^#\s*define\s+([A-Za-z_]\w*)(.*)', line)
            if not m:
                continue
            name = m.group(1)
            rest = m.group(2)

            # Function-like macro: opening paren immediately after name
            if rest.startswith('('):
                continue

            # Strip leading whitespace from value
            value = rest.strip()

            # Remove C++ line comments
            value = re.sub(r'//.*$', '', value).strip()
            # Remove C block comments (single-line only)
            value = re.sub(r'/\*.*?\*/', '', value).strip()

            if not value:
                continue  # flag define with no value

            macros[name] = value
    return macros


def try_evaluate(expr):
    """Attempt to evaluate a C-style arithmetic expression as a Python int.

    Handles: arithmetic (+, -, *, /), bitwise (<<, >>, &, |, ^, ~),
    parenthesized sub-expressions, type casts ((uint64_t) etc.),
    and integer literal suffixes (U, L, UL, ULL, LL).

    Returns (True, int_value) on success, (False, 0) on failure.
    """
    # Remove C-style type casts
    cleaned = re.sub(
        r'\(\s*(?:u?int(?:8|16|32|64)_t|'
        r'unsigned\s+(?:int|long(?:\s+long)?)|'
        r'signed\s+(?:int|long(?:\s+long)?)|'
        r'int|long\s+long|long|size_t|char|short|'
        r'float|double|uint64_t)\s*\)',
        '', expr
    )

    # Remove integer literal suffixes
    cleaned = re.sub(r'(\d+)\s*(?:ULL|UL|LL|U|L)\b', r'\1',
                     cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.strip()

    if not cleaned:
        return False, 0

    # Verify no unresolved identifiers remain
    # (exclude hex digits that appear in 0x... literals)
    check = re.sub(r'0[xX][0-9a-fA-F]+', '', cleaned)
    if re.search(r'[a-zA-Z_]\w*', check):
        return False, 0

    # Evaluate as Python expression
    try:
        result = eval(cleaned)
        if isinstance(result, (int, float)):
            return True, int(result)
    except Exception:
        pass

    return False, 0


def resolve_macros(raw_macros):
    """Iteratively resolve macros to integer values.

    Performs repeated passes, substituting already-resolved macro values
    into unresolved expressions until no further progress is made.
    """
    resolved = {}
    unresolved = dict(raw_macros)

    for _iteration in range(300):
        progress = False
        for name in list(unresolved):
            expr = unresolved[name]

            # Substitute resolved macros (longest name first to avoid
            # partial matches, though \\b handles this correctly)
            substituted = expr
            for rname in sorted(resolved, key=len, reverse=True):
                substituted = re.sub(
                    r'\b' + re.escape(rname) + r'\b',
                    str(resolved[rname]),
                    substituted
                )

            success, value = try_evaluate(substituted)
            if success:
                resolved[name] = value
                del unresolved[name]
                progress = True

        if not progress:
            break

    return resolved


def compute_fnlmma_storage(macros):
    """Compute FNLMMA prefetcher hardware storage budget.

    Derived from the printf formulas in l1i_prefetcher_final_stats():

      Miss Ahead Prediction Table:  72 * 4 * SIZEWAYNEXTMISS / 8
      I-Shadow cache:               (SIZESHADOWICACHE * 17) / 8
      Touched + WorthPF tables:     (FNL_NBENTRIES * 3) / 8
      MMA filter:                   (MMA_FILT_SIZE * 58) / 8
      FNL filter:                   (SIZEFILTERFNL * 17) / 8

    SIZEWAYNEXTMISS is computed as 1 << (11 + LOGMULTSIZE) from the
    PredictMiss::init() call in l1i_prefetcher_initialize():
      AHEAD.init(DISTAHEAD, 11)
      -> LOGWAYNEXTMISS = 11 + LOGMULTSIZE
      -> SIZEWAYNEXTMISS = 1 << LOGWAYNEXTMISS

    All division uses C integer semantics (truncation toward zero).
    """
    logmultsize = macros['LOGMULTSIZE']
    sizewaynextmiss = 1 << (11 + logmultsize)

    # 72 bits per entry = 12-bit tag + 58-bit block + 1-bit confidence
    # = 71 bits, rounded to 72 by author; 4 ways per set
    miss_ahead = 72 * 4 * sizewaynextmiss // 8

    # 15-bit tag + 2-bit LRU = 17 bits per entry
    i_shadow = (macros['SIZESHADOWICACHE'] * 17) // 8

    # 1-bit Touched + 2-bit WorthPF = 3 bits per entry
    touched_worthpf = (macros['FNL_NBENTRIES'] * 3) // 8

    # 58-bit address per entry
    mma_filter = (macros['MMA_FILT_SIZE'] * 58) // 8

    # 15-bit tag + 2-bit for FIFO = 17 bits per entry
    fnl_filter = (macros['SIZEFILTERFNL'] * 17) // 8

    return miss_ahead + i_shadow + touched_worthpf + mma_filter + fnl_filter


def compute_pips_storage(macros):
    """Compute PIPS prefetcher hardware storage budget.

    From the LINE_HISTORY_TABLE class:

      LHT_ENTRY::size() = NTARGETS * OFFSETBITS + (NTARGETS+1) * CBITS

      LINE_HISTORY_TABLE::size():
        nbits = LHT_ENTRY::size() + TAGBITS + rpbits
        n = nway << logset
        total = nbits * n

    Two tables: lht(LHT_LOGSETS, LHT_NUMWAYS, LHT_RPBITS)
                scc(SCC_LOGSETS, SCC_NUMWAYS, SCC_RPBITS)

    Returns (total_bits, total_kb_rounded_2dp).
    """
    ntargets = macros['NTARGETS']
    offsetbits = macros['OFFSETBITS']
    cbits = macros['CBITS']
    tagbits = macros['TAGBITS']

    # LHT_ENTRY::size()
    entry_bits = ntargets * offsetbits + (ntargets + 1) * cbits

    # lht table
    lht_logsets = macros['LHT_LOGSETS']
    lht_numways = macros['LHT_NUMWAYS']
    lht_rpbits = macros['LHT_RPBITS']
    lht_nbits_per_entry = entry_bits + tagbits + lht_rpbits
    lht_n = lht_numways * (1 << lht_logsets)
    lht_total = lht_nbits_per_entry * lht_n

    # scc table (same entry type, different configuration)
    scc_logsets = macros['SCC_LOGSETS']
    scc_numways = macros['SCC_NUMWAYS']
    scc_rpbits = macros['SCC_RPBITS']
    scc_nbits_per_entry = entry_bits + tagbits + scc_rpbits
    scc_n = scc_numways * (1 << scc_logsets)
    scc_total = scc_nbits_per_entry * scc_n

    total_bits = lht_total + scc_total
    total_kb = round(total_bits / 8192, 2)

    return total_bits, total_kb


def main():
    source_dir = '/app/sources'
    output_dir = '/app/output'
    os.makedirs(output_dir, exist_ok=True)

    # Collect all #define macros from all source files
    all_raw_macros = {}
    for pattern in ('*.h', '*.cc'):
        for filepath in sorted(glob.glob(os.path.join(source_dir, pattern))):
            file_macros = parse_defines(filepath)
            all_raw_macros.update(file_macros)

    # Resolve to integer values
    resolved = resolve_macros(all_raw_macros)

    # Compute storage budgets
    fnlmma_bytes = compute_fnlmma_storage(resolved)
    pips_bits, pips_kb = compute_pips_storage(resolved)

    # Build output
    result = {
        "resolved_macros": dict(sorted(resolved.items())),
        "storage": {
            "FNLMMA_total_bytes": fnlmma_bytes,
            "FNLMMA_within_budget": fnlmma_bytes <= 131072,
            "PIPS_total_bits": pips_bits,
            "PIPS_total_kb": pips_kb,
            "PIPS_within_budget": pips_kb <= 128.0
        }
    }

    with open(os.path.join(output_dir, 'analysis.json'), 'w') as f:
        json.dump(result, f, indent=2)

    print("Analysis complete.")
    print(f"Resolved {len(resolved)} macros.")
    print(f"FNLMMA: {fnlmma_bytes} bytes "
          f"({'PASS' if fnlmma_bytes <= 131072 else 'FAIL'})")
    print(f"PIPS: {pips_bits} bits = {pips_kb} KB "
          f"({'PASS' if pips_kb <= 128.0 else 'FAIL'})")


if __name__ == '__main__':
    main()
