#include "dual.h"
#include <math.h>

DualNum dual_new(double real, double dual) {
    DualNum d = {real, dual};
    return d;
}

DualNum dual_const(double val) {
    DualNum d = {val, 0.0};
    return d;
}

DualNum dual_add(DualNum a, DualNum b) {
    DualNum r = {a.real + b.real, a.dual + b.dual};
    return r;
}

DualNum dual_sub(DualNum a, DualNum b) {
    DualNum r = {a.real - b.real, a.dual - b.dual};
    return r;
}

DualNum dual_mul(DualNum a, DualNum b) {
    DualNum r = {a.real * b.real, a.real * b.dual + a.dual * b.real};
    return r;
}

DualNum dual_div(DualNum a, DualNum b) {
    double denom = b.real * b.real;
    DualNum r = {a.real / b.real, (a.dual * b.real - a.real * b.dual) / denom};
    return r;
}

DualNum dual_sqrt(DualNum a) {
    double sr = sqrt(a.real);
    DualNum r = {sr, a.dual / (2.0 * sr)};
    return r;
}

DualNum dual_neg(DualNum a) {
    DualNum r = {-a.real, -a.dual};
    return r;
}

DualNum dual_add_scalar(DualNum a, double s) {
    DualNum r = {a.real + s, a.dual};
    return r;
}

DualNum dual_mul_scalar(DualNum a, double s) {
    DualNum r = {a.real * s, a.dual * s};
    return r;
}

DualNum dual_div_scalar(DualNum a, double s) {
    DualNum r = {a.real / s, a.dual / s};
    return r;
}

int dual_lt(DualNum a, DualNum b) {
    return a.real < b.real;
}
