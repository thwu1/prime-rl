# Rectangle Ad Placement Problem

## Problem Statement

A web page has a 10000 × 10000 advertisement space. N companies each want an ad rectangle placed on this grid.

Company i desires:
- A rectangle **containing** the point (x_i + 0.5, y_i + 0.5)
- With area as close to r_i as possible

Each rectangle is axis-aligned with **integer** vertex coordinates and **positive area**.
Rectangles may touch on their boundaries but must **not overlap** (i.e., their intersection must have zero area).
Not all grid space needs to be used.

## Input Format

```
N
x_0 y_0 r_0
x_1 y_1 r_1
...
x_{N-1} y_{N-1} r_{N-1}
```

- 50 ≤ N ≤ 200
- 0 ≤ x_i, y_i ≤ 9999 (integers); all (x_i, y_i) are distinct
- r_i ≥ 1 (integer); sum of all r_i = 100,000,000 (= 10000 × 10000)

## Output Format

For each company i (in order 0 to N-1), output one line:

```
a_i b_i c_i d_i
```

where (a_i, b_i) and (c_i, d_i) are opposite corners of the rectangle:
- 0 ≤ a_i < c_i ≤ 10000
- 0 ≤ b_i < d_i ≤ 10000

## Scoring

The satisfaction of company i is:

- **p_i = 0** if the rectangle does not contain (x_i + 0.5, y_i + 0.5)
- **p_i = 1 - (1 - min(r_i, s_i) / max(r_i, s_i))²** otherwise, where s_i = (c_i - a_i) × (d_i - b_i) is the actual area

Containment means: a_i ≤ x_i AND c_i ≥ x_i + 1 AND b_i ≤ y_i AND d_i ≥ y_i + 1.

**Score = round(10⁹ × (1/N) × Σ p_i)**

Higher is better. Maximum possible score is 1,000,000,000.

## Constraints Summary

1. All rectangles must have positive area
2. All rectangles must stay within [0, 10000] × [0, 10000]
3. No two rectangles may share positive area (touching edges/corners is fine)
4. Coordinates must be integers
