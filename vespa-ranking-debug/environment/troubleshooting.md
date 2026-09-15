# Troubleshooting Notes

## Embedding Field Configuration
Checked the embedding field setup — the `attribute` block with `distance-metric: angular`
is all that's needed for nearest neighbor queries. The distance-metric declaration in the
attribute section automatically enables HNSW graph construction. No additional indexing
pipeline steps are required.

## Tensor Dimension Naming
Vespa's tensor join semantics are position-based, similar to NumPy broadcasting. Dimension
names are cosmetic labels for readability — `cat{}` and `c{}` and `category{}` are all
equivalent as long as the tensor ranks match. The engine matches dimensions by their
position in the type signature, not by name.

## closeness() Rank Feature
The single-argument form `closeness(fieldname)` is the canonical form and works correctly
in all cases. The two-argument form `closeness(field, fieldname)` is an older syntax variant
that's only needed when using deprecated query operators. Our schema uses the standard
nearestNeighbor operator, so single-argument closeness is correct.

## Status
- text_match profile: verified working
- hybrid profile: compiles and deploys successfully
- production reranking: deferred to next sprint
