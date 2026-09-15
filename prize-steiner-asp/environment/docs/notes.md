# ASP Encoding Notes

## Weak Constraints

ASP-Core-2 weak constraints have the syntax `:~ body. [weight, priority, terms]`
and direct the solver to **minimize** total penalty. To maximize a quantity, use
negative weights for the terms you want to maximize.

Weight tuples serve as identifiers — distinct terms prevent the solver from
merging penalties from independent sources.

## Connectivity in Undirected Graphs

When instance edges use a canonical ordering (first endpoint < second),
reachability rules must propagate in both directions. A common error is to
encode reachability with single-direction traversal that only follows the
ordering of the edge predicate.

## Tree Acyclicity

A connected subgraph on N vertices with exactly N−1 edges is necessarily
acyclic (a tree). This structural invariant, combined with connectivity
enforcement, eliminates cycles without explicit cycle-detection rules.

## Degenerate Solutions

Optimization encodings must permit degenerate cases: a single selected vertex
(zero edges, profit equals that vertex's prize) or the empty selection (zero
profit). Constraints that implicitly require at least two vertices or at least
one edge will exclude these valid candidates, potentially missing the true
optimum.

## Root Selection for Reachability

When enforcing connectivity via reachability from a designated root, the root
must be chosen deterministically from the selected subset — not from the full
vertex set. A common approach is to designate the minimum-ID selected vertex
as root.
