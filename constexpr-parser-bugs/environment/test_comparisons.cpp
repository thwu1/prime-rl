
#include "vm.hpp"
#include "compiler.hpp"

// --- Less than ---
static_assert([] {
    constexpr auto p = cxvm::compile("3 < 5");
    return cxvm::execute(p);
}() == 1.0);

static_assert([] {
    constexpr auto p = cxvm::compile("5 < 3");
    return cxvm::execute(p);
}() == 0.0);

// --- Greater than ---
static_assert([] {
    constexpr auto p = cxvm::compile("5 > 3");
    return cxvm::execute(p);
}() == 1.0);

static_assert([] {
    constexpr auto p = cxvm::compile("3 > 5");
    return cxvm::execute(p);
}() == 0.0);

// --- Less or equal ---
static_assert([] {
    constexpr auto p = cxvm::compile("3 <= 3");
    return cxvm::execute(p);
}() == 1.0);

static_assert([] {
    constexpr auto p = cxvm::compile("4 <= 3");
    return cxvm::execute(p);
}() == 0.0);

// --- Greater or equal ---
static_assert([] {
    constexpr auto p = cxvm::compile("5 >= 5");
    return cxvm::execute(p);
}() == 1.0);

static_assert([] {
    constexpr auto p = cxvm::compile("4 >= 5");
    return cxvm::execute(p);
}() == 0.0);

// --- Equal ---
static_assert([] {
    constexpr auto p = cxvm::compile("4 == 4");
    return cxvm::execute(p);
}() == 1.0);

static_assert([] {
    constexpr auto p = cxvm::compile("4 == 5");
    return cxvm::execute(p);
}() == 0.0);

// --- Not equal ---
static_assert([] {
    constexpr auto p = cxvm::compile("4 != 5");
    return cxvm::execute(p);
}() == 1.0);

static_assert([] {
    constexpr auto p = cxvm::compile("4 != 4");
    return cxvm::execute(p);
}() == 0.0);

// --- Comparison with variables ---
static_assert([] {
    constexpr auto p = cxvm::compile("x < y");
    cxvm::Environment env;
    env.set(23, 3.0);
    env.set(24, 7.0);
    return cxvm::execute(p, env);
}() == 1.0);

// --- Comparison with arithmetic expressions ---
static_assert([] {
    constexpr auto p = cxvm::compile("2 + 3 > 4");
    return cxvm::execute(p);
}() == 1.0);

// --- Comparison with expressions on both sides ---
static_assert([] {
    constexpr auto p = cxvm::compile("x * 2 >= y + 1");
    cxvm::Environment env;
    env.set(23, 5.0);
    env.set(24, 8.0);
    // 5*2=10 >= 8+1=9 -> 1.0
    return cxvm::execute(p, env);
}() == 1.0);

int main() { return 0; }
