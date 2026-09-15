#!/usr/bin/env bash
#
# tagdiff.sh — Shell implementation of the DFTB+ tagged output comparison tool.
# Compares two tagged output files using tolerance rules from config file(s).
#
# Usage: tagdiff.sh [-c configfile]... [-v] ref_file new_file

set -uo pipefail

CONFIG_FILES=()
VERBOSE=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        -c|--config)
            CONFIG_FILES+=("$2")
            shift 2
            ;;
        -v|--verbose)
            VERBOSE=1
            shift
            ;;
        --)
            shift
            break
            ;;
        -*)
            echo "Error: unknown option '$1'" >&2
            exit 2
            ;;
        *)
            break
            ;;
    esac
done

if [[ $# -lt 2 ]]; then
    echo "Usage: $0 [-c config]... ref_file new_file" >&2
    exit 2
fi

REF_FILE="$1"
NEW_FILE="$2"

# Default config: tagdiff.conf in same directory as this script
if [[ ${#CONFIG_FILES[@]} -eq 0 ]]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    CONFIG_FILES=("${SCRIPT_DIR}/tagdiff.conf")
fi

# Validate all input files exist
for f in "${CONFIG_FILES[@]}"; do
    if [[ ! -f "$f" ]]; then
        echo "ERROR::Input/output error for file '$f'" >&2
        exit 1
    fi
done
for f in "$REF_FILE" "$NEW_FILE"; do
    if [[ ! -f "$f" ]]; then
        echo "ERROR::Input/output error for file '$f'" >&2
        exit 1
    fi
done

# Read a file, transparently decompressing if it ends in .gz
read_file() {
    local f="$1"
    if [[ "$f" == *.gz ]]; then
        zcat "$f"
    else
        cat "$f"
    fi
}

# Build the combined input stream with phase markers, then process in gawk.
# Phase markers delimit config sections, ref file, and new file.
{
    for cf in "${CONFIG_FILES[@]}"; do
        echo "===PHASE:CONFIG==="
        read_file "$cf"
    done
    echo "===PHASE:REF==="
    read_file "$REF_FILE"
    echo "===PHASE:NEW==="
    read_file "$NEW_FILE"
    echo "===PHASE:END==="
} | gawk '
# =========================================================================
# DFTB+ tagdiff comparison engine in gawk
# =========================================================================

BEGIN {
    phase = "init"
    ncfg = 0
    nref = 0
    nnew = 0
    cur_name = ""
    cur_type = ""
    cur_rank = 0
    cur_shape = ""
    cur_values = ""
    exit_code = 0
}

# ----- Phase transitions -----
/^===PHASE:CONFIG===/ { phase = "config"; next }
/^===PHASE:REF===/ {
    flush_entry()
    phase = "ref"
    cur_name = ""
    next
}
/^===PHASE:NEW===/ {
    flush_entry()
    phase = "new"
    cur_name = ""
    next
}
/^===PHASE:END===/ {
    flush_entry()
    phase = "done"
    next
}

# ----- Config parsing -----
phase == "config" {
    # Strip comments
    sub(/#.*/, "")
    # Skip blank lines
    if ($0 ~ /^[[:space:]]*$/) next

    n = split($0, fld, "@")
    if (n < 2) next

    ncfg++
    p = fld[1]; gsub(/^[[:space:]]+|[[:space:]]+$/, "", p)
    t = fld[2]; gsub(/^[[:space:]]+|[[:space:]]+$/, "", t)
    cfg_pat[ncfg] = p
    cfg_tol[ncfg] = t + 0.0

    cfg_meth[ncfg] = "element"
    cfg_marg[ncfg] = 0
    if (n >= 3) {
        mf = fld[3]; gsub(/^[[:space:]]+|[[:space:]]+$/, "", mf)
        if (mf != "") {
            nm = split(mf, mp, ":")
            cfg_meth[ncfg] = mp[1]
            if (nm >= 2) cfg_marg[ncfg] = mp[2] + 0
        }
    }

    # Field 4: keep/nokeep flag, or rtol:VALUE if keep/nokeep is omitted
    cfg_keep[ncfg] = 0
    cfg_rtol[ncfg] = -1
    if (n >= 4) {
        fl = fld[4]; gsub(/^[[:space:]]+|[[:space:]]+$/, "", fl)
        if (fl == "keep") {
            cfg_keep[ncfg] = 1
        } else if (fl == "nokeep") {
            cfg_keep[ncfg] = 0
        } else if (index(fl, "rtol:") == 1) {
            # rtol in field 4 when keep/nokeep is omitted
            cfg_rtol[ncfg] = substr(fl, 6) + 0.0
        }
    }

    # Field 5: rtol:VALUE (when field 4 is keep/nokeep)
    if (n >= 5) {
        rt = fld[5]; gsub(/^[[:space:]]+|[[:space:]]+$/, "", rt)
        if (index(rt, "rtol:") == 1) {
            cfg_rtol[ncfg] = substr(rt, 6) + 0.0
        }
    }

    next
}

# ----- Tag file parsing (ref or new) -----
(phase == "ref" || phase == "new") {
    # Detect tag header line: name<optional-spaces>:type:rank:shape
    if (match($0, /^([^: ]+)[[:space:]]*:([^:]+):([0-9]+):(.*)$/, m)) {
        flush_entry()
        cur_name  = m[1]
        cur_type  = m[2]; gsub(/^[[:space:]]+|[[:space:]]+$/, "", cur_type)
        cur_rank  = m[3] + 0
        cur_shape = m[4]; gsub(/^[[:space:]]+|[[:space:]]+$/, "", cur_shape)
        cur_values = ""
    } else if (cur_name != "") {
        # Data line — accumulate values
        line = $0
        gsub(/^[[:space:]]+|[[:space:]]+$/, "", line)
        if (line != "") {
            if (cur_values != "") cur_values = cur_values " "
            cur_values = cur_values line
        }
    }
}

# ----- Flush the current entry into the appropriate collection -----
function flush_entry(    tagged, idx) {
    if (cur_name == "") return

    tagged = cur_name ":" cur_type ":" cur_rank ":" cur_shape

    if (phase == "ref") {
        nref++
        idx = nref
        ref_name[idx]   = cur_name
        ref_type[idx]   = cur_type
        ref_rank[idx]   = cur_rank
        ref_shape[idx]  = cur_shape
        ref_tagged[idx] = tagged
        ref_values[idx] = cur_values
        ref_alive[idx]  = 1
    } else if (phase == "new") {
        nnew++
        idx = nnew
        new_name[idx]   = cur_name
        new_type[idx]   = cur_type
        new_rank[idx]   = cur_rank
        new_shape[idx]  = cur_shape
        new_tagged[idx] = tagged
        new_values[idx] = cur_values
        new_alive[idx]  = 1
    }

    cur_name = ""
    cur_values = ""
}

# ----- Look up a named entry in the new-file collection -----
function find_new(name,    i) {
    for (i = 1; i <= nnew; i++) {
        if (new_alive[i] && new_name[i] == name) return i
    }
    return 0
}

function abs_val(x) { return (x < 0) ? -x : x }

# ----- Element-wise max absolute difference -----
function element_diff(rv, nv, n, entry_type,    i, d, maxd, re_d, im_d) {
    maxd = 0
    if (entry_type == "complex") {
        # Values stored as interleaved real/imag pairs
        if (n % 2 != 0) return -1
        for (i = 1; i <= n; i += 2) {
            re_d = (rv[i] + 0.0) - (nv[i] + 0.0)
            im_d = (rv[i+1] + 0.0) - (nv[i+1] + 0.0)
            d = sqrt(re_d * re_d + im_d * im_d)
            if (d > maxd) maxd = d
        }
    } else if (entry_type == "logical") {
        for (i = 1; i <= n; i++) {
            rv_v = (rv[i] == "T" || rv[i] == "t") ? 1 : 0
            nv_v = (nv[i] == "T" || nv[i] == "t") ? 1 : 0
            d = abs_val(rv_v - nv_v)
            if (d > maxd) maxd = d
        }
    } else {
        # real or integer
        for (i = 1; i <= n; i++) {
            d = abs_val((rv[i] + 0.0) - (nv[i] + 0.0))
            if (d > maxd) maxd = d
        }
    }
    return maxd
}

# ----- Vector-norm max difference -----
function vector_diff(rv, nv, n, nelem, entry_type,    i, j, maxd, sumsq, d) {
    if (nelem <= 0 || n % nelem != 0) return -1
    maxd = 0
    for (i = 0; i < n; i += nelem) {
        sumsq = 0
        for (j = 1; j <= nelem; j++) {
            if (entry_type == "complex") {
                d = (rv[i + j] + 0.0) - (nv[i + j] + 0.0)
            } else if (entry_type == "logical") {
                rv_v = (rv[i + j] == "T" || rv[i + j] == "t") ? 1 : 0
                nv_v = (nv[i + j] == "T" || nv[i + j] == "t") ? 1 : 0
                d = rv_v - nv_v
            } else {
                d = (rv[i + j] + 0.0) - (nv[i + j] + 0.0)
            }
            sumsq += d * d
        }
        d = sqrt(sumsq)
        if (d > maxd) maxd = d
    }
    return maxd
}

# ----- Format and print one result line -----
function print_result(name, method, msg, status) {
    printf "%-20s %-20s %-27s %-10s\n", name, method, msg, status
    if (status == "Failed" || status == "Error") exit_code = 1
}

# =========================================================================
# END block — perform all comparisons
# =========================================================================
END {
    for (ci = 1; ci <= ncfg; ci++) {
        pat = cfg_pat[ci]

        # Find all matching reference entries
        for (ri = 1; ri <= nref; ri++) {
            if (!ref_alive[ri]) continue

            # Regex match anchored at start of the tagged line
            if (!match(ref_tagged[ri], "^" pat)) continue

            name = ref_name[ri]
            entry_type = ref_type[ri]

            # Build method display string
            meth_str = cfg_meth[ci]
            if (cfg_meth[ci] == "vector") {
                meth_str = meth_str ":" cfg_marg[ci]
            }

            # Look up in new collection
            ni = find_new(name)

            # Consume entries unless keep flag is set
            if (!cfg_keep[ci]) {
                ref_alive[ri] = 0
                if (ni > 0) new_alive[ni] = 0
            }

            # --- Not found in new ---
            if (ni == 0) {
                print_result(name, meth_str, "Not found in new", "Skipped")
                continue
            }

            # --- Check comparability (type, rank, shape must match) ---
            if (ref_type[ri] != new_type[ni] || \
                ref_rank[ri] != new_rank[ni] || \
                ref_shape[ri] != new_shape[ni]) {
                print_result(name, meth_str, "Mismatching data", "Error")
                continue
            }

            # --- Parse values into arrays ---
            nrv = split(ref_values[ri], rv_arr)
            nnv = split(new_values[ni], nv_arr)

            if (nrv != nnv) {
                print_result(name, meth_str, "Different value count", "Error")
                continue
            }

            if (nrv == 0) {
                print_result(name, meth_str, "0", "OK")
                continue
            }

            # --- Compute difference ---
            diff = -1
            if (cfg_meth[ci] == "element") {
                diff = element_diff(rv_arr, nv_arr, nrv, entry_type)
            } else if (cfg_meth[ci] == "vector") {
                nelem = cfg_marg[ci]
                if (nelem == -1) {
                    # Use first dimension from shape
                    split(ref_shape[ri], sdims, ",")
                    nelem = sdims[1] + 0
                }
                diff = vector_diff(rv_arr, nv_arr, nrv, nelem, entry_type)
            }

            if (diff < 0) {
                print_result(name, meth_str, "Difference building error", "Error")
                continue
            }

            # --- Compute effective tolerance with rtol ---
            eff_tol = cfg_tol[ci]
            if (cfg_rtol[ci] >= 0) {
                max_ref_mag = 0
                for (k = 1; k <= nrv; k++) {
                    v = abs_val(rv_arr[k] + 0.0)
                    if (v > max_ref_mag) max_ref_mag = v
                }
                rtol_threshold = cfg_rtol[ci] * max_ref_mag
                if (rtol_threshold > eff_tol) eff_tol = rtol_threshold
            }

            if (diff <= eff_tol) {
                print_result(name, meth_str, sprintf("%-20g", diff), "OK")
            } else {
                print_result(name, meth_str, sprintf("%-20g", diff), "Failed")
            }
        }
    }

    exit exit_code
}
'
