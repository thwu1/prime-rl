The SDSL (Succinct Data Structure Library) v3 is a header-only C++ library pre-installed at `/opt/sdsl` (headers at `/opt/sdsl/include`). A 3,000-character DNA-alphabet text corpus is at `/app/corpus.txt` and a set of query patterns is at `/app/queries.txt` (one per line).

Write a C++ program that uses SDSL v3 to construct a compressed suffix tree over the corpus and output `/app/results.json` with the following fields:

- `num_internal_nodes` (integer): total internal nodes in the suffix tree, including the root
- `num_leaves` (integer): total leaf nodes
- `longest_repeat_length` (integer): string depth of the deepest internal node (longest repeated substring)
- `longest_repeat_string` (string): the longest repeated substring itself; lexicographically first if tied
- `longest_repeat_frequency` (integer): number of occurrences of the longest repeated substring
- `num_maximal_repeats` (integer): count of maximal repeats with string depth > 0. A **maximal repeat** is an internal node that is left-diverse: the set of BWT characters at positions `lb(v)..rb(v)` contains more than one distinct value (the sentinel counts as a distinct character)
- `num_supermaximal_repeats` (integer): count of supermaximal repeats. A **supermaximal repeat** is a maximal repeat where every child in the suffix tree is a leaf
- `space_bytes` (integer): serialized size of the CST in bytes
- `pattern_counts` (object): maps each query pattern from `/app/queries.txt` to its occurrence count in the corpus

The program must compile against the pre-installed SDSL headers and produce valid JSON at `/app/results.json`.