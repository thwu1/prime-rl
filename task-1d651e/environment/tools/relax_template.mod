/* Facility Location LP Relaxation */
/* GMPL model template for use with glpsol */
/* Requires a companion .dat file with parameter values */

set FACILITIES;
set CUSTOMERS;

param setup_cost{i in FACILITIES};
param capacity{i in FACILITIES};
param demand{j in CUSTOMERS};
param dist{i in FACILITIES, j in CUSTOMERS};

var y{i in FACILITIES}, >= 0, <= 1;
var x{i in FACILITIES, j in CUSTOMERS}, >= 0, <= 1;

minimize total_cost:
    sum{i in FACILITIES} setup_cost[i] * y[i] +
    sum{i in FACILITIES, j in CUSTOMERS} dist[i,j] * x[i,j];

/* TODO: Each customer must be assigned to exactly one facility */
/* s.t. assignment{j in CUSTOMERS}: ... = 1; */

/* TODO: Capacity linking - assigned demand must not exceed facility capacity */
/* s.t. cap_link{i in FACILITIES}: ... <= 0; */

solve;

printf "LP_BOUND %.6f\n", total_cost;

end;
