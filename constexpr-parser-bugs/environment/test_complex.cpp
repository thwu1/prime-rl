
#include "vm.hpp"
#include "compiler.hpp"

// --- Complex expression mixing functions and variables ---
static_assert([] {
    constexpr auto p = cxvm::compile("max(a * 2, b + 3) - abs(c)");
    cxvm::Environment env;
    env.set(0, 5.0);   // a=5
    env.set(1, 8.0);   // b=8
    env.set(2, -3.0);  // c=-3
    // max(10, 11) - abs(-3) = 11 - 3 = 8
    return cxvm::execute(p, env);
}() == 8.0);

// --- Deeply nested parentheses, fully constant ---
static_assert([] {
    constexpr auto p = cxvm::compile("((2 + 3) * (4 - 1)) / 5");
    return cxvm::execute(p);
}() == 3.0);

// Verify full folding of above
static_assert([] {
    constexpr auto p = cxvm::compile("((2 + 3) * (4 - 1)) / 5");
    return p.len == 2
        && p.code[0].op == cxvm::Op::PUSH_CONST
        && p.code[0].arg == 3.0;
}());

// --- Mixed folding in complex expression ---
// "x * (3 + 4) + (10 - 2) / 2" with x=2
// constant folds: (3+4)=7, (10-2)/2=4
// bytecode: LOAD_VAR x, PUSH_CONST 7, MUL, PUSH_CONST 4, ADD, HALT -> len 6
static_assert([] {
    constexpr auto p = cxvm::compile("x * (3 + 4) + (10 - 2) / 2");
    cxvm::Environment env;
    env.set(23, 2.0);
    return cxvm::execute(p, env);
}() == 18.0);

static_assert([] {
    constexpr auto p = cxvm::compile("x * (3 + 4) + (10 - 2) / 2");
    return p.len == 6;
}());

// --- sqrt with variable expression ---
static_assert([] {
    constexpr auto p = cxvm::compile("sqrt(x * x + y * y)");
    cxvm::Environment env;
    env.set(23, 3.0);  // x=3
    env.set(24, 4.0);  // y=4
    double r = cxvm::execute(p, env);
    return r > 4.999 && r < 5.001;
}());

// --- Multiple variables in function args ---
static_assert([] {
    constexpr auto p = cxvm::compile("min(a + b, c * d)");
    cxvm::Environment env;
    env.set(0, 3.0);  // a
    env.set(1, 9.0);  // b  -> a+b=12
    env.set(2, 4.0);  // c
    env.set(3, 2.0);  // d  -> c*d=8
    return cxvm::execute(p, env);
}() == 8.0);

// --- Chain of operations with partial folding ---
static_assert([] {
    constexpr auto p = cxvm::compile("a * 10 + 5 * 2 - 3");
    cxvm::Environment env;
    env.set(0, 7.0);
    // 7*10 + 10 - 3 = 77
    return cxvm::execute(p, env);
}() == 77.0);

// --- Complex: ternary + let + power ---
static_assert([] {
    constexpr auto p = cxvm::compile("let n = 3 in n ^ 2 > 8 ? n : -n");
    return cxvm::execute(p);
}() == 3.0);  // n=3, 9>8 is true, so 3

// --- Complex: let with comparison and ternary, variable init ---
static_assert([] {
    constexpr auto p = cxvm::compile("let d = x - y in d > 0 ? d : -d");
    cxvm::Environment env;
    env.set(23, 3.0);   // x
    env.set(24, 10.0);  // y
    // d = 3-10 = -7, -7 > 0 is false, so -(-7) = 7
    return cxvm::execute(p, env);
}() == 7.0);

// --- Power with modulo and comparison ---
static_assert([] {
    constexpr auto p = cxvm::compile("2 ^ 10 % 100");
    return cxvm::execute(p);
}() == 24.0);  // 2^10 = 1024, 1024 % 100 = 24

// --- Nested ternary with let ---
static_assert([] {
    constexpr auto p = cxvm::compile(
        "let v = x in v < 0 ? -1 : v > 0 ? 1 : 0");
    cxvm::Environment env;
    env.set(23, -42.0);
    return cxvm::execute(p, env);
}() == -1.0);

int main() { return 0; }
