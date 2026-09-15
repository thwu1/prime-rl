# CSS Selectors Level 4, Custom Properties, Cascade, and Value Resolution

Reference specification extracts from W3C CSS Selectors Level 4, CSS Cascading
and Inheritance Level 4, CSS Custom Properties Level 1, and CSS Values Level 4.

## 1. Selector Specificity

A selector's specificity is a 3-tuple (a, b, c):

- **a**: Count of ID selectors (#foo)
- **b**: Count of class selectors (.bar), attribute selectors ([attr]),
  and pseudo-classes (:is(), :not(), etc.)
- **c**: Count of type selectors (div) and pseudo-elements (::before)

The universal selector (*) contributes (0, 0, 0).
Combinators (+, >, ~, whitespace) do not affect specificity.

### Pseudo-class Specificity

- `:is(sel-list)` — specificity of the most specific argument
- `:not(sel-list)` — specificity of the most specific argument
- `:where(sel-list)` — always (0, 0, 0)
- `:has(rel-sel-list)` — specificity of the most specific relative selector

## 2. Cascade Resolution

When multiple declarations target the same property on an element:

1. **Importance**: `!important` declarations beat normal declarations.
2. **Specificity**: Higher specificity wins (compare tuples lexicographically).
3. **Source order**: Later in source order wins if importance and specificity tie.

## 3. Combinator Semantics

- **Descendant** (whitespace): `A B` — B is a descendant of A at any depth.
- **Child** (`>`): `A > B` — B is a direct child of A.
- **Adjacent sibling** (`+`): `A + B` — B immediately follows A.
- **General sibling** (`~`): `A ~ B` — B follows A (any distance).

## 4. CSS Custom Properties

Custom properties are author-defined properties whose names begin with `--`
(two dashes). They are set using standard declaration syntax:

```css
:root { --main-color: #06c; }
.alert { --bg: red; }
```

Custom properties participate in the cascade and specificity exactly like
ordinary properties. They are resolved per-element using the same cascade
algorithm (importance → specificity → source order).

### Inheritance

**Custom properties are inherited properties.** If a custom property is not
declared on an element, it inherits its parent's computed value. This is the
default — unlike most CSS properties where inheritance must be opted into.

## 5. The var() Function

The `var()` function substitutes the value of a custom property:

```
var( <custom-property-name> )
var( <custom-property-name> , <fallback-value> )
```

### Substitution Rules

1. If the named custom property has a value on this element (from cascade or
   inheritance), substitute that value.
2. If the custom property is **not defined** or has a **guaranteed-invalid
   value**, use the fallback value if provided.
3. If there is no fallback and the property is undefined/invalid, the
   declaration containing the var() is invalid at computed-value time (the
   property is effectively unset).

### Recursive Substitution

Custom property values may themselves contain `var()` references:

```css
.a { --x: 10px; --y: var(--x); width: var(--y); }
/* width resolves to 10px */
```

Fallback values may also contain `var()`:

```css
.a { --backup: green; color: var(--missing, var(--backup)); }
/* color resolves to green */
```

### Cycle Detection

If custom properties form a reference cycle, all properties in the cycle
receive the **guaranteed-invalid value**:

```css
.a { --x: var(--y); --y: var(--x); }
/* Both --x and --y are guaranteed-invalid */
```

A self-referencing property is the simplest cycle:

```css
.a { --x: var(--x); }
/* --x is guaranteed-invalid */
```

When a var() references a guaranteed-invalid property, it uses its fallback
(if any), or the using property becomes invalid at computed-value time.

## 6. CSS Inheritance

### Inherited vs. Non-inherited Properties

Some CSS properties inherit by default — if not explicitly set on an element,
the element uses its parent's computed value. The following properties (among
others) are **inherited**:

    color, cursor, direction, font, font-family, font-size, font-style,
    font-variant, font-weight, letter-spacing, line-height, list-style,
    list-style-type, list-style-position, list-style-image, orphans, quotes,
    text-align, text-indent, text-transform, visibility, white-space, widows,
    word-spacing

Properties not in this set (e.g., margin, padding, border, width, height,
display, position, background) are **non-inherited** — they do not flow from
parent to child.

**All custom properties (--*) are inherited.**

### The inherit Keyword

`inherit` forces a property to take its parent's computed value, even if the
property would not normally inherit:

```css
.parent { margin: 20px; }
.child  { margin: inherit; }  /* child gets 20px */
```

### The initial Keyword

`initial` resets a property to its initial (default) value as defined by the
specification. For the purposes of this system, `initial` removes the property
from the element's computed style (it will not appear in output), and it
prevents inheritance of that property from the parent.

## 7. CSS Math Functions

### calc()

`calc()` evaluates a mathematical expression:

```css
width: calc(100px - 20px);    /* → 80px */
width: calc(10px * 3);        /* → 30px */
width: calc(100px / 4);       /* → 25px */
```

**Operator precedence**: `*` and `/` bind tighter than `+` and `-`.

**Nesting**: `calc()` may be nested:

```css
width: calc(calc(10px + 5px) * 2);  /* → 30px */
```

**Unit rules**:
- Addition/subtraction require compatible units (same unit type): `10px + 5px = 15px`
- Multiplication: one operand must be unitless: `3 * 10px = 30px`
- Division: divisor must be unitless: `100px / 4 = 25px`
- When both operands are unitless, the result is unitless.

### min(), max(), clamp()

These functions select among their arguments:

```css
width: min(100px, 50px, 200px);     /* → 50px */
width: max(10px, 30px, 20px);       /* → 30px */
width: clamp(10px, 50px, 100px);    /* → 50px */
```

**clamp(MIN, PREFERRED, MAX)** is equivalent to
`max(MIN, min(PREFERRED, MAX))`:

| Expression               | Result |
|--------------------------|--------|
| clamp(10px, 5px, 30px)   | 10px   |
| clamp(10px, 20px, 30px)  | 20px   |
| clamp(10px, 50px, 30px)  | 30px   |

All arguments to min/max/clamp must have the same unit for evaluation.

### Interaction with var()

`var()` is substituted **before** math function evaluation:

```css
:root { --gap: 8px; --cols: 3; }
.grid { width: calc(var(--gap) * var(--cols)); }
/* After var(): calc(8px * 3) → 24px */
```

## 8. Value Resolution Order

For each element, processing occurs top-down through the DOM tree:

1. **Cascade**: determine winning declarations per property (including custom).
2. **Inheritance**: for inherited properties not in the cascade, use the
   parent's computed value. Custom properties always inherit.
3. **var() substitution**: resolve var() references in all property values
   using the element's custom property values. Custom property values are
   resolved first (so they are fully substituted before being used).
4. **Math function evaluation**: evaluate calc(), min(), max(), clamp().
5. **Output**: only non-custom properties with non-empty values appear in
   the final result. Custom properties are internal to the resolution
   pipeline and should not appear in output.
