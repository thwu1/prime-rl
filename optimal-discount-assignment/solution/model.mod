/* Supermarket Discount Optimization - MILP Model (GMPL/MathProg)
 *
 * Minimizes total cart cost by optimally assigning items to pre-enumerated
 * discount application options. Each option specifies items consumed and
 * the cost paid. Items not assigned to any option are charged at full price.
 *
 * Decision variables:
 *   x[o] = number of times discount option o is applied (integer >= 0)
 *   s[p] = units of product p charged at full price (integer >= 0)
 *
 * The balance constraint ensures every cart unit is accounted for exactly once.
 */

set PRODUCTS;
set OPTIONS;

param price{p in PRODUCTS}, >= 0;
param qty{p in PRODUCTS}, integer, >= 0;
param consume{o in OPTIONS, p in PRODUCTS}, integer, >= 0, default 0;
param cost{o in OPTIONS}, >= 0;

var x{o in OPTIONS}, integer, >= 0;
var s{p in PRODUCTS}, integer, >= 0;

minimize total_cost:
    sum{o in OPTIONS} cost[o] * x[o] + sum{p in PRODUCTS} price[p] * s[p];

s.t. balance{p in PRODUCTS}:
    sum{o in OPTIONS} consume[o, p] * x[o] + s[p] = qty[p];

solve;

printf "OPTIMAL_TOTAL=%.10f\n", total_cost;

end;
