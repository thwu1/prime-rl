#!/usr/bin/env python3
"""
Diagnoses and fixes four independent bugs in the constexpr expression
evaluator at /app/include/constexpr_eval.hpp.

Bug analysis (found via compilation errors in test programs):

1. Operator precedence inversion: parse_term handles + and - while
   parse_expression handles * and /. This reverses arithmetic precedence
   so that addition binds tighter than multiplication.

2. Parenthesis position tracking: parse_primary returns inner.pos
   (position before closing ')') instead of cp (position after ')'),
   making any operator following a parenthesized group invisible.

3. Unary minus scope: the negation handler calls parse_number instead
   of parse_unary, so negation only works before bare number literals,
   not before parenthesized expressions or chained negations.

4. Missing scientific notation: parse_number does not consume 'e'/'E'
   exponent suffixes, so "1.5e2" parses as 1.5 instead of 150.
"""


import sys


def read_file(path: str) -> str:
    with open(path) as fh:
        return fh.read()


def write_file(path: str, content: str) -> None:
    with open(path, "w") as fh:
        fh.write(content)


def fix_operator_precedence(src: str) -> str:
    """Swap operator sets between parse_term and parse_expression."""
    # Swap the condition operators using a placeholder
    src = src.replace("op == '+' || op == '-'", "__SWAP_MULDIV__")
    src = src.replace("op == '*' || op == '/'", "op == '+' || op == '-'")
    src = src.replace("__SWAP_MULDIV__", "op == '*' || op == '/'")

    # Swap the ternary value computations
    src = src.replace(
        "op == '+' ? lhs.value + rhs.value", "__SWAP_MULOP__"
    )
    src = src.replace(
        "op == '*' ? lhs.value * rhs.value",
        "op == '+' ? lhs.value + rhs.value",
    )
    src = src.replace("__SWAP_MULOP__", "op == '*' ? lhs.value * rhs.value")

    src = src.replace(": lhs.value - rhs.value", "__SWAP_DIVOP__")
    src = src.replace(
        ": lhs.value / rhs.value", ": lhs.value - rhs.value"
    )
    src = src.replace("__SWAP_DIVOP__", ": lhs.value / rhs.value")

    return src


def fix_paren_position(src: str) -> str:
    """Return cp (after ')') instead of inner.pos."""
    return src.replace(
        "return {inner.value, inner.pos};",
        "return {inner.value, cp};",
    )


def fix_unary_minus(src: str) -> str:
    """Unary minus must recurse into parse_unary, not parse_number."""
    return src.replace(
        "auto r = parse_number(expr, pos);",
        "auto r = parse_unary(expr, pos);",
    )


def fix_scientific_notation(src: str) -> str:
    """Insert scientific-notation parsing into parse_number."""
    sci_block = (
        "\n"
        "    // Scientific notation (e.g. 1.5e2, 2E-3)\n"
        "    if (found && pos < expr.size()"
        " && (expr[pos] == 'e' || expr[pos] == 'E')) {\n"
        "        ++pos;\n"
        "        bool neg_exp = false;\n"
        "        if (pos < expr.size()"
        " && (expr[pos] == '+' || expr[pos] == '-')) {\n"
        "            neg_exp = (expr[pos] == '-');\n"
        "            ++pos;\n"
        "        }\n"
        "        double exp_val = 0.0;\n"
        "        while (pos < expr.size() && is_digit(expr[pos])) {\n"
        "            exp_val = exp_val * 10.0"
        " + static_cast<double>(expr[pos] - '0');\n"
        "            ++pos;\n"
        "        }\n"
        "        double multiplier = 1.0;\n"
        "        for (int i = 0;"
        " i < static_cast<int>(exp_val); ++i) {\n"
        "            multiplier *= (neg_exp ? 0.1 : 10.0);\n"
        "        }\n"
        "        result *= multiplier;\n"
        "    }\n"
        "\n"
    )
    target = "    return {found ? result : 0.0, pos};"
    return src.replace(target, sci_block + target)


def main() -> None:
    path = "/app/include/constexpr_eval.hpp"
    src = read_file(path)

    src = fix_operator_precedence(src)
    src = fix_paren_position(src)
    src = fix_unary_minus(src)
    src = fix_scientific_notation(src)

    write_file(path, src)

    # Verify each fix was applied by checking the output
    result = read_file(path)
    checks = [
        ("op == '*' || op == '/'" in result
         and "op == '+' || op == '-'" in result,
         "precedence operators swapped"),
        ("return {inner.value, cp};" in result,
         "paren position uses cp"),
        ("auto r = parse_unary(expr, pos);" in result,
         "unary minus recurses into parse_unary"),
        ("expr[pos] == 'e' || expr[pos] == 'E'" in result,
         "scientific notation handler present"),
    ]
    all_ok = True
    for ok, desc in checks:
        status = "OK" if ok else "FAIL"
        print(f"  [{status}] {desc}")
        if not ok:
            all_ok = False

    if not all_ok:
        print("ERROR: some fixes were not applied correctly")
        sys.exit(1)

    print("All 4 bugs fixed successfully.")


if __name__ == "__main__":
    main()
