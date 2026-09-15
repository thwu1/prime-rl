Build an exact solver for the **twinwidth** problem. Your solver must read a graph in PACE `.gr` format from stdin and write a minimum-width contraction sequence to stdout.

## Twinwidth

A *trigraph* is a graph whose edges are colored black or red. All edges begin black. A *contraction* of the ordered pair (x, y) merges y into x: y is deleted, and for each remaining vertex z:

- if z was adjacent to both x and y, the edge x–z retains its current color;
- if z was adjacent to exactly one of x or y, the edge x–z becomes (or stays) red;
- if z was adjacent to neither, no edge is created.

Any pre-existing edge between x and y is simply deleted. "Adjacent" means connected by any edge regardless of color.

A *contraction sequence* for an n-vertex graph is n−1 contractions reducing it to a single vertex. Its *width* is the maximum red degree of any vertex at any point during the process. The *twinwidth* of a graph is the minimum width over all valid contraction sequences.

## I/O

**Input** (stdin, PACE `.gr`):
```
c optional comment
p tww <n> <m>
<u> <v>
```
Vertices 1…n, m undirected edges.

**Output** (stdout): exactly n−1 lines, each `<x> <y>` — contract y into x (x survives).

## Task

Create an executable at `/app/solver` that computes **optimal** (minimum-width) contraction sequences. The solver must efficiently handle all benchmark instances provided in `/app/instances/`. Instance graphs range from small to moderately sized — brute-force enumeration in an interpreted language will not scale to the larger instances.

Explore `/app/` for benchmark instances, development tools, and documentation.