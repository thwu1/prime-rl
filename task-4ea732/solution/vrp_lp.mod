/* CVRP Assignment LP Relaxation                             */
/* Computes a lower bound via directed assignment relaxation  */
/* Usage: glpsol --math vrp_lp.mod --data <instance>.dat      */

param n, integer, > 0;
param nv, integer, > 0;

set N := 0 .. n-1;
set C := 1 .. n-1;

param cx{N};
param cy{N};

param d{i in N, j in N} :=
    if i = j then 0
    else sqrt((cx[i] - cx[j]) * (cx[i] - cx[j])
            + (cy[i] - cy[j]) * (cy[i] - cy[j]));

var x{i in N, j in N: i <> j}, >= 0, <= 1;

minimize total_dist:
    sum{i in N, j in N: i <> j} d[i,j] * x[i,j];

s.t. arrive{i in C}: sum{j in N: j <> i} x[j,i] = 1;

s.t. depart{i in C}: sum{j in N: j <> i} x[i,j] = 1;

s.t. depot_out: sum{j in C} x[0,j] = nv;

s.t. depot_in: sum{j in C} x[j,0] = nv;

solve;

printf "LP_BOUND: %.6f\n",
    sum{i in N, j in N: i <> j} d[i,j] * x[i,j];

end;
