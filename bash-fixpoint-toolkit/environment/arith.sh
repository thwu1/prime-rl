#!/bin/bash

# Pure-bash arithmetic toolkit
# Supports: base conversion (2-64), fixed-point arithmetic, octal sanitization
# Constraint: only bash arithmetic — no bc, dc, awk, python, perl

# ============================================================
# Digit Mapping
# ============================================================

# Map a numeric value (0-63) to its digit character for base-N output
# Digit alphabet: 0-9 a-z A-Z @ _
val_to_char() {
    local v=$1
    if (( v < 0 || v > 63 )); then
        echo "error: digit value $v out of range 0-63" >&2
        return 1
    elif (( v <= 9 )); then
        printf '%d' "$v"
    elif (( v <= 35 )); then
        printf "\\$(printf '%03o' "$(( v + 87 ))")"   # a(10)..z(35)
    elif (( v <= 61 )); then
        printf "\\$(printf '%03o' "$(( v + 55 ))")"   # A(36)..Z(61)
    elif (( v == 62 )); then
        printf '@'
    else
        printf '_'
    fi
}

# ============================================================
# Base Conversion
# ============================================================

# Parse a base-N number to decimal using bash builtin arithmetic
from_base() {
    local base=$1 num="$2"
    if (( base < 2 || base > 64 )); then
        echo "error: base must be 2-64" >&2
        return 1
    fi
    printf '%d\n' "$(( ${base}#${num} ))"
}

# Convert a decimal integer to its base-N string representation
to_base() {
    local base=$1 dec=$2
    local result="" remainder

    if (( base < 2 || base > 64 )); then
        echo "error: base must be 2-64" >&2
        return 1
    fi

    while (( dec > 0 )); do
        remainder=$(( dec % base ))
        result="$(val_to_char "$remainder")${result}"
        dec=$(( dec / base ))
    done

    echo "$result"
}

# Convert a number between two arbitrary bases
base_convert() {
    local from_b=$1 to_b=$2 num="$3"
    local decimal
    decimal=$(from_base "$from_b" "$num") || return 1
    to_base "$to_b" "$decimal"
}

# ============================================================
# Fixed-Point Arithmetic
# ============================================================

# Parse a decimal string (e.g. "1.25", "-3.5", "10") into a scaled integer.
# With precision P, the value 1.25 becomes 125 (scale = 10^P).
fp_parse() {
    local num="$1" prec="$2"
    local scale=1 sign=1 integer frac_str i

    if [[ "$num" == -* ]]; then
        sign=-1
        num="${num#-}"
    fi

    for ((i = 0; i < prec; i++)); do
        scale=$(( scale * 10 ))
    done

    if [[ "$num" == *.* ]]; then
        integer="${num%.*}"
        frac_str="${num#*.}"
    else
        integer="$num"
        frac_str=""
    fi

    [[ -z "$integer" ]] && integer=0

    # Truncate to precision width
    frac_str="${frac_str:0:$prec}"

    # Handle empty fractional part
    [[ -z "$frac_str" ]] && frac_str=0

    # Force base-10 interpretation
    frac_str=$(( 10#$frac_str ))

    printf '%d\n' "$(( sign * (integer * scale + frac_str) ))"
}

# Format a scaled integer back to a decimal string with the given precision.
fp_format() {
    local val=$1 prec=$2
    local scale=1 sign="" integer_part frac_part i

    for ((i = 0; i < prec; i++)); do
        scale=$(( scale * 10 ))
    done

    if (( val < 0 )); then
        sign="-"
        val=$(( -val ))
    fi

    integer_part=$(( val / scale ))
    frac_part=$(( val % scale ))

    printf '%s%d.%0*d\n' "$sign" "$integer_part" "$prec" "$frac_part"
}

# Fixed-point addition
fp_add() {
    local a_str="$1" b_str="$2" prec="$3"
    local a b
    a=$(fp_parse "$a_str" "$prec")
    b=$(fp_parse "$b_str" "$prec")
    fp_format "$(( a + b ))" "$prec"
}

# Fixed-point multiplication
fp_mul() {
    local a_str="$1" b_str="$2" prec="$3"
    local a b scale=1 i

    a=$(fp_parse "$a_str" "$prec")
    b=$(fp_parse "$b_str" "$prec")

    for ((i = 0; i < prec; i++)); do
        scale=$(( scale * 10 ))
    done

    # Scale the product back
    fp_format "$(( a * b / scale ))" "$prec"
}

# Fixed-point division
fp_div() {
    local a_str="$1" b_str="$2" prec="$3"
    local a b scale=1 i

    a=$(fp_parse "$a_str" "$prec")
    b=$(fp_parse "$b_str" "$prec")

    if (( b == 0 )); then
        echo "error: division by zero" >&2
        return 1
    fi

    for ((i = 0; i < prec; i++)); do
        scale=$(( scale * 10 ))
    done

    # Scale the dividend for precision
    fp_format "$(( a * scale / b ))" "$prec"
}

# Fixed-point square root
fp_sqrt() {
    local val_str="$1" prec="$2"
    local val
    val=$(fp_parse "$val_str" "$prec")

    if (( val < 0 )); then
        echo "error: square root of negative number" >&2
        return 1
    fi
    if (( val == 0 )); then
        fp_format 0 "$prec"
        return
    fi

    # Newton's method for integer square root
    local x=$val x1
    while true; do
        x1=$(( (x + val / x) / 2 ))
        if (( x1 >= x )); then break; fi
        x=$x1
    done

    fp_format "$x" "$prec"
}

# Fixed-point integer exponentiation
fp_pow() {
    local base_str="$1" exp="$2" prec="$3"
    local scale=1 i

    for ((i = 0; i < prec; i++)); do
        scale=$(( scale * 10 ))
    done

    local base
    base=$(fp_parse "$base_str" "$prec")

    if (( exp == 0 )); then
        fp_format "$scale" "$prec"
        return
    fi

    local result=$scale
    for ((i = 0; i < exp; i++)); do
        result=$(( result * base / scale ))
    done

    fp_format "$result" "$prec"
}

# ============================================================
# Sanitize
# ============================================================

# Interpret a possibly zero-padded number string as base-10
sanitize() {
    local n="$1"
    # Force base-10 interpretation to strip octal
    printf '%d\n' "$(( 10#$n ))"
}

# ============================================================
# Main Dispatcher
# ============================================================

case "${1:-}" in
    from_base)    shift; from_base "$@" ;;
    to_base)      shift; to_base "$@" ;;
    base_convert) shift; base_convert "$@" ;;
    fp_add)       shift; fp_add "$@" ;;
    fp_mul)       shift; fp_mul "$@" ;;
    fp_div)       shift; fp_div "$@" ;;
    fp_sqrt)      shift; fp_sqrt "$@" ;;
    fp_pow)       shift; fp_pow "$@" ;;
    sanitize)     shift; sanitize "$@" ;;
    *)
        echo "usage: $(basename "$0") {from_base|to_base|base_convert|fp_add|fp_mul|fp_div|fp_sqrt|fp_pow|sanitize} args..." >&2
        exit 1
        ;;
esac
