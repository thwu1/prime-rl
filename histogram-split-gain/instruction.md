`/app/` contains a C++ histogram-based split finder for gradient boosted decision trees. It supports forward (left-to-right) and reverse (right-to-left) bin scanning, L1/L2 regularization, max_delta_step output clamping, monotone constraints with output bounds, path smoothing, and NaN bin handling. The project builds with CMake, compiles, and runs, but produces incorrect results across multiple configurations. Bugs may exist in any project file, including the CMake build configuration.

Diagnose and fix all defects so the test suite passes.

Source files: `/app/CMakeLists.txt`, `/app/split_math.hpp`, `/app/histogram_scanner.hpp`, `/app/main.cpp`.

Build: `cd /app && cmake -B build && cmake --build build`
Run: `cd /app && ./histogram_split_finder`

Read `/app/input.json`, write `/app/output.json`.

**Input** (`test_cases` array, each element):
- `bins`: array of `{grad, hess}` per-bin gradient/hessian sums; bin 0 is a remainder bin excluded from scanning
- `total_gradient`, `total_hessian`: node-level aggregates
- `total_count`: data points in the node
- `lambda_l1`, `lambda_l2`: L1/L2 regularization strengths
- `min_data_in_leaf`, `min_sum_hessian_in_leaf`: per-child minimums enforced on both sides of a candidate split
- `min_gain_to_split`: minimum net gain to accept a split
- `max_delta_step`: leaf output magnitude cap (0 = none)
- `monotone_type`: 1 (left output <= right), -1 (left >= right), 0 (unconstrained)
- `constraint_min`, `constraint_max`: output bounds applied under monotone constraints
- `parent_output`: float
- `path_smooth`: smoothing coefficient (0 = none); smoothed output = raw*(n/s)/(n/s+1) + parent*1/(n/s+1) where n=num_data, s=path_smooth
- `scan_reverse`: bool -- true scans right-to-left
- `has_na_bin`: bool -- true means last bin is NaN sentinel, excluded from reverse scan

**Output** (per-case array):
`best_threshold` (int, -1 if none), `best_gain` (float, net gain), `left_output`, `right_output` (float), `left_count`, `right_count` (int), `default_left` (bool: true for reverse, false for forward).

Net gain = split_gain - parent_gain - min_gain_to_split. Parent gain uses total_hessian + 2*epsilon where epsilon is a negligible stability constant. When monotone constraints are active, candidate leaf outputs are clamped to bounds, directionally-violating splits are skipped, and gain uses the output-given formula. In reverse scan, the threshold is one below the rightmost bin assigned to the right child.
