# Ad Placement Optimization — Problem Specification

## Problem Statement

You are given a 10000 x 10000 grid and N companies. Each company i (0-indexed) has:
- A desired location (x_i, y_i) where 0 <= x_i, y_i <= 9999
- A desired area r_i (positive integer)

All (x_i, y_i) are distinct. The total desired area equals the grid area: sum(r_i) = 10^8.

Your task: assign each company i a rectangle with diagonal corners (a_i, b_i) and (c_i, d_i) satisfying:
1. 0 <= a_i < c_i <= 10000
2. 0 <= b_i < d_i <= 10000
3. No two rectangles overlap (they may share edges but must not have positive common area)

## Scoring

The satisfaction p_i of company i is computed as:

- If the rectangle for company i does **not** contain the point (x_i + 0.5, y_i + 0.5):
  p_i = 0

- If it **does** contain (x_i + 0.5, y_i + 0.5), let s_i = (c_i - a_i) * (d_i - b_i) be the actual area:
  p_i = 1 - (1 - min(r_i, s_i) / max(r_i, s_i))^2

The total score is the average satisfaction: sum(p_i) / N.

**Containment rule**: The point (x_i + 0.5, y_i + 0.5) is inside rectangle [a_i, c_i] x [b_i, d_i] if and only if a_i <= x_i and x_i + 1 <= c_i and b_i <= y_i and y_i + 1 <= d_i.

**Key insight**: Satisfaction is maximized when the actual area s_i equals the desired area r_i (giving p_i = 1.0). Any mismatch reduces satisfaction quadratically. The point must also be contained.

## Input Format

Read from standard input:

```
N
x_0 y_0 r_0
x_1 y_1 r_1
...
x_{N-1} y_{N-1} r_{N-1}
```

## Output Format

Write to standard output:

```
a_0 b_0 c_0 d_0
a_1 b_1 c_1 d_1
...
a_{N-1} b_{N-1} c_{N-1} d_{N-1}
```

Where (a_i, b_i) and (c_i, d_i) are the two diagonal corners of company i's rectangle.

## Constraints

- 50 <= N <= 200
- 0 <= x_i, y_i <= 9999
- All (x_i, y_i) are distinct
- r_i >= 1 for all i
- sum(r_i) = 100,000,000

## Input Generation

Inputs are generated as follows:
- N = round(50 * 4^u) where u is uniform random in [0, 1), giving N in [50, 200]
- (x_i, y_i): N distinct coordinates sampled uniformly from {0,...,9999}^2
- Areas: N-1 distinct integers sampled uniformly from {1,...,99999999}, sorted. Let these be q_1 < ... < q_{N-1}. Set q_0 = 0, q_N = 100000000. Then r_i = q_{i+1} - q_i.
