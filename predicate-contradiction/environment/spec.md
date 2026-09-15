# Legal Predicate Comparison: Semantic Reference

This document describes the semantics of legal predicate comparison, based on the
nettlesome framework's approach to modeling factual assertions in legal proceedings.

## 1. Data Sources

Predicate data is split across two sources that must be integrated:

- **YAML holdings file** (`/app/holdings.yaml`): Contains predicate definitions organized by
  judicial opinion, including templates, quantity comparisons with physical units, and truth values.
  Predicates are nested under `opinions[].facts[]`, each identified by a `predicate_id`.

- **SQLite database** (`/app/terms.db`): Contains entity term assignments in the `predicate_terms`
  table (columns: `predicate_id`, `position`, `term_name`, `is_generic`) and interchangeable
  position group declarations in the `interchangeable_groups` table (columns: `predicate_id`,
  `group_index`, `position`).

A complete predicate object requires merging data from both sources by `predicate_id`.

## 2. Predicate Structure

Each fully-assembled predicate consists of:
- A **template** string with `{placeholder}` markers defining the assertion's structure
- An ordered list of **terms** filling those placeholders, each classified as *generic* (representing
  a universal or abstract entity) or *specific* (a named, particular entity)
- A **truth value**: `true`, `false`, or `null` (the "whether" state—an assertion that the
  fact is relevant without committing to its truth or falsity)
- An optional **quantity comparison** with a sign (`>=`, `>`, `<=`, `<`), magnitude, and physical unit
- Zero or more **interchangeable groups**: sets of term positions whose occupants are semantically
  symmetric (swapping them does not alter the predicate's meaning)

## 3. Template Compatibility

Two predicates can only participate in a semantic relationship if they are **template-compatible**:
identical template strings, identical term counts, and either both have a quantity comparison or
neither does.

## 4. Quantity Comparisons and Unit Conversion

A quantity comparison defines a set of values on the real number line via its sign and magnitude:
lower-bounded sets (for `>=` and `>`) or upper-bounded sets (for `<=` and `<`). The boundary
may be inclusive or exclusive depending on strictness.

Physical units must be converted using the **pint** library (`pint.UnitRegistry`) before comparing
magnitudes across different unit systems. Do not hard-code conversion factors—use pint's
dimensional analysis to handle all unit conversions programmatically.

When determining whether one comparison's value set is **contained within** another's, or whether
two value sets are **disjoint**, boundary strictness is load-bearing: a strict boundary (`>` or `<`)
excludes its endpoint while a non-strict boundary (`>=` or `<=`) includes it. The correct treatment
of boundary cases must be derived from the set-theoretic definitions of containment and disjointness.

## 5. Term Compatibility and Context Registers

When testing whether predicate A can *imply* predicate B, a **directed term compatibility** check
determines which term mappings are valid:

- A *generic* term represents a universal claim and is compatible with any term position
- A *specific* term can only map to the identical specific name
- A specific term cannot map to a generic term (a particular instance does not generalize)

A **context register** is a bijective mapping between the term positions of two predicates such that
every mapped pair satisfies directed compatibility. A valid register must be consistent: each source
position maps to exactly one target position and vice versa.

## 6. Interchangeable Groups and Meaning-Preserving Permutations

The `interchangeable_groups` table declares which term positions can be freely permuted without
changing the predicate's meaning. For example, if positions 0 and 1 are interchangeable, then
filling them with `(Alice, Bob)` or `(Bob, Alice)` yields semantically identical predicates.

When searching for a valid context register, all meaning-preserving permutations from both
predicates' interchangeable groups must be explored. The search space is the Cartesian product
of each group's permutations, applied independently to each predicate.

## 7. Comparison Predicate Normalization

When a comparison predicate has `truth = false`, the comparison sign must be logically negated
(`>=` ↔ `<`, `>` ↔ `<=`) and truth set to `true`. This normalization ensures all semantic
comparisons operate on positive assertions. Non-comparison predicates are not affected.

## 8. Truth Value Entailment

- Both `true` and `false` entail `null` (knowing the definite truth value implies the question is relevant)
- `null` entails only `null`
- `true` and `false` each entail themselves but not each other
- Only `true` and `false` can contradict each other; `null` never participates in contradiction

## 9. Semantic Relationships

**Implication** (A implies B): Template compatibility, a valid directed context register from A to B,
and semantic content where A is at least as specific as B (quantity range containment or truth entailment).

**Contradiction** (A contradicts B): Template compatibility, a valid context register in at least one
direction (A→B or B→A), and incompatible semantic content (disjoint quantity ranges or opposed truth values).

**Equivalence**: Mutual implication—A implies B and B implies A.

## 10. Output Requirements

Results must be written to two locations:

1. **`/app/results.json`** — JSON object with keys `equivalent`, `implies`, `contradicts`
2. **`/app/results.db`** — SQLite database with table `relationships(id_a TEXT, id_b TEXT, relation TEXT)`

In both outputs: equivalent and contradicts pairs are stored with IDs sorted alphabetically;
implies pairs are ordered `[A, B]` meaning A implies B.
