# Dynamic Forest Query Engine

## Problem

You are given a forest of **N** nodes with initial weights w_1, w_2, ..., w_N. Process **Q** operations:

- `link u v` — Add an edge between nodes u and v. Guaranteed not to create a cycle.
- `cut u v` — Remove the edge between nodes u and v. Guaranteed the edge exists.
- `path_sum u v` — Print the sum of weights of all nodes on the unique path from u to v.
- `path_max u v` — Print the maximum weight among all nodes on the unique path from u to v.
- `path_min u v` — Print the minimum weight among all nodes on the unique path from u to v.
- `add u v d` — Add d to the weight of every node on the path from u to v.
- `update u w` — Set the weight of node u to w.

All query operations (path_sum, path_max, path_min) are guaranteed to have u and v connected.

## Input Format

```
N
w_1 w_2 ... w_N
Q
<operation_1>
<operation_2>
...
<operation_Q>
```

**Constraints:**
- 1 <= N <= 200,000
- 1 <= Q <= 500,000
- |w_i| <= 10^9
- |d| <= 10^9
- Weights and results fit in 64-bit signed integers.

## Output Format

For each `path_sum`, `path_max`, and `path_min` operation, print the result on a separate line.

## Example

Input:
```
5
10 20 30 40 50
10
link 1 2
link 2 3
path_sum 1 3
path_max 1 3
path_min 1 3
update 2 100
path_sum 1 3
path_max 1 3
path_min 1 3
path_sum 1 2
```

Output:
```
60
30
10
140
100
10
110
```
