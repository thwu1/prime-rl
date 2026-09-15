# Prize-Collecting Steiner Tree (PCST)

## Problem Definition

Given an undirected weighted graph G = (V, E, w, p) where:

- V is a set of vertices
- E is a set of undirected edges
- w: E → Z⁺ assigns a positive integer weight (cost) to each edge
- p: V → Z⁺ assigns a positive integer prize to each vertex

Find a connected subtree T = (V_T, E_T) of G that maximizes the **profit**:

    profit(T) = Σ_{v ∈ V_T} p(v) − Σ_{e ∈ E_T} w(e)

The optimal solution T* has the maximum profit over all valid subtrees.
Valid solutions include:

- The **empty tree** (no nodes, no edges) with profit 0
- A **single vertex** v with profit p(v) and zero edge cost
- A **multi-vertex connected subtree** with at least one edge

## Relation to Standard Steiner Tree

The classical Steiner Tree problem designates some vertices as *terminals* that
must all be connected by a minimum-weight tree. PCST differs fundamentally:
there are no mandatory terminals. Instead, every vertex offers a prize for
inclusion, and the solver decides which vertices are worth connecting given the
edge costs. A vertex whose prize is lower than the cheapest path to reach it
from the current tree should be excluded.

## Optimization Requirement

The encoding must **prove global optimality** — it is not sufficient to find a
feasible connected subtree. The solver must exhaustively search the space of
candidate subtrees and certify that the reported profit cannot be improved.
