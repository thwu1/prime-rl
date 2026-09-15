#!/usr/bin/env python3
"""
Generate the complete constexpr expression compiler implementation.
Writes /app/include/compiler.hpp with:
  - AST-based recursive descent parser (constexpr)
  - Tree-level optimizer: constant folding, constant propagation,
    dead branch elimination
  - Bytecode code generator with jump backpatching
"""


COMPILER_HPP = r'''#ifndef CXVM_COMPILER_HPP
#define CXVM_COMPILER_HPP

#include "bytecode.hpp"
#include <string_view>

namespace cxvm {
namespace detail {

// ---- Utilities ----
constexpr bool is_digit(char c) { return c >= '0' && c <= '9'; }
constexpr bool is_alpha(char c) { return c >= 'a' && c <= 'z'; }
constexpr bool is_space(char c) {
    return c == ' ' || c == '\t' || c == '\n' || c == '\r';
}

// ---- AST node kinds ----
enum class NK : unsigned char {
    LIT, GVAR, LVAR,
    OP_ADD, OP_SUB, OP_MUL, OP_DIV, OP_MOD, OP_POW, OP_NEG,
    CMP_LT, CMP_GT, CMP_LE, CMP_GE, CMP_EQ, CMP_NE,
    FN_ABS, FN_MIN, FN_MAX, FN_SQRT,
    TERNARY, LET_BIND
};

struct Node {
    NK kind = NK::LIT;
    double val = 0.0;
    int idx = -1;
    int ch[3] = {-1, -1, -1};
};

// ---- AST pool (fixed-size, constexpr-compatible) ----
template<int N = 256>
struct Pool {
    Node nd[N]{};
    int cnt = 0;

    constexpr int add(NK k) {
        int i = cnt++;
        nd[i] = Node{};
        nd[i].kind = k;
        return i;
    }
    constexpr int lit(double v) {
        int i = add(NK::LIT); nd[i].val = v; return i;
    }
    constexpr int gvar(int index) {
        int i = add(NK::GVAR); nd[i].idx = index; return i;
    }
    constexpr int lvar(int slot) {
        int i = add(NK::LVAR); nd[i].idx = slot; return i;
    }
    constexpr int bin(NK k, int l, int r) {
        int i = add(k); nd[i].ch[0] = l; nd[i].ch[1] = r; return i;
    }
    constexpr int un(NK k, int c) {
        int i = add(k); nd[i].ch[0] = c; return i;
    }
    constexpr int tern(int c, int t, int e) {
        int i = add(NK::TERNARY);
        nd[i].ch[0] = c; nd[i].ch[1] = t; nd[i].ch[2] = e;
        return i;
    }
    constexpr int letb(int slot, int init, int body) {
        int i = add(NK::LET_BIND);
        nd[i].idx = slot; nd[i].ch[0] = init; nd[i].ch[1] = body;
        return i;
    }
};

// ---- Scope entry for let-bindings ----
struct Scope { char name; int slot; };

// ---- Recursive-descent parser ----
template<int NP = 256>
struct Parser {
    std::string_view src;
    std::size_t pos = 0;
    Pool<NP> pool;
    Scope sc[64]{};
    int sd = 0;
    int ns = 0;

    constexpr Parser(std::string_view s) : src(s) {}

    constexpr void ws() {
        while (pos < src.size() && is_space(src[pos])) ++pos;
    }
    constexpr char cc() const {
        return pos < src.size() ? src[pos] : '\0';
    }
    constexpr char pk(int o = 1) const {
        return (pos + o) < src.size() ? src[pos + o] : '\0';
    }

    constexpr bool kw(const char* w) {
        int len = 0;
        while (w[len]) {
            if (pos + len >= src.size() || src[pos + len] != w[len])
                return false;
            ++len;
        }
        if (pos + len < src.size() && is_alpha(src[pos + len]))
            return false;
        pos += len;
        return true;
    }

    constexpr bool sv_eq(std::string_view a, const char* b) const {
        int blen = 0;
        while (b[blen]) ++blen;
        if (static_cast<int>(a.size()) != blen) return false;
        for (int i = 0; i < blen; ++i)
            if (a[i] != b[i]) return false;
        return true;
    }

    constexpr double parse_num() {
        double r = 0.0;
        while (pos < src.size() && is_digit(src[pos]))
            r = r * 10.0 + static_cast<double>(src[pos++] - '0');
        if (pos < src.size() && src[pos] == '.') {
            ++pos;
            double f = 0.1;
            while (pos < src.size() && is_digit(src[pos])) {
                r += static_cast<double>(src[pos++] - '0') * f;
                f *= 0.1;
            }
        }
        return r;
    }

    constexpr int find_local(char n) const {
        for (int i = sd - 1; i >= 0; --i)
            if (sc[i].name == n) return sc[i].slot;
        return -1;
    }

    // ---- Grammar rules ----

    constexpr int p_primary() {
        ws();
        if (cc() == '(') {
            ++pos;
            int n = p_expr();
            ws();
            ++pos; // ')'
            return n;
        }
        if (is_digit(cc()) || cc() == '.') {
            return pool.lit(parse_num());
        }
        if (is_alpha(cc())) {
            std::size_t st = pos;
            while (pos < src.size() && is_alpha(src[pos])) ++pos;
            auto id = src.substr(st, pos - st);
            ws();
            // Built-in function call
            if (cc() == '(' &&
                (sv_eq(id, "abs") || sv_eq(id, "min") ||
                 sv_eq(id, "max") || sv_eq(id, "sqrt"))) {
                ++pos; // '('
                int a0 = p_expr();
                ws();
                int a1 = -1;
                if (cc() == ',') { ++pos; a1 = p_expr(); ws(); }
                ++pos; // ')'
                NK k = sv_eq(id, "abs")  ? NK::FN_ABS
                     : sv_eq(id, "min")  ? NK::FN_MIN
                     : sv_eq(id, "max")  ? NK::FN_MAX
                     :                     NK::FN_SQRT;
                return a1 >= 0 ? pool.bin(k, a0, a1) : pool.un(k, a0);
            }
            // Single-letter variable
            if (id.size() == 1) {
                int ls = find_local(id[0]);
                return ls >= 0 ? pool.lvar(ls)
                               : pool.gvar(id[0] - 'a');
            }
            // Multi-char non-function: treat first char as variable
            pos = st + 1;
            int ls = find_local(src[st]);
            return ls >= 0 ? pool.lvar(ls)
                           : pool.gvar(src[st] - 'a');
        }
        return pool.lit(0.0);
    }

    // unary: '-' unary | primary
    constexpr int p_unary() {
        ws();
        if (cc() == '-') {
            ++pos;
            return pool.un(NK::OP_NEG, p_unary());
        }
        return p_primary();
    }

    // power: unary ('^' power)?   -- right recursion = right-to-left
    constexpr int p_power() {
        int l = p_unary();
        ws();
        if (cc() == '^') {
            ++pos;
            return pool.bin(NK::OP_POW, l, p_power());
        }
        return l;
    }

    // term: power (('*'|'/'|'%') power)*
    constexpr int p_term() {
        int l = p_power();
        while (true) {
            ws();
            if      (cc() == '*') { ++pos; l = pool.bin(NK::OP_MUL, l, p_power()); }
            else if (cc() == '/') { ++pos; l = pool.bin(NK::OP_DIV, l, p_power()); }
            else if (cc() == '%') { ++pos; l = pool.bin(NK::OP_MOD, l, p_power()); }
            else break;
        }
        return l;
    }

    // additive: term (('+'|'-') term)*
    constexpr int p_add() {
        int l = p_term();
        while (true) {
            ws();
            if      (cc() == '+') { ++pos; l = pool.bin(NK::OP_ADD, l, p_term()); }
            else if (cc() == '-') { ++pos; l = pool.bin(NK::OP_SUB, l, p_term()); }
            else break;
        }
        return l;
    }

    // comparison: additive (comp_op additive)?
    constexpr int p_cmp() {
        int l = p_add();
        ws();
        if (cc() == '<' && pk() == '=') { pos += 2; return pool.bin(NK::CMP_LE, l, p_add()); }
        if (cc() == '>' && pk() == '=') { pos += 2; return pool.bin(NK::CMP_GE, l, p_add()); }
        if (cc() == '=' && pk() == '=') { pos += 2; return pool.bin(NK::CMP_EQ, l, p_add()); }
        if (cc() == '!' && pk() == '=') { pos += 2; return pool.bin(NK::CMP_NE, l, p_add()); }
        if (cc() == '<') { ++pos; return pool.bin(NK::CMP_LT, l, p_add()); }
        if (cc() == '>') { ++pos; return pool.bin(NK::CMP_GT, l, p_add()); }
        return l;
    }

    // ternary: comparison ('?' expr ':' expr)?
    constexpr int p_tern() {
        int c = p_cmp();
        ws();
        if (cc() == '?') {
            ++pos;
            int t = p_expr();
            ws();
            ++pos; // ':'
            int e = p_expr();
            return pool.tern(c, t, e);
        }
        return c;
    }

    // let_expr: 'let' IDENT '=' expr 'in' expr | ternary
    constexpr int p_let() {
        ws();
        std::size_t sv = pos;
        if (kw("let")) {
            ws();
            char vn = src[pos]; ++pos;
            ws(); ++pos; // '='
            int init = p_expr();
            ws(); kw("in");
            int slot = ns++;
            sc[sd++] = {vn, slot};
            int body = p_expr();
            --sd;
            return pool.letb(slot, init, body);
        }
        pos = sv;
        return p_tern();
    }

    constexpr int p_expr() { return p_let(); }
};

// ---- Optimizer math helpers ----
constexpr double opt_abs(double x) { return x < 0 ? -x : x; }
constexpr double opt_min(double a, double b) { return a < b ? a : b; }
constexpr double opt_max(double a, double b) { return a > b ? a : b; }

constexpr double opt_sqrt(double x) {
    if (x <= 0) return 0;
    double g = x;
    for (int i = 0; i < 64; ++i) g = (g + x / g) * 0.5;
    return g;
}

constexpr double opt_pow(double base, double exp) {
    if (exp == 0) return 1;
    if (base == 0) return 0;
    bool neg = exp < 0;
    double ae = neg ? -exp : exp;
    int ei = static_cast<int>(ae);
    if (static_cast<double>(ei) == ae) {
        double r = 1, b = base;
        while (ei > 0) { if (ei & 1) r *= b; b *= b; ei >>= 1; }
        return neg ? 1.0 / r : r;
    }
    double lnb = 0;
    {
        double y = (base - 1) / (base + 1), y2 = y * y, t = y;
        for (int i = 0; i < 40; ++i) { lnb += t / (2*i+1); t *= y2; }
        lnb *= 2;
    }
    double z = ae * lnb, r = 1, t = 1;
    for (int i = 1; i < 40; ++i) { t *= z / i; r += t; }
    return neg ? 1.0 / r : r;
}

constexpr double opt_fmod(double a, double b) {
    if (b == 0) return 0;
    return a - static_cast<double>(static_cast<int>(a / b)) * b;
}

// ---- Constant propagation through let-bindings ----
template<int NP>
constexpr void subst(Pool<NP>& p, int n, int slot, double v) {
    if (n < 0) return;
    auto& nd = p.nd[n];
    if (nd.kind == NK::LVAR && nd.idx == slot) {
        nd.kind = NK::LIT;
        nd.val = v;
        return;
    }
    // Don't substitute into a nested let that shadows the same slot
    if (nd.kind == NK::LET_BIND && nd.idx == slot) {
        subst(p, nd.ch[0], slot, v);
        return;
    }
    for (int i = 0; i < 3; ++i)
        subst(p, nd.ch[i], slot, v);
}

// ---- AST optimizer ----
template<int NP>
constexpr int opt(Pool<NP>& p, int n) {
    if (n < 0) return n;
    auto& nd = p.nd[n];

    // Recursively optimize children
    for (int i = 0; i < 3; ++i)
        nd.ch[i] = opt(p, nd.ch[i]);

    // --- Binary constant fold (arithmetic, comparisons, min, max) ---
    auto is_foldable_bin = [](NK k) {
        return k == NK::OP_ADD  || k == NK::OP_SUB
            || k == NK::OP_MUL || k == NK::OP_DIV
            || k == NK::OP_MOD || k == NK::OP_POW
            || k == NK::CMP_LT || k == NK::CMP_GT
            || k == NK::CMP_LE || k == NK::CMP_GE
            || k == NK::CMP_EQ || k == NK::CMP_NE
            || k == NK::FN_MIN || k == NK::FN_MAX;
    };

    if (is_foldable_bin(nd.kind) && nd.ch[0] >= 0 && nd.ch[1] >= 0
        && p.nd[nd.ch[0]].kind == NK::LIT
        && p.nd[nd.ch[1]].kind == NK::LIT) {
        double a = p.nd[nd.ch[0]].val;
        double b = p.nd[nd.ch[1]].val;
        double r = 0;
        NK saved = nd.kind;
        switch (saved) {
        case NK::OP_ADD: r = a + b; break;
        case NK::OP_SUB: r = a - b; break;
        case NK::OP_MUL: r = a * b; break;
        case NK::OP_DIV: r = a / b; break;
        case NK::OP_MOD: r = opt_fmod(a, b); break;
        case NK::OP_POW: r = opt_pow(a, b); break;
        case NK::CMP_LT: r = (a < b) ? 1.0 : 0.0; break;
        case NK::CMP_GT: r = (a > b) ? 1.0 : 0.0; break;
        case NK::CMP_LE: r = (a <= b) ? 1.0 : 0.0; break;
        case NK::CMP_GE: r = (a >= b) ? 1.0 : 0.0; break;
        case NK::CMP_EQ: r = (a == b) ? 1.0 : 0.0; break;
        case NK::CMP_NE: r = (a != b) ? 1.0 : 0.0; break;
        case NK::FN_MIN: r = opt_min(a, b); break;
        case NK::FN_MAX: r = opt_max(a, b); break;
        default: break;
        }
        nd.kind = NK::LIT;
        nd.val = r;
        nd.ch[0] = nd.ch[1] = -1;
    }

    // --- Unary constant fold ---
    if ((nd.kind == NK::OP_NEG || nd.kind == NK::FN_ABS
         || nd.kind == NK::FN_SQRT)
        && nd.ch[0] >= 0 && p.nd[nd.ch[0]].kind == NK::LIT) {
        double v = p.nd[nd.ch[0]].val;
        double r = 0;
        switch (nd.kind) {
        case NK::OP_NEG:  r = -v; break;
        case NK::FN_ABS:  r = opt_abs(v); break;
        case NK::FN_SQRT: r = opt_sqrt(v); break;
        default: break;
        }
        nd.kind = NK::LIT;
        nd.val = r;
        nd.ch[0] = -1;
    }

    // --- Ternary with constant condition: dead branch elimination ---
    if (nd.kind == NK::TERNARY && nd.ch[0] >= 0
        && p.nd[nd.ch[0]].kind == NK::LIT) {
        return p.nd[nd.ch[0]].val != 0.0 ? nd.ch[1] : nd.ch[2];
    }

    // --- Let-binding with constant init: constant propagation ---
    if (nd.kind == NK::LET_BIND && nd.ch[0] >= 0
        && p.nd[nd.ch[0]].kind == NK::LIT) {
        double val = p.nd[nd.ch[0]].val;
        subst(p, nd.ch[1], nd.idx, val);
        nd.ch[1] = opt(p, nd.ch[1]);
        return nd.ch[1];
    }

    return n;
}

// ---- Bytecode code generator ----
template<int ML, int NP>
constexpr void gen(const Pool<NP>& p, int n, Program<ML>& prog) {
    if (n < 0) return;
    const auto& nd = p.nd[n];

    switch (nd.kind) {
    case NK::LIT:
        prog.emit(Op::PUSH_CONST, nd.val);
        break;
    case NK::GVAR:
        prog.emit(Op::LOAD_VAR, static_cast<double>(nd.idx));
        break;
    case NK::LVAR:
        prog.emit(Op::LOAD_LOCAL, static_cast<double>(nd.idx));
        break;

    case NK::OP_ADD: case NK::OP_SUB: case NK::OP_MUL: case NK::OP_DIV:
    case NK::OP_MOD: case NK::OP_POW:
        gen(p, nd.ch[0], prog);
        gen(p, nd.ch[1], prog);
        switch (nd.kind) {
        case NK::OP_ADD: prog.emit(Op::ADD); break;
        case NK::OP_SUB: prog.emit(Op::SUB); break;
        case NK::OP_MUL: prog.emit(Op::MUL); break;
        case NK::OP_DIV: prog.emit(Op::DIV); break;
        case NK::OP_MOD: prog.emit(Op::MOD); break;
        case NK::OP_POW: prog.emit(Op::POW); break;
        default: break;
        }
        break;

    case NK::CMP_LT: case NK::CMP_GT: case NK::CMP_LE: case NK::CMP_GE:
    case NK::CMP_EQ: case NK::CMP_NE:
        gen(p, nd.ch[0], prog);
        gen(p, nd.ch[1], prog);
        switch (nd.kind) {
        case NK::CMP_LT: prog.emit(Op::CMP_LT); break;
        case NK::CMP_GT: prog.emit(Op::CMP_GT); break;
        case NK::CMP_LE: prog.emit(Op::CMP_LE); break;
        case NK::CMP_GE: prog.emit(Op::CMP_GE); break;
        case NK::CMP_EQ: prog.emit(Op::CMP_EQ); break;
        case NK::CMP_NE: prog.emit(Op::CMP_NE); break;
        default: break;
        }
        break;

    case NK::OP_NEG:
        gen(p, nd.ch[0], prog);
        prog.emit(Op::NEG);
        break;
    case NK::FN_ABS:
        gen(p, nd.ch[0], prog);
        prog.emit(Op::CALL_ABS);
        break;
    case NK::FN_SQRT:
        gen(p, nd.ch[0], prog);
        prog.emit(Op::CALL_SQRT);
        break;
    case NK::FN_MIN:
        gen(p, nd.ch[0], prog);
        gen(p, nd.ch[1], prog);
        prog.emit(Op::CALL_MIN);
        break;
    case NK::FN_MAX:
        gen(p, nd.ch[0], prog);
        gen(p, nd.ch[1], prog);
        prog.emit(Op::CALL_MAX);
        break;

    case NK::TERNARY: {
        gen(p, nd.ch[0], prog);
        int jz = prog.emit_placeholder(Op::JZ);
        gen(p, nd.ch[1], prog);
        int jm = prog.emit_placeholder(Op::JMP);
        prog.patch(jz, static_cast<double>(prog.len));
        gen(p, nd.ch[2], prog);
        prog.patch(jm, static_cast<double>(prog.len));
        break;
    }

    case NK::LET_BIND:
        gen(p, nd.ch[0], prog);
        prog.emit(Op::STORE_LOCAL, static_cast<double>(nd.idx));
        gen(p, nd.ch[1], prog);
        break;
    }
}

} // namespace detail

// ---- Public API ----
template<int MaxLen = 256>
constexpr Program<MaxLen> compile(std::string_view expr) {
    detail::Parser<256> parser(expr);
    int root = parser.p_expr();
    root = detail::opt(parser.pool, root);
    Program<MaxLen> prog;
    detail::gen<MaxLen, 256>(parser.pool, root, prog);
    prog.finalize();
    return prog;
}

} // namespace cxvm

#endif // CXVM_COMPILER_HPP
'''

with open('/app/include/compiler.hpp', 'w') as f:
    f.write(COMPILER_HPP.lstrip('\n'))

print("compiler.hpp written successfully.")
