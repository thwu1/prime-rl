
#include "vm.hpp"
#include "compiler.hpp"

// --- Literal parsing ---
static_assert([] {
    constexpr auto p = cxvm::compile("42");
    return cxvm::execute(p);
}() == 42.0);

static_assert([] {
    constexpr auto p = cxvm::compile("3.14");
    constexpr double r = cxvm::execute(p);
    return r > 3.139 && r < 3.141;
}());

// --- Addition and subtraction ---
static_assert([] {
    constexpr auto p = cxvm::compile("2 + 3");
    return cxvm::execute(p);
}() == 5.0);

static_assert([] {
    constexpr auto p = cxvm::compile("10 - 4");
    return cxvm::execute(p);
}() == 6.0);

// --- Multiplication and division ---
static_assert([] {
    constexpr auto p = cxvm::compile("6 * 7");
    return cxvm::execute(p);
}() == 42.0);

static_assert([] {
    constexpr auto p = cxvm::compile("20 / 4");
    return cxvm::execute(p);
}() == 5.0);

// --- Operator precedence ---
static_assert([] {
    constexpr auto p = cxvm::compile("2 + 3 * 4");
    return cxvm::execute(p);
}() == 14.0);

static_assert([] {
    constexpr auto p = cxvm::compile("10 - 2 * 3");
    return cxvm::execute(p);
}() == 4.0);

static_assert([] {
    constexpr auto p = cxvm::compile("12 / 4 + 1");
    return cxvm::execute(p);
}() == 4.0);

// --- Left-to-right associativity ---
static_assert([] {
    constexpr auto p = cxvm::compile("20 - 5 - 3");
    return cxvm::execute(p);
}() == 12.0);

static_assert([] {
    constexpr auto p = cxvm::compile("100 / 10 / 2");
    return cxvm::execute(p);
}() == 5.0);

// --- Parentheses ---
static_assert([] {
    constexpr auto p = cxvm::compile("(2 + 3) * 4");
    return cxvm::execute(p);
}() == 20.0);

static_assert([] {
    constexpr auto p = cxvm::compile("(10 - 2) * (3 + 1)");
    return cxvm::execute(p);
}() == 32.0);

// --- Unary minus ---
static_assert([] {
    constexpr auto p = cxvm::compile("-5");
    return cxvm::execute(p);
}() == -5.0);

static_assert([] {
    constexpr auto p = cxvm::compile("-(3 + 4)");
    return cxvm::execute(p);
}() == -7.0);

static_assert([] {
    constexpr auto p = cxvm::compile("--5");
    return cxvm::execute(p);
}() == 5.0);

static_assert([] {
    constexpr auto p = cxvm::compile("2 - -3");
    return cxvm::execute(p);
}() == 5.0);

int main() { return 0; }
