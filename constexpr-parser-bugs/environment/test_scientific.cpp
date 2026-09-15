// Scientific notation tests: the number parser must handle
// e/E exponent notation (e.g. 1.5e2 == 150.0).


#include "constexpr_eval.hpp"

static_assert(cev::evaluate("1e2") == 100.0);
static_assert(cev::evaluate("1.5e2") == 150.0);
static_assert(cev::evaluate("2E3") == 2000.0);
static_assert(cev::evaluate("5e-1") == 0.5);
static_assert(cev::evaluate("5e0") == 5.0);

int main() { return 0; }
