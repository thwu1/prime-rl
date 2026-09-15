% Standard Steiner Tree encoding (ASP-Core-2)
%
% Problem: given terminal vertices and optional Steiner vertices,
% find the minimum-weight tree connecting ALL terminals.
%
% Input predicates:
%   node(V)          — vertex V exists
%   terminal(V)      — vertex V is a required terminal
%   edge(U,V,W)      — undirected edge with weight W, U < V
%
% This encoding assumes all terminals MUST be included.
% It does NOT apply to problems where vertex inclusion is optional.

% All terminals are in the tree; Steiner vertices are optional
in_tree(V) :- terminal(V).
{ in_tree(V) } :- node(V), not terminal(V).

% Select edges between tree vertices
{ use_edge(U,V) } :- edge(U,V,_), in_tree(U), in_tree(V).

% Determine root as minimum terminal
has_smaller_terminal(V) :- terminal(V), terminal(U), U < V.
root(V) :- terminal(V), not has_smaller_terminal(V).

% Reachability from root (undirected traversal)
reach(V) :- root(V).
reach(V) :- reach(U), use_edge(U,V).
reach(U) :- reach(V), use_edge(U,V).

% All tree nodes must be reachable
:- in_tree(V), not reach(V).

% Tree structure: exactly n-1 edges for n nodes
tree_nodes(N) :- N = #count { V : in_tree(V) }.
tree_edges(M) :- M = #count { U,V : use_edge(U,V) }.
:- tree_nodes(N), tree_edges(M), N > 0, M != N - 1.

% No isolated Steiner vertices (optimization: prune useless vertices)
:- in_tree(V), not terminal(V),
   #count { U : use_edge(V,U) ; U : use_edge(U,V) } = 0.

% Minimize total edge weight
:~ use_edge(U,V), edge(U,V,W). [W,U,V]

#show in_tree/1.
#show use_edge/2.
