// Basic sanity tests for the constexpr expression evaluator.
// These exercise single-operator expressions and should compile
// regardless of other bugs in the library.


#include "constexpr_eval.hpp"

static_assert(cev::evaluate("42") == 42.0);
static_assert(cev::evaluate("0") == 0.0);
static_assert(cev::evaluate("1.5") == 1.5);
static_assert(cev::evaluate("  7  ") == 7.0);
static_assert(cev::evaluate("3 + 4") == 7.0);
static_assert(cev::evaluate("10 - 3") == 7.0);
static_assert(cev::evaluate("6 * 7") == 42.0);
static_assert(cev::evaluate("15 / 3") == 5.0);
static_assert(cev::evaluate("-5") == -5.0);

int main() { return 0; }
