// Unary minus tests: negation must work before parenthesized
// sub-expressions and support chained negation (e.g. --3 == 3).


#include "constexpr_eval.hpp"

static_assert(cev::evaluate("-(5)") == -5.0);
static_assert(cev::evaluate("-(2 + 3)") == -5.0);
static_assert(cev::evaluate("--3") == 3.0);
static_assert(cev::evaluate("10 + -(3)") == 7.0);

int main() { return 0; }
