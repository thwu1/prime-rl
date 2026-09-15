/* touring.mod - MIP formulation for Optimal Touring (TSPTW, no-waiting)
 *
 * Formulates the touring problem as a mixed-integer program:
 * - Binary site-selection variables (x)
 * - Binary arc-flow variables (y) for sequencing
 * - Continuous arrival-time variables (t) with MTZ-style propagation
 * - Bidirectional big-M constraints enforce the no-waiting rule
 *
 */

set SITES;

param avenue{SITES};
param street{SITES};
param duration{SITES};
param value{SITES};
param begin_min{SITES};
param end_min{SITES};

param M := 1500;

param dist{i in SITES, j in SITES} :=
    abs(avenue[i] - avenue[j]) + abs(street[i] - street[j]);

/* Decision variables */
var x{SITES}, binary;                            /* 1 if site i is visited */
var y{i in SITES, j in SITES: i <> j}, binary;   /* 1 if j immediately follows i */
var is_first{SITES}, binary;                      /* 1 if site i is the first visited */
var is_last{SITES}, binary;                       /* 1 if site i is the last visited */
var t{SITES}, >= 0;                               /* arrival time at site i (minutes) */

/* Objective: maximize total collected value */
maximize total_value: sum{i in SITES} value[i] * x[i];

/* Flow conservation: each visited site has exactly one predecessor (or is first)
   and one successor (or is last) */
s.t. flow_in{j in SITES}:
    sum{i in SITES: i <> j} y[i,j] + is_first[j] = x[j];
s.t. flow_out{i in SITES}:
    sum{j in SITES: j <> i} y[i,j] + is_last[i] = x[i];

/* At most one first and one last site */
s.t. one_first: sum{i in SITES} is_first[i] <= 1;
s.t. one_last: sum{i in SITES} is_last[i] <= 1;

/* Arc activation requires both endpoints to be visited */
s.t. arc_src{i in SITES, j in SITES: i <> j}: y[i,j] <= x[i];
s.t. arc_dst{i in SITES, j in SITES: i <> j}: y[i,j] <= x[j];

/* Time propagation (MTZ-style) with NO-WAITING enforcement:
   When y[i,j]=1, arrival at j equals departure from i plus travel time.
   The bidirectional bounds (lb + ub) enforce exact arrival = no waiting. */
s.t. time_lb{i in SITES, j in SITES: i <> j}:
    t[j] >= t[i] + duration[i] + dist[i,j] - M * (1 - y[i,j]);
s.t. time_ub{i in SITES, j in SITES: i <> j}:
    t[j] <= t[i] + duration[i] + dist[i,j] + M * (1 - y[i,j]);

/* First site starts at its opening time */
s.t. first_start_lb{i in SITES}:
    t[i] >= begin_min[i] - M * (1 - is_first[i]);
s.t. first_start_ub{i in SITES}:
    t[i] <= begin_min[i] + M * (1 - is_first[i]);

/* Time window constraints for visited sites */
s.t. tw_open{i in SITES}:
    t[i] >= begin_min[i] - M * (1 - x[i]);
s.t. tw_close{i in SITES}:
    t[i] + duration[i] <= end_min[i] + M * (1 - x[i]);

/* Force t=0 when site is not visited */
s.t. t_bound{i in SITES}: t[i] <= M * x[i];

solve;

/* Write solution to file for Python parser */
printf "SOL_START\n" > "/tmp/glpk_sol.txt";
printf{i in SITES: x[i] > 0.5}: "V %d\n", i >> "/tmp/glpk_sol.txt";
printf{i in SITES, j in SITES: i <> j and y[i,j] > 0.5}: "A %d %d\n", i, j >> "/tmp/glpk_sol.txt";
printf{i in SITES: is_first[i] > 0.5}: "F %d\n", i >> "/tmp/glpk_sol.txt";
printf "SOL_END\n" >> "/tmp/glpk_sol.txt";

end;
