/*
 * MaxSAT solver using CaDiCaL's incremental SAT API.
 *
 * Algorithm: Linear SAT-UNSAT search with sequential counter encoding.
 * - Hard clauses added directly to solver.
 * - Soft clauses augmented with relaxation variables.
 * - Sequential counter computes unary sum of relaxation variables.
 * - CaDiCaL's assume() bounds the counter to enforce at-most-k.
 * - Linear search from k=0 upward finds the optimum.
 */

#include "cadical.hpp"
#include <algorithm>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

using namespace std;

struct Clause {
  int weight;
  vector<int> lits;
};

struct WCNF {
  int nvars;
  int nclauses;
  int top;
  vector<Clause> clauses;
};

WCNF parse_wcnf(const char *filename) {
  WCNF wcnf;
  wcnf.nvars = 0;
  wcnf.nclauses = 0;
  wcnf.top = 0;
  ifstream file(filename);
  if (!file.is_open()) {
    cerr << "Error: cannot open " << filename << endl;
    exit(2);
  }
  string line;
  while (getline(file, line)) {
    if (line.empty() || line[0] == 'c')
      continue;
    if (line[0] == 'p') {
      istringstream iss(line);
      string p, fmt;
      iss >> p >> fmt >> wcnf.nvars >> wcnf.nclauses >> wcnf.top;
      continue;
    }
    istringstream iss(line);
    Clause cl;
    iss >> cl.weight;
    int lit;
    while (iss >> lit && lit != 0) {
      cl.lits.push_back(lit);
    }
    if (!cl.lits.empty()) {
      wcnf.clauses.push_back(cl);
    }
  }
  return wcnf;
}

int main(int argc, char *argv[]) {
  if (argc < 2) {
    cerr << "Usage: maxsat <wcnf-file>" << endl;
    return 1;
  }

  WCNF wcnf = parse_wcnf(argv[1]);

  vector<vector<int>> hard_clauses, soft_clauses;
  for (auto &cl : wcnf.clauses) {
    if (cl.weight >= wcnf.top) {
      hard_clauses.push_back(cl.lits);
    } else {
      soft_clauses.push_back(cl.lits);
    }
  }

  int n_soft = (int)soft_clauses.size();
  int next_var = wcnf.nvars + 1;

  CaDiCaL::Solver solver;

  /* Disable factor (BVA) to avoid variable declaration requirements
   * in incremental mode on CaDiCaL >= 3.0. */
  solver.set("factor", 0);

  /* Add hard clauses. */
  for (auto &clause : hard_clauses) {
    for (int lit : clause)
      solver.add(lit);
    solver.add(0);
  }

  /* Handle trivial case: no soft clauses. */
  if (n_soft == 0) {
    int result = solver.solve();
    if (result == 10) {
      cout << "s OPTIMUM FOUND" << endl;
      cout << "o 0" << endl;
      cout << "v";
      for (int v = 1; v <= wcnf.nvars; v++)
        cout << " " << solver.val(v);
      cout << " 0" << endl;
      return 0;
    } else {
      cout << "s UNSATISFIABLE" << endl;
      return 1;
    }
  }

  /* Add soft clauses with relaxation variables: (clause OR r_i). */
  vector<int> relax(n_soft);
  for (int i = 0; i < n_soft; i++) {
    relax[i] = next_var++;
    for (int lit : soft_clauses[i])
      solver.add(lit);
    solver.add(relax[i]);
    solver.add(0);
  }

  /*
   * Build sequential counter over relax[0..n_soft-1].
   *
   * Auxiliary variable s(i, j) means "at least j of relax[0..i] are true."
   * We encode the forward implication only (sufficient for at-most-k via
   * assumption on the counter output).
   *
   * Clauses:
   *   i=0:  -relax[0] | s(0,1)
   *   i>0:  -relax[i] | s(i,1)                           [init]
   *         -s(i-1,j) | s(i,j)         for j=1..i        [monotonicity]
   *         -relax[i] | -s(i-1,j-1) | s(i,j)  j=2..i+1  [carry]
   */

  int counter_base = next_var;
  /* s(i, j) -> counter_base + i * n_soft + (j - 1) */
  auto s = [&](int i, int j) -> int {
    return counter_base + i * n_soft + (j - 1);
  };
  /* Reserve variable space (not strictly required but documents intent). */
  next_var = counter_base + n_soft * n_soft;

  /* i = 0 */
  solver.add(-relax[0]);
  solver.add(s(0, 1));
  solver.add(0);

  /* i = 1 .. n_soft-1 */
  for (int i = 1; i < n_soft; i++) {
    /* -relax[i] | s(i,1) */
    solver.add(-relax[i]);
    solver.add(s(i, 1));
    solver.add(0);

    int max_prev = min(i, n_soft); /* max valid j for s(i-1, j) */
    /* monotonicity */
    for (int j = 1; j <= max_prev; j++) {
      solver.add(-s(i - 1, j));
      solver.add(s(i, j));
      solver.add(0);
    }
    /* carry */
    for (int j = 2; j <= min(i + 1, n_soft); j++) {
      solver.add(-relax[i]);
      solver.add(-s(i - 1, j - 1));
      solver.add(s(i, j));
      solver.add(0);
    }
  }

  /* Linear search from k=0 upward. */
  for (int k = 0; k <= n_soft; k++) {
    if (k < n_soft) {
      /* Assume at most k relaxation variables are true:
       * negate the (k+1)-th counter output at the last position. */
      solver.assume(-s(n_soft - 1, k + 1));
    }
    /* If k == n_soft no assumption needed (all relax vars can be true). */

    int result = solver.solve();

    if (result == 10) { /* SATISFIABLE */
      cout << "s OPTIMUM FOUND" << endl;
      cout << "o " << k << endl;
      cout << "v";
      for (int v = 1; v <= wcnf.nvars; v++)
        cout << " " << solver.val(v);
      cout << " 0" << endl;
      return 0;
    }
    /* UNSATISFIABLE at this bound; try next k. */
  }

  /* Hard clauses are infeasible. */
  cout << "s UNSATISFIABLE" << endl;
  return 1;
}
