# Arborescence Distribution

## Definitions

An **arborescence** rooted at node 0 over nodes {0, 1, ..., n} is a directed subgraph where:
- Every non-root node j (1 <= j <= n) has exactly one incoming arc (i -> j) with i != j
- Node 0 has no incoming arcs
- Following head pointers from any node eventually reaches 0 (no directed cycles)

## Probability Distribution

Given a score matrix S of shape (n+1, n+1):
- Arc weight: w(i->j) = exp(S[i][j]),  defined for i != j and j >= 1
- Tree weight: W(t) = product of w(i->j) for each arc (i->j) in tree t
- Normalizing constant: Z = sum of W(t) over all valid arborescences t
- Tree probability: P(t) = W(t) / Z

## Derived Quantities

- **Arc marginal**: P(i->j) = sum of P(t) over all arborescences t containing arc (i->j)
- **Column constraint**: For each non-root node j, the marginals over all possible heads sum to 1
- **Total arcs**: The sum of all arc marginals equals n (each tree has exactly n arcs)
- **Shannon entropy**: H = -sum over t of P(t) * ln(P(t))
- **KL divergence**: KL(P||Q) = sum over t of P(t) * ln(P(t) / Q(t))

## Complexity

The number of valid arborescences grows super-exponentially with n. Direct enumeration is infeasible beyond very small instances.
