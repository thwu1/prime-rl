Sudoku Unavoidable Set Analysis Tools
=====================================

ua_finder.c
  Finds 2-digit unavoidable sets in a sudoku solution grid using
  column permutation cycle analysis. Compile with 'make'.
  Usage: ./ua_finder [max_size] < grid.txt
  Output: one set per line, comma-separated cell indices (0-80)

  Limitation: only finds 2-digit trades. Multi-digit unavoidable
  sets (3+ distinct digits) require separate analysis.

clique_finder.py
  Computes the Maximum Clique Number (MCN) of the disjointness
  graph of unavoidable sets using the Bron-Kerbosch algorithm.
  Also counts cliques of sizes 2 through 5.
  Usage: python3 clique_finder.py sets.json
  Input: JSON array of unavoidable sets (each a sorted list of cell indices)
  Output: JSON with mcn, max_clique_indices, clique_counts
