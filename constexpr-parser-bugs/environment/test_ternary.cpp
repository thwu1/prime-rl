
#include "vm.hpp"
#include "compiler.hpp"

// --- Ternary with constant true condition ---
static_assert([] {
    constexpr auto p = cxvm::compile("1 ? 42 : 99");
    return cxvm::execute(p);
}() == 42.0);

// --- Ternary with constant false condition ---
static_assert([] {
    constexpr auto p = cxvm::compile("0 ? 42 : 99");
    return cxvm::execute(p);
}() == 99.0);

// --- Ternary with comparison condition ---
static_assert([] {
    constexpr auto p = cxvm::compile("3 < 5 ? 10 : 20");
    return cxvm::execute(p);
}() == 10.0);

static_assert([] {
    constexpr auto p = cxvm::compile("5 < 3 ? 10 : 20");
    return cxvm::execute(p);
}() == 20.0);

// --- Ternary with variable condition (positive) ---
static_assert([] {
    constexpr auto p = cxvm::compile("x > 0 ? x : -x");
    cxvm::Environment env;
    env.set(23, 7.0);
    return cxvm::execute(p, env);
}() == 7.0);

// --- Ternary with variable condition (negative) ---
static_assert([] {
    constexpr auto p = cxvm::compile("x > 0 ? x : -x");
    cxvm::Environment env;
    env.set(23, -5.0);
    // -5 > 0 is false, so -(-5) = 5
    return cxvm::execute(p, env);
}() == 5.0);

// --- Nested ternary (signum function) ---
static_assert([] {
    constexpr auto p = cxvm::compile("x < 0 ? -1 : x > 0 ? 1 : 0");
    cxvm::Environment env;
    env.set(23, -5.0);
    return cxvm::execute(p, env);
}() == -1.0);

static_assert([] {
    constexpr auto p = cxvm::compile("x < 0 ? -1 : x > 0 ? 1 : 0");
    cxvm::Environment env;
    env.set(23, 5.0);
    return cxvm::execute(p, env);
}() == 1.0);

static_assert([] {
    constexpr auto p = cxvm::compile("x < 0 ? -1 : x > 0 ? 1 : 0");
    cxvm::Environment env;
    env.set(23, 0.0);
    return cxvm::execute(p, env);
}() == 0.0);

// --- Ternary with expressions in branches ---
static_assert([] {
    constexpr auto p = cxvm::compile("a > b ? a - b : b - a");
    cxvm::Environment env;
    env.set(0, 10.0);
    env.set(1, 3.0);
    return cxvm::execute(p, env);
}() == 7.0);

static_assert([] {
    constexpr auto p = cxvm::compile("a > b ? a - b : b - a");
    cxvm::Environment env;
    env.set(0, 3.0);
    env.set(1, 10.0);
    return cxvm::execute(p, env);
}() == 7.0);

// --- Ternary with function calls ---
static_assert([] {
    constexpr auto p = cxvm::compile("x >= 0 ? sqrt(x) : 0");
    cxvm::Environment env;
    env.set(23, 9.0);
    constexpr double tol = 0.001;
    double r = cxvm::execute(p, env);
    return r > 3.0 - tol && r < 3.0 + tol;
}());

int main() { return 0; }
