#!/usr/bin/env python3
"""
Apply targeted fixes to /app/arith.sh to correct eight categories of bugs:
1. val_to_char uppercase ASCII offset (v+55 -> v+29)
2. to_base missing zero and negative handling
3. fp_parse missing fractional zero-padding
4. fp_mul naive overflow -> algebraic splitting
5. fp_div naive overflow -> algebraic splitting
6. fp_sqrt wrong scaling (val -> val*scale) + overflow-safe Newton
7. fp_pow naive overflow -> algebraic splitting
8. sanitize signed-number 10# pitfall
"""


import re

with open("/app/arith.sh", "r") as f:
    code = f.read()

# ---------- Fix 1: val_to_char uppercase offset ----------
# v + 55 gives ASCII 91 ('[') for v=36; correct is v + 29 -> ASCII 65 ('A')
code = code.replace("v + 55", "v + 29")

# ---------- Fix 2: to_base zero and negative handling ----------
old_to_base_loop = """\
    while (( dec > 0 )); do"""

new_to_base_loop = """\
    if (( dec == 0 )); then
        echo "0"
        return
    fi

    local sign=""
    if (( dec < 0 )); then
        sign="-"
        dec=$(( -dec ))
    fi

    while (( dec > 0 )); do"""

code = code.replace(old_to_base_loop, new_to_base_loop, 1)

# Update the echo at the end of to_base to include the sign
code = code.replace(
    '    echo "$result"\n}\n\n# Convert a number between',
    '    echo "${sign}${result}"\n}\n\n# Convert a number between',
    1,
)

# ---------- Fix 3: fp_parse fractional zero-padding ----------
old_parse = """\
    # Truncate to precision width
    frac_str="${frac_str:0:$prec}\""""

new_parse = """\
    # Right-pad fractional part with trailing zeros to precision width
    while (( ${#frac_str} < prec )); do
        frac_str="${frac_str}0"
    done
    # Truncate to precision width
    frac_str="${frac_str:0:$prec}\""""

code = code.replace(old_parse, new_parse, 1)

# ---------- Fix 4: fp_mul split multiplication ----------
old_mul = """\
    # Scale the product back
    fp_format "$(( a * b / scale ))" "$prec\""""

new_mul = """\
    # Overflow-safe split multiplication
    local a_hi=$(( a / scale )) a_lo=$(( a % scale ))
    local product=$(( a_hi * b + a_lo * b / scale ))
    fp_format "$product" "$prec\""""

code = code.replace(old_mul, new_mul, 1)

# ---------- Fix 5: fp_div split division ----------
old_div = """\
    # Scale the dividend for precision
    fp_format "$(( a * scale / b ))" "$prec\""""

new_div = """\
    # Overflow-safe split division
    local q_main=$(( a / b ))
    local r_main=$(( a % b ))
    local quotient=$(( q_main * scale + r_main * scale / b ))
    fp_format "$quotient" "$prec\""""

code = code.replace(old_div, new_div, 1)

# ---------- Fix 6: fp_sqrt correct scaling + overflow-safe Newton ----------
old_sqrt = """\
    # Newton's method for integer square root
    local x=$val x1
    while true; do
        x1=$(( (x + val / x) / 2 ))
        if (( x1 >= x )); then break; fi
        x=$x1
    done

    fp_format "$x" "$prec\""""

new_sqrt = """\
    local scale=1
    for ((i = 0; i < prec; i++)); do
        scale=$(( scale * 10 ))
    done

    # Compute floor(sqrt(val * scale)) using overflow-safe Newton
    # max(val, scale) is always >= sqrt(val * scale), so it is a valid overestimate
    local x=$val
    if (( scale > x )); then x=$scale; fi

    # Newton: x = (x + val*scale/x) / 2
    # Overflow-safe: val*scale/x = (val/x)*scale + (val%x)*scale/x
    local x1 q r nox
    while true; do
        q=$(( val / x ))
        r=$(( val % x ))
        nox=$(( q * scale + r * scale / x ))
        x1=$(( (x + nox) / 2 ))
        if (( x1 >= x )); then break; fi
        x=$x1
    done

    fp_format "$x" "$prec\""""

code = code.replace(old_sqrt, new_sqrt, 1)

# ---------- Fix 7: fp_pow overflow-safe multiplication ----------
old_pow = """\
    local result=$scale
    for ((i = 0; i < exp; i++)); do
        result=$(( result * base / scale ))
    done

    fp_format "$result" "$prec\""""

new_pow = """\
    local result=$scale
    for ((i = 0; i < exp; i++)); do
        # Overflow-safe: result * base / scale
        local r_hi=$(( result / scale ))
        local r_lo=$(( result % scale ))
        result=$(( r_hi * base + r_lo * base / scale ))
    done

    fp_format "$result" "$prec\""""

code = code.replace(old_pow, new_pow, 1)

# ---------- Fix 8: sanitize sign handling ----------
old_san = """\
    local n="$1"
    # Force base-10 interpretation to strip octal
    printf '%d\\n' "$(( 10#$n ))\""""

new_san = """\
    local n="$1"
    local sign=""
    if [[ "$n" == -* ]]; then
        sign="-"
        n="${n#-}"
    elif [[ "$n" == +* ]]; then
        n="${n#+}"
    fi
    # Force base-10 interpretation to strip octal
    printf '%s%d\\n' "$sign" "$(( 10#$n ))\""""

code = code.replace(old_san, new_san, 1)

with open("/app/arith.sh", "w") as f:
    f.write(code)

print("All fixes applied to /app/arith.sh")
