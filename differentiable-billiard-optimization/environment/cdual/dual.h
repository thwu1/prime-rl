#ifndef DUAL_H
#define DUAL_H

typedef struct {
    double real;
    double dual;
} DualNum;

DualNum dual_new(double real, double dual);
DualNum dual_const(double val);
DualNum dual_add(DualNum a, DualNum b);
DualNum dual_sub(DualNum a, DualNum b);
DualNum dual_mul(DualNum a, DualNum b);
DualNum dual_div(DualNum a, DualNum b);
DualNum dual_sqrt(DualNum a);
DualNum dual_neg(DualNum a);
DualNum dual_add_scalar(DualNum a, double s);
DualNum dual_mul_scalar(DualNum a, double s);
DualNum dual_div_scalar(DualNum a, double s);
int dual_lt(DualNum a, DualNum b);

#endif
