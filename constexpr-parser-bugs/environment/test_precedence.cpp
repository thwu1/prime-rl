// Operator precedence tests: multiplication and division must bind
// tighter than addition and subtraction.


#include "constexpr_eval.hpp"

static_assert(cev::evaluate("2 + 3 * 4") == 14.0);
static_assert(cev::evaluate("10 - 6 / 2") == 7.0);
static_assert(cev::evaluate("2 * 3 + 4 * 5") == 26.0);
static_assert(cev::evaluate("100 / 4 - 3 * 2") == 19.0);

int main() { return 0; }
