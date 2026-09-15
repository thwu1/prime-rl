
#include "vm.hpp"
#include "compiler.hpp"

// --- Single variable ---
static_assert([] {
    constexpr auto p = cxvm::compile("x");
    cxvm::Environment env;
    env.set(23, 7.0);  // x = index 23
    return cxvm::execute(p, env);
}() == 7.0);

// --- Variable arithmetic ---
static_assert([] {
    constexpr auto p = cxvm::compile("x + y");
    cxvm::Environment env;
    env.set(23, 3.0);
    env.set(24, 4.0);
    return cxvm::execute(p, env);
}() == 7.0);

// --- Variable with constant ---
static_assert([] {
    constexpr auto p = cxvm::compile("x * 2 + 1");
    cxvm::Environment env;
    env.set(23, 5.0);
    return cxvm::execute(p, env);
}() == 11.0);

// --- Precedence with variables ---
static_assert([] {
    constexpr auto p = cxvm::compile("a + b * c");
    cxvm::Environment env;
    env.set(0, 1.0);  // a
    env.set(1, 2.0);  // b
    env.set(2, 3.0);  // c
    return cxvm::execute(p, env);
}() == 7.0);

// --- Same program, different bindings ---
static_assert([] {
    constexpr auto p = cxvm::compile("x + y * 2");
    cxvm::Environment env1;
    env1.set(23, 3.0);
    env1.set(24, 4.0);

    cxvm::Environment env2;
    env2.set(23, 10.0);
    env2.set(24, 5.0);

    return cxvm::execute(p, env1) == 11.0
        && cxvm::execute(p, env2) == 20.0;
}());

// --- Unary minus on variable ---
static_assert([] {
    constexpr auto p = cxvm::compile("-x + y");
    cxvm::Environment env;
    env.set(23, 3.0);
    env.set(24, 10.0);
    return cxvm::execute(p, env);
}() == 7.0);

// --- Parenthesized variable expressions ---
static_assert([] {
    constexpr auto p = cxvm::compile("(x + y) * (x - y)");
    cxvm::Environment env;
    env.set(23, 5.0);
    env.set(24, 3.0);
    // (5+3)*(5-3) = 8*2 = 16
    return cxvm::execute(p, env);
}() == 16.0);

int main() { return 0; }
