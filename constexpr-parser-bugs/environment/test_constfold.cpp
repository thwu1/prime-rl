
#include "vm.hpp"
#include "compiler.hpp"

// ---- Basic constant folding: pure-constant expressions produce
//      minimal bytecode (PUSH_CONST + HALT only). ----

// "42" -> [PUSH_CONST 42.0, HALT] -> len == 2
static_assert([] {
    constexpr auto p = cxvm::compile("42");
    return p.len == 2
        && p.code[0].op == cxvm::Op::PUSH_CONST
        && p.code[0].arg == 42.0
        && p.code[1].op == cxvm::Op::HALT;
}());

// "2 + 3" -> folded to [PUSH_CONST 5.0, HALT]
static_assert([] {
    constexpr auto p = cxvm::compile("2 + 3");
    return p.len == 2
        && p.code[0].op == cxvm::Op::PUSH_CONST
        && p.code[0].arg == 5.0;
}());

// "2 + 3 * 4" -> folded to [PUSH_CONST 14.0, HALT]
static_assert([] {
    constexpr auto p = cxvm::compile("2 + 3 * 4");
    return p.len == 2
        && p.code[0].op == cxvm::Op::PUSH_CONST
        && p.code[0].arg == 14.0;
}());

// "-(3 + 4)" -> folded to [PUSH_CONST -7.0, HALT]
static_assert([] {
    constexpr auto p = cxvm::compile("-(3 + 4)");
    return p.len == 2
        && p.code[0].op == cxvm::Op::PUSH_CONST
        && p.code[0].arg == -7.0;
}());

// ---- Partial folding: constant sub-trees folded, variable parts remain. ----

// "x + 2 * 3" -> [LOAD_VAR 23, PUSH_CONST 6.0, ADD, HALT] -> len == 4
static_assert([] {
    constexpr auto p = cxvm::compile("x + 2 * 3");
    return p.len == 4
        && p.code[0].op == cxvm::Op::LOAD_VAR
        && static_cast<int>(p.code[0].arg) == 23
        && p.code[1].op == cxvm::Op::PUSH_CONST
        && p.code[1].arg == 6.0
        && p.code[2].op == cxvm::Op::ADD
        && p.code[3].op == cxvm::Op::HALT;
}());

// "(1 + 2) * x" -> [PUSH_CONST 3.0, LOAD_VAR 23, MUL, HALT] -> len == 4
static_assert([] {
    constexpr auto p = cxvm::compile("(1 + 2) * x");
    return p.len == 4
        && p.code[0].op == cxvm::Op::PUSH_CONST
        && p.code[0].arg == 3.0
        && p.code[1].op == cxvm::Op::LOAD_VAR
        && p.code[2].op == cxvm::Op::MUL
        && p.code[3].op == cxvm::Op::HALT;
}());

// ---- Function folding ----

// "abs(-5)" -> folded to [PUSH_CONST 5.0, HALT]
static_assert([] {
    constexpr auto p = cxvm::compile("abs(-5)");
    return p.len == 2
        && p.code[0].op == cxvm::Op::PUSH_CONST
        && p.code[0].arg == 5.0;
}());

// "abs(x)" -> NOT folded: [LOAD_VAR, CALL_ABS, HALT]
static_assert([] {
    constexpr auto p = cxvm::compile("abs(x)");
    return p.code[0].op == cxvm::Op::LOAD_VAR
        && p.code[1].op == cxvm::Op::CALL_ABS
        && p.code[2].op == cxvm::Op::HALT;
}());

// "min(10, 4)" -> folded to [PUSH_CONST 4.0, HALT]
static_assert([] {
    constexpr auto p = cxvm::compile("min(10, 4)");
    return p.len == 2
        && p.code[0].op == cxvm::Op::PUSH_CONST
        && p.code[0].arg == 4.0;
}());

// ---- Power and modulo folding ----

// "2 ^ 3" -> [PUSH_CONST 8.0, HALT]
static_assert([] {
    constexpr auto p = cxvm::compile("2 ^ 3");
    return p.len == 2
        && p.code[0].op == cxvm::Op::PUSH_CONST
        && p.code[0].arg == 8.0;
}());

// "2 ^ 3 ^ 2" -> [PUSH_CONST 512.0, HALT] (right-to-left)
static_assert([] {
    constexpr auto p = cxvm::compile("2 ^ 3 ^ 2");
    return p.len == 2
        && p.code[0].op == cxvm::Op::PUSH_CONST
        && p.code[0].arg == 512.0;
}());

// "17 % 5" -> [PUSH_CONST 2.0, HALT]
static_assert([] {
    constexpr auto p = cxvm::compile("17 % 5");
    return p.len == 2
        && p.code[0].op == cxvm::Op::PUSH_CONST
        && p.code[0].arg == 2.0;
}());

// ---- Comparison folding ----

// "3 < 5" -> [PUSH_CONST 1.0, HALT]
static_assert([] {
    constexpr auto p = cxvm::compile("3 < 5");
    return p.len == 2
        && p.code[0].op == cxvm::Op::PUSH_CONST
        && p.code[0].arg == 1.0;
}());

// "5 < 3" -> [PUSH_CONST 0.0, HALT]
static_assert([] {
    constexpr auto p = cxvm::compile("5 < 3");
    return p.len == 2
        && p.code[0].op == cxvm::Op::PUSH_CONST
        && p.code[0].arg == 0.0;
}());

// ---- Ternary dead branch elimination ----

// "1 ? 42 : 99" -> [PUSH_CONST 42.0, HALT] (no JZ, no JMP)
static_assert([] {
    constexpr auto p = cxvm::compile("1 ? 42 : 99");
    return p.len == 2
        && p.code[0].op == cxvm::Op::PUSH_CONST
        && p.code[0].arg == 42.0;
}());

// "0 ? 42 : 99" -> [PUSH_CONST 99.0, HALT]
static_assert([] {
    constexpr auto p = cxvm::compile("0 ? 42 : 99");
    return p.len == 2
        && p.code[0].op == cxvm::Op::PUSH_CONST
        && p.code[0].arg == 99.0;
}());

// "3 < 5 ? 10 : 20" -> comparison folds, ternary folds -> [PUSH_CONST 10.0, HALT]
static_assert([] {
    constexpr auto p = cxvm::compile("3 < 5 ? 10 : 20");
    return p.len == 2
        && p.code[0].op == cxvm::Op::PUSH_CONST
        && p.code[0].arg == 10.0;
}());

// ---- Let-binding constant propagation ----

// "let x = 5 in x + 1" -> propagate x=5 -> fold 5+1 -> [PUSH_CONST 6.0, HALT]
static_assert([] {
    constexpr auto p = cxvm::compile("let x = 5 in x + 1");
    return p.len == 2
        && p.code[0].op == cxvm::Op::PUSH_CONST
        && p.code[0].arg == 6.0;
}());

// "let x = 3 + 4 in x * 2" -> init folds to 7, propagate, fold -> [PUSH_CONST 14.0, HALT]
static_assert([] {
    constexpr auto p = cxvm::compile("let x = 3 + 4 in x * 2");
    return p.len == 2
        && p.code[0].op == cxvm::Op::PUSH_CONST
        && p.code[0].arg == 14.0;
}());

// Cascading: "let x = 5 in let y = x + 1 in y * 2" -> 12
static_assert([] {
    constexpr auto p = cxvm::compile("let x = 5 in let y = x + 1 in y * 2");
    return p.len == 2
        && p.code[0].op == cxvm::Op::PUSH_CONST
        && p.code[0].arg == 12.0;
}());

int main() { return 0; }
