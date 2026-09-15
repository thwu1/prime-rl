
#include "vm.hpp"
#include "compiler.hpp"

// --- abs ---
static_assert([] {
    constexpr auto p = cxvm::compile("abs(-5)");
    return cxvm::execute(p);
}() == 5.0);

static_assert([] {
    constexpr auto p = cxvm::compile("abs(3)");
    return cxvm::execute(p);
}() == 3.0);

// --- min ---
static_assert([] {
    constexpr auto p = cxvm::compile("min(3, 7)");
    return cxvm::execute(p);
}() == 3.0);

static_assert([] {
    constexpr auto p = cxvm::compile("min(10, 2)");
    return cxvm::execute(p);
}() == 2.0);

// --- max ---
static_assert([] {
    constexpr auto p = cxvm::compile("max(3, 7)");
    return cxvm::execute(p);
}() == 7.0);

// --- sqrt ---
static_assert([] {
    constexpr auto p = cxvm::compile("sqrt(16)");
    constexpr double r = cxvm::execute(p);
    return r > 3.999 && r < 4.001;
}());

// --- Function with expression argument ---
static_assert([] {
    constexpr auto p = cxvm::compile("abs(3 - 10)");
    return cxvm::execute(p);
}() == 7.0);

// --- Nested function calls ---
static_assert([] {
    constexpr auto p = cxvm::compile("abs(min(3, -5))");
    return cxvm::execute(p);
}() == 5.0);

// --- Function with variable argument ---
static_assert([] {
    constexpr auto p = cxvm::compile("max(x, y) + 1");
    cxvm::Environment env;
    env.set(23, 3.0);
    env.set(24, 8.0);
    return cxvm::execute(p, env);
}() == 9.0);

// --- sqrt of expression ---
static_assert([] {
    constexpr auto p = cxvm::compile("sqrt(9 + 16)");
    constexpr double r = cxvm::execute(p);
    return r > 4.999 && r < 5.001;
}());

// --- min with expressions ---
static_assert([] {
    constexpr auto p = cxvm::compile("min(2 * 5, 3 + 4)");
    return cxvm::execute(p);
}() == 7.0);

int main() { return 0; }
