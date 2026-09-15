// Parenthesized expression tests: the parser must correctly track
// positions past the closing ')' so subsequent operators are visible.


#include "constexpr_eval.hpp"

static_assert(cev::evaluate("(5) + 1") == 6.0);
static_assert(cev::evaluate("(2 + 3) * 4") == 20.0);
static_assert(cev::evaluate("(10 - 3) * (2 + 1)") == 21.0);
static_assert(cev::evaluate("1 + (2 + 3) + 4") == 10.0);

int main() { return 0; }
