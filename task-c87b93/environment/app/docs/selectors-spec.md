# CSS Selectors Level 4 — Specificity and Cascade Reference

Extracted from W3C CSS Selectors Level 4 and CSS Cascading Level 4 specifications.

## Specificity Calculation

A selector's specificity is a 3-tuple (a, b, c):

- **a**: Count of ID selectors (#foo)
- **b**: Count of class selectors (.bar), attribute selectors ([attr]),
  and pseudo-classes (:is(), :not(), etc.)
- **c**: Count of type selectors (div) and pseudo-elements (::before)

The universal selector (*) contributes (0, 0, 0).
Combinators (+, >, ~, whitespace) do not affect specificity.

## Pseudo-class Specificity

### :is(selector-list)
Contributes the specificity of the **most specific** selector in its
argument list. The pseudo-class itself does not add to the b component.

Example: `:is(.foo, #bar)` has specificity (1,0,0) from #bar.

### :not(selector-list)
Same rule as :is() — takes the specificity of the most specific
argument. The pseudo-class itself does not add to b.

### :where(selector-list)
The specificity of :where() is **always (0, 0, 0)**, regardless of its
arguments. This is the defining difference between :where() and :is().

This allows authors to add filtering conditions without increasing
specificity, useful for resets and default styles.

### :has(relative-selector-list)
Contributes the specificity of the most specific relative selector
in its argument list. Each relative selector's specificity includes
its combinator's compound selectors.

## Cascade Resolution

When multiple declarations target the same property on an element,
the cascade determines the winner:

1. **Importance**: `!important` declarations beat normal declarations.
   Among two !important declarations, proceed to step 2.
2. **Specificity**: Higher specificity wins. Compare tuples
   lexicographically: (a1,b1,c1) > (a2,b2,c2) iff a1>a2, or
   a1==a2 and b1>b2, or a1==a2 and b1==b2 and c1>c2.
3. **Source order**: If importance and specificity are equal, the
   declaration appearing **later** in source order wins.

## Combinator Semantics

### Descendant combinator (whitespace)
`A B` — B is a descendant of A at any depth.

### Child combinator (>)
`A > B` — B is a direct child of A.

### Adjacent sibling combinator (+)
`A + B` — B immediately follows A as siblings of the same parent.
Only the **single immediately preceding** element sibling is tested.
If A is not B's immediately preceding sibling, the selector does not
match, even if A appears elsewhere among B's preceding siblings.

### General sibling combinator (~)
`A ~ B` — B follows A as siblings of the same parent.
**Any** preceding sibling matching A satisfies the selector.
