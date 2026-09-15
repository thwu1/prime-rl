Produce `/app/quartet_tool.py` — a Python tool that computes pairwise phylogenetic quartet comparison statistics between unrooted trees in Newick format.

**Usage:**
```
python3 /app/quartet_tool.py <input.nwk> -o <output.json>
```

**Input:** One Newick tree per line (≥2 trees, all sharing the same leaf set of ≥4 leaves). Trees may contain polytomies (multifurcations), branch lengths (`:float`, ignored), and internal node labels (ignored).

**Core computation:** The C++ source at `/app/tqdist/` implements a quartet agreement calculator. It must be compiled (Makefile provided) and used for quartet computation. Pure Python quartet enumeration will not meet performance requirements for trees with ≥80 leaves. Explore the C++ source to understand the binary's interface and output semantics.

**Statistics:** For each unordered pair (i < j), produce the Estabrook et al. (1985) five-way partition of Q = C(n, 4) quartets into `s` (resolved identically in both), `d` (resolved to different topologies), `r1` (resolved in tree i, unresolved in j), `r2` (resolved in j, unresolved in i), `u` (unresolved in both). These satisfy s + d + r1 + r2 + u = Q.

**Similarity metrics:** Compute 8 named metrics derived from the Estabrook statistics. The R source files in `/app/reference/` define these metrics and their formulas: `do_not_conflict`, `explicitly_agree`, `strict_joint_assertions`, `semi_strict_joint_assertions`, `symmetric_difference`, `marczewski_steinhaus`, `steel_penny`, `quartet_divergence`. Each is a float in [0, 1] or `null` when the denominator is zero. Round to 10 decimal places.

**Output JSON:**
```json
{
  "num_trees": "<int>",
  "leaf_labels": ["<sorted strings>"],
  "pairwise": [
    {
      "i": "<int>", "j": "<int>",
      "Q": "<int>", "s": "<int>", "d": "<int>",
      "r1": "<int>", "r2": "<int>", "u": "<int>",
      "metrics": { "<key>": "<float or null>" }
    }
  ]
}
```

Pairs ordered by (i, j) ascending. All 8 metrics in every `metrics` object. Exit 0 on success, non-zero on invalid input, parse errors, or mismatched leaf sets.
