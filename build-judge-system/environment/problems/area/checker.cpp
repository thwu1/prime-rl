#include "testlib.h"
#include <cmath>

int main(int argc, char* argv[]) {
    registerTestlibCmd(argc, argv);

    double expected = ans.readDouble();
    double actual = ouf.readDouble();

    if (fabs(expected - actual) <= 1e-4) {
        quitf(_ok, "area = %.6f", actual);
    } else {
        quitf(_wa, "expected %.6f, got %.6f", expected, actual);
    }
}
