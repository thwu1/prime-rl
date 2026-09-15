
#include "vm.hpp"
#include "compiler.hpp"

// --- Power basics ---
static_assert([] {
    constexpr auto p = cxvm::compile("2 ^ 3");
    return cxvm::execute(p);
}() == 8.0);

static_assert([] {
    constexpr auto p = cxvm::compile("3 ^ 2");
    return cxvm::execute(p);
}() == 9.0);

// --- Right-to-left associativity: 2^3^2 = 2^(3^2) = 2^9 = 512 ---
static_assert([] {
    constexpr auto p = cxvm::compile("2 ^ 3 ^ 2");
    return cxvm::execute(p);
}() == 512.0);

// --- Parentheses override: (2^3)^2 = 8^2 = 64 ---
static_assert([] {
    constexpr auto p = cxvm::compile("(2 ^ 3) ^ 2");
    return cxvm::execute(p);
}() == 64.0);

// --- Power precedence higher than * ---
static_assert([] {
    constexpr auto p = cxvm::compile("2 * 3 ^ 2");
    return cxvm::execute(p);
}() == 18.0);  // 2 * (3^2) = 2 * 9 = 18

// --- Power with variable ---
static_assert([] {
    constexpr auto p = cxvm::compile("x ^ 3");
    cxvm::Environment env;
    env.set(23, 2.0);
    return cxvm::execute(p, env);
}() == 8.0);

// --- Power of zero ---
static_assert([] {
    constexpr auto p = cxvm::compile("5 ^ 0");
    return cxvm::execute(p);
}() == 1.0);

// --- Power of one ---
static_assert([] {
    constexpr auto p = cxvm::compile("7 ^ 1");
    return cxvm::execute(p);
}() == 7.0);

// --- Modulo basics ---
static_assert([] {
    constexpr auto p = cxvm::compile("17 % 5");
    return cxvm::execute(p);
}() == 2.0);

static_assert([] {
    constexpr auto p = cxvm::compile("10 % 3");
    return cxvm::execute(p);
}() == 1.0);

// --- Modulo precedence same as * / ---
static_assert([] {
    constexpr auto p = cxvm::compile("10 + 7 % 3");
    return cxvm::execute(p);
}() == 11.0);  // 10 + (7%3) = 10 + 1 = 11

// --- Modulo with variable ---
static_assert([] {
    constexpr auto p = cxvm::compile("x % 4");
    cxvm::Environment env;
    env.set(23, 13.0);
    return cxvm::execute(p, env);
}() == 1.0);

// --- Power combined with addition ---
static_assert([] {
    constexpr auto p = cxvm::compile("1 + 2 ^ 3");
    return cxvm::execute(p);
}() == 9.0);  // 1 + 8 = 9

int main() { return 0; }
