The adaptive merge sort framework at `/app/` needs a merge scheduling algorithm. In adaptive sorting, an array is first scanned for naturally pre-sorted subsequences ("runs"), then those runs are merged pairwise. The order in which adjacent runs are merged dramatically affects the total merge cost. Only adjacent runs may be merged, and the cost of each merge equals the combined length of the two segments.

Implement `compute_schedule(run_lengths)` in `/app/scheduler.py`. It receives a list of positive integer run lengths and must return `(cost, merge_tree)` where:
- `cost` is the total merge cost
- `merge_tree` is a nested binary tree: leaf = integer run index (0..n-1, in left-to-right order), internal node = `(left, right)` tuple

Your algorithm must:
- Achieve merge costs within 5% of the exact optimum (the O(n^2) DP in `/app/reference_dp.py`) across uniform, geometric, alternating, spike, and Fibonacci-like run-length distributions
- Handle 200,000 runs in under 5 seconds
- Report cost consistent with the tree structure
- Outperform the balanced binary baseline in `/app/baselines/balanced.py` by a significant margin on skewed distributions

Study the baseline strategies in `/app/baselines/`, the reference DP, and the merge engine utilities before designing your approach.