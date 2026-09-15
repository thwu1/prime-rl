N-Queens Completion Problem — Decision, Counting, and UNSAT Analysis
=====================================================================

Problem Definition
------------------
Given an n x n chessboard with some queens already placed (guaranteed to be
mutually non-attacking), determine whether it is possible to place additional
queens so that there are exactly n queens total, with no two queens attacking
each other. Two queens attack each other if they share the same row, column,
or diagonal.

This task requires three capabilities:

1. DECISION: Classify each instance as satisfiable (SAT) or unsatisfiable
   (UNSAT). For SAT instances, produce one valid completion.

2. SOLUTION COUNTING: Some instances have "count_solutions": true in their
   JSON. For these, report the exact number of distinct valid completions.
   This is the #P-Complete variant of the problem.

3. MINIMAL UNSATISFIABLE CORE (MUS): For each UNSAT instance, identify a
   minimal subset of the pre-placed queens that is itself unsatisfiable.
   "Minimal" means removing any single queen from the subset must restore
   satisfiability.

Input Format
------------
Instance files are in /app/instances/ as JSON:

    {
        "n": <board_size>,
        "pre_placed": [[row_0, col_0], [row_1, col_1], ...],
        "count_solutions": true
    }

- Rows and columns are 0-indexed (0 to n-1).
- pre_placed queens are guaranteed to be mutually non-attacking.
- pre_placed may be empty (standard n-Queens problem).
- "count_solutions" is optional; absent or false means counting is not required.

Output Format
-------------
Write results to /app/results.json as a JSON object mapping instance names
(filename without .json extension) to result objects.

For satisfiable instances (no counting):
    {
        "instance_01": {
            "satisfiable": true,
            "queens": [c0, c1, c2, ..., c_{n-1}]
        }
    }

For unsatisfiable instances (must include minimal_unsat_core):
    {
        "instance_07": {
            "satisfiable": false,
            "queens": null,
            "minimal_unsat_core": [[r0, c0], [r1, c1], ...]
        }
    }

For counting instances:
    {
        "count_01": {
            "satisfiable": true,
            "queens": [c0, c1, c2, ..., c_{n-1}],
            "solution_count": 92
        }
    }

Field Details:
- "queens": list of n integers where queens[i] is the column of the queen
  in row i (0-indexed). Every row must have exactly one queen.
- For UNSAT instances, "queens" must be null.
- "minimal_unsat_core": list of [row, col] pairs identifying the minimal
  subset of pre_placed queens causing unsatisfiability. Must be a subset
  of the instance's pre_placed queens. Required for all UNSAT instances.
- "solution_count": exact integer count of all distinct valid completions.
  Required for instances with "count_solutions": true.
- All pre-placed queens must appear in the solution at their original positions.

Instance Set
------------
15 instances total:
- 8 standard SAT instances (n = 5 to 100), including one dense instance
  with 20 pre-placed queens on a 60x60 board
- 3 UNSAT instances (n = 8, 10, 12) — require minimal_unsat_core
- 4 counting instances (n = 8, 9, 10, 12) — require solution_count
