
#include "vm.hpp"
#include "compiler.hpp"

// --- Simple let-binding ---
static_assert([] {
    constexpr auto p = cxvm::compile("let x = 5 in x + 1");
    return cxvm::execute(p);
}() == 6.0);

// --- Let-binding with expression ---
static_assert([] {
    constexpr auto p = cxvm::compile("let x = 3 + 4 in x * 2");
    return cxvm::execute(p);
}() == 14.0);

// --- Let-binding shadows global variable ---
static_assert([] {
    constexpr auto p = cxvm::compile("let x = 10 in x + 1");
    cxvm::Environment env;
    env.set(23, 999.0);  // global x = 999, should be shadowed
    return cxvm::execute(p, env);
}() == 11.0);

// --- Nested let-bindings ---
static_assert([] {
    constexpr auto p = cxvm::compile("let x = 3 in let y = 4 in x + y");
    return cxvm::execute(p);
}() == 7.0);

// --- Nested let-bindings with shadowing ---
static_assert([] {
    constexpr auto p = cxvm::compile("let x = 5 in let x = 10 in x");
    return cxvm::execute(p);
}() == 10.0);

// --- Let-binding with global variable in init ---
static_assert([] {
    constexpr auto p = cxvm::compile("let y = x + 1 in y * 2");
    cxvm::Environment env;
    env.set(23, 4.0);  // x = 4
    // y = x + 1 = 5, y * 2 = 10
    return cxvm::execute(p, env);
}() == 10.0);

// --- Multiple uses of let-bound variable ---
static_assert([] {
    constexpr auto p = cxvm::compile("let x = 7 in x * x + x");
    return cxvm::execute(p);
}() == 56.0);  // 7*7+7 = 49+7 = 56

// --- Let-binding using function ---
static_assert([] {
    constexpr auto p = cxvm::compile("let d = sqrt(9) in d + 1");
    constexpr double r = cxvm::execute(p);
    return r > 3.999 && r < 4.001;
}());

// --- Chained let: inner init references outer binding ---
static_assert([] {
    constexpr auto p = cxvm::compile("let x = 5 in let y = x + 1 in y * 2");
    return cxvm::execute(p);
}() == 12.0);  // x=5, y=6, y*2=12

// --- Let with ternary in body ---
static_assert([] {
    constexpr auto p = cxvm::compile("let t = 10 in t > 5 ? t : 0");
    return cxvm::execute(p);
}() == 10.0);

// --- Let inside function argument ---
static_assert([] {
    constexpr auto p = cxvm::compile("abs(let x = -7 in x)");
    return cxvm::execute(p);
}() == 7.0);

int main() { return 0; }
