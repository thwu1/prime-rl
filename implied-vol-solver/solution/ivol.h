#ifndef IVOL_H
#define IVOL_H


double bs_price(int is_call, double strike, double forward,
                double total_var, double df);

double implied_vol(int is_call, double price, double forward,
                   double strike, double tte, double df);

#endif
