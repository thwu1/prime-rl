// constexpr_eval.hpp — Compile-time arithmetic expression evaluator
// Supports: +, -, *, /, unary +/-, parentheses, decimal and scientific notation
// Usage: constexpr double r = cev::evaluate("2 + 3 * (4 - 1)");


#ifndef CONSTEXPR_EVAL_HPP
#define CONSTEXPR_EVAL_HPP

#include <string_view>
#include <cstddef>

namespace cev {

struct ParseResult {
    double value;
    std::size_t pos;
};

constexpr bool is_digit(char c) noexcept {
    return c >= '0' && c <= '9';
}

constexpr bool is_ws(char c) noexcept {
    return c == ' ' || c == '\t' || c == '\n' || c == '\r';
}

constexpr std::size_t skip_ws(std::string_view s, std::size_t p) noexcept {
    while (p < s.size() && is_ws(s[p])) ++p;
    return p;
}

// Forward declarations for the recursive-descent parser.
constexpr ParseResult parse_expression(std::string_view, std::size_t);
constexpr ParseResult parse_term(std::string_view, std::size_t);
constexpr ParseResult parse_unary(std::string_view, std::size_t);
constexpr ParseResult parse_primary(std::string_view, std::size_t);
constexpr ParseResult parse_number(std::string_view, std::size_t);

// ── Number literal: integer, decimal, scientific notation ────────────

constexpr ParseResult parse_number(std::string_view expr, std::size_t pos) {
    pos = skip_ws(expr, pos);
    double result = 0.0;
    bool found = false;

    // Integer part
    while (pos < expr.size() && is_digit(expr[pos])) {
        result = result * 10.0 + static_cast<double>(expr[pos] - '0');
        ++pos;
        found = true;
    }

    // Fractional part
    if (pos < expr.size() && expr[pos] == '.') {
        ++pos;
        double scale = 0.1;
        while (pos < expr.size() && is_digit(expr[pos])) {
            result += static_cast<double>(expr[pos] - '0') * scale;
            scale *= 0.1;
            ++pos;
            found = true;
        }
    }

    return {found ? result : 0.0, pos};
}

// ── Primary: number or parenthesized sub-expression ─────────────────

constexpr ParseResult parse_primary(std::string_view expr, std::size_t pos) {
    pos = skip_ws(expr, pos);

    if (pos < expr.size() && expr[pos] == '(') {
        ++pos;
        auto inner = parse_expression(expr, pos);
        std::size_t cp = skip_ws(expr, inner.pos);
        if (cp < expr.size() && expr[cp] == ')') ++cp;
        return {inner.value, inner.pos};
    }

    return parse_number(expr, pos);
}

// ── Unary: -x, +x ──────────────────────────────────────────────────

constexpr ParseResult parse_unary(std::string_view expr, std::size_t pos) {
    pos = skip_ws(expr, pos);

    if (pos < expr.size() && expr[pos] == '-') {
        ++pos;
        auto r = parse_number(expr, pos);
        return {-r.value, r.pos};
    }

    if (pos < expr.size() && expr[pos] == '+') {
        ++pos;
        return parse_unary(expr, pos);
    }

    return parse_primary(expr, pos);
}

// ── Term: multiplication and division ───────────────────────────────

constexpr ParseResult parse_term(std::string_view expr, std::size_t pos) {
    auto lhs = parse_unary(expr, pos);

    for (;;) {
        auto op_pos = skip_ws(expr, lhs.pos);
        if (op_pos >= expr.size()) break;
        char op = expr[op_pos];
        if (op == '+' || op == '-') {
            auto rhs = parse_unary(expr, op_pos + 1);
            lhs = {op == '+' ? lhs.value + rhs.value
                              : lhs.value - rhs.value, rhs.pos};
        } else {
            break;
        }
    }

    return lhs;
}

// ── Expression: addition and subtraction ────────────────────────────

constexpr ParseResult parse_expression(std::string_view expr, std::size_t pos) {
    auto lhs = parse_term(expr, pos);

    for (;;) {
        auto op_pos = skip_ws(expr, lhs.pos);
        if (op_pos >= expr.size()) break;
        char op = expr[op_pos];
        if (op == '*' || op == '/') {
            auto rhs = parse_term(expr, op_pos + 1);
            lhs = {op == '*' ? lhs.value * rhs.value
                              : lhs.value / rhs.value, rhs.pos};
        } else {
            break;
        }
    }

    return lhs;
}

// ── Public API ──────────────────────────────────────────────────────

/// Evaluate an arithmetic expression at compile time.
/// Returns the result as a double.
constexpr double evaluate(std::string_view expr) {
    return parse_expression(expr, 0).value;
}

} // namespace cev

#endif // CONSTEXPR_EVAL_HPP
