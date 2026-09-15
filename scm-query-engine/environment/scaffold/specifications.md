# Causal Inference Mathematical Specifications

## Structural Causal Model

An SCM M = (U, V, F) consists of exogenous variables U with independent uniform noise distributions, endogenous variables V, and structural equations f_i where V_i = f_i(pa(V_i), U_i). The causal graph G encodes the functional dependencies. An intervention do(X=x) replaces the structural equation for X with the constant x, while leaving all other equations and noise distributions unchanged.

## Average Treatment Effect

ATE(T→Y; t₁, t₀) = E[Y_{t₁} − Y_{t₀}]

where Y_t denotes the potential outcome under do(T=t). This is the expected individual-level causal effect — the difference in potential outcomes under two treatment values for the same individual (same noise realization).

## Counterfactual Total Effect

For discrete outcome Y with target value y:

Ctf-TE = P(Y_{t₁} = y | E) − P(Y_{t₀} = y | E)

where E = {V_F = v_F} is factual evidence (observed values of variables V_F), and Y_t | E denotes the counterfactual outcome under do(T=t) for individuals whose noise realizations are consistent with evidence E.

Computing this requires determining which noise realizations are consistent with the observed evidence, then computing the interventional outcome using only those noise realizations.

For continuous outcome (no target value), replace P(Y_t = y | E) with E[Y_t | E].

## D-Separation

Nodes X and Y are d-separated by Z in a DAG G if every undirected path between any node in X and any node in Y is blocked by Z.

A path is blocked by Z if it contains:
- A non-collider node (where the path does not have two arrowheads meeting) that IS in Z, OR
- A collider node (where two arrowheads meet, A → B ← C) where NEITHER the collider NOR any of its descendants is in Z

## Graph Mutilation

Two operations modify the causal graph for reasoning about interventions:

- Remove-incoming(S): delete all edges pointing INTO nodes in set S
- Remove-outgoing(S): delete all edges emanating FROM nodes in set S

The resulting adjacency structure includes only endogenous (non-exogenous) variables.

## Latent Projection to ADMG

An Acyclic Directed Mixed Graph (ADMG) represents causal structure using only visible (observed) variables:

- Directed edge (A → B): A has a causal effect on B, possibly through hidden intermediaries
- Bidirected edge (A ↔ B): A and B share a hidden common ancestor

To construct the ADMG: for each non-visible variable, determine which visible variables are its ancestors and which are its descendants (traversing through non-visible intermediaries), then add appropriate directed and bidirected edges among visible variables.

## Back-Door Criterion

A set Z of visible variables satisfies the back-door criterion relative to treatment X and outcome Y if:

(i) No variable in Z is a descendant of X
(ii) Z d-separates X from Y in the graph obtained by removing outgoing edges from X

When such a Z exists, it enables unconfounded estimation of the causal effect of X on Y. If no valid set of visible variables satisfies both conditions, no back-door adjustment is possible.
