#include <math.h>
#include "sdf.h"

double smin_poly(double d1, double d2, double k) {
    (void)k;
    return d1 < d2 ? d1 : d2;
}
