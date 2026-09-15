/* Job Shop Scheduling Problem - Manne (1960) MIP Formulation */
/* Solves JSP instances using big-M disjunctive constraints    */

param J, integer, >= 1;   /* number of jobs */
param M, integer, >= 1;   /* number of machines */

set JOBS := 1..J;
set OPS  := 1..M;         /* each job has exactly M operations */

/* Instance data (1-indexed) */
param machine{JOBS, OPS}, integer, >= 1, <= M;
param duration{JOBS, OPS}, integer, >= 0;

/* Big-M constant for disjunctive relaxation */
param bigM, >= 0;

/* ---- Decision variables ---- */
var s{JOBS, OPS}, >= 0;          /* start time of each operation */
var makespan, >= 0;              /* schedule length              */

/* Binary ordering variable: y=1 iff (j1,k1) is scheduled before (j2,k2) */
var y{j1 in JOBS, k1 in OPS, j2 in JOBS, k2 in OPS:
      j1 < j2 and machine[j1,k1] = machine[j2,k2]}, binary;

/* ---- Objective ---- */
minimize obj: makespan;

/* Makespan must cover all job completions */
s.t. makespan_lb{j in JOBS}:
    makespan >= s[j, M] + duration[j, M];

/* Each operation must finish before the next operation in the same job begins */
s.t. precedence{j in JOBS, k in 1..M-1}:
    s[j, k+1] >= s[j, k] + duration[j, k+1];

/* Disjunctive: two operations on the same machine cannot overlap */
s.t. disj_fwd{j1 in JOBS, k1 in OPS, j2 in JOBS, k2 in OPS:
              j1 < j2 and machine[j1,k1] = machine[j2,k2]}:
    s[j1,k1] + duration[j1,k1] <= s[j2,k2]
        + bigM * (1 - y[j1,k1,j2,k2]);

s.t. disj_bwd{j1 in JOBS, k1 in OPS, j2 in JOBS, k2 in OPS:
              j1 < j2 and machine[j1,k1] = machine[j2,k2]}:
    s[j2,k2] + duration[j2,k2] <= s[j1,k1]
        + bigM * y[j1,k1,j2,k2];

end;
