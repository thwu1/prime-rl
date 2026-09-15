# TypeSim: Structural Similarity for Python Type Annotations

## 1. Overview

TypeSim quantifies the structural similarity between two Python type annotation expressions, producing a score in [0.0, 1.0]. A score of 1.0 indicates structurally identical types; 0.0 indicates completely unrelated types. The metric is used for evaluating inferred type annotations against ground truth in large-scale Python codebases.

## 2. Type Representation

Types are represented as tree nodes (`TypeNode`) with three attributes:
- `name`: the type constructor (e.g., `"int"`, `"List"`, `"Dict"`, `"Union"`, `"Callable"`)
- `args`: an ordered list of child type nodes
- `is_variadic`: marks homogeneous tuple types (`Tuple[T, ...]`)

### 2.1 Canonical Form

All types must be in canonical form before comparison:
1. `Optional[X]` ≡ `Union[X, None]` — normalized during parsing
2. Nested unions must be flattened: `Union[Union[A, B], C]` → `Union[A, B, C]`
3. The `Ellipsis` in `Tuple[T, ...]` sets `is_variadic` but is not stored as an argument

## 3. Callable Types

`Callable[[P₁, ..., Pₙ], R]` represents a callable accepting parameter types P₁,...,Pₙ and returning type R.

The double-bracket notation requires dedicated parsing logic to distinguish the parameter list from the return type.

Callable types have two semantic components: parameter types and a return type. The tree representation must encode both in a way that allows the similarity algorithm to compare them correctly through its standard recursive traversal — without any Callable-specific case logic in the similarity function itself.

`str(parse_type(s))` must reproduce the canonical double-bracket notation for Callable types, e.g. `"Callable[[int, str], bool]"`.

## 4. Metric Properties

### 4.1 Axioms
- **Identity**: sim(a, a) = 1.0 for all types a
- **Symmetry**: sim(a, b) = sim(b, a) for all types a, b
- **Bounded**: 0.0 ≤ sim(a, b) ≤ 1.0

### 4.2 Fast Path
If the canonical string representations of two types are identical, the similarity is 1.0.

### 4.3 Constructor Comparison
Similarity between non-union types begins with comparing their top-level constructor names:
- Identical constructors indicate maximum structural compatibility
- The special type `Any` acts as a wildcard: partial compatibility with every other type
- Different, non-wildcard constructors have no structural compatibility

### 4.4 Argument Integration

The final score for non-union types combines the constructor comparison with recursive comparison of type arguments. The exact combination depends on the structural relationship:

- **Both have arguments**: Arguments at corresponding positions are compared recursively. The final score integrates both the constructor similarity and the positional argument similarities. When argument lists differ in length, unmatched positions reduce the argument contribution.

- **Exactly one has arguments**: The structural asymmetry between the types attenuates the score.

- **Neither has arguments**: The constructor comparison alone determines the score.

Derive the exact integration formulas from the 40 validation cases in `/app/test_cases.json`.

### 4.5 Union Semantics

Union types represent unordered sets of alternative types. Comparing two unions — or comparing a union against a non-union type (treating the non-union as a single-member union) — must respect this unordered semantics: the comparison should find the best possible pairing between members of each side. The score reflects size differences between the member sets.

## 5. Validation

`/app/test_cases.json` contains 40 test cases with expected similarity scores. All computed scores must match expected values within ±0.001 tolerance. Run `/app/compute_similarity.py` for diagnostics.
