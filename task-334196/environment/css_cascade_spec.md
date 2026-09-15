# CSS Cascading and Inheritance — Specification Reference
## Abridged from CSS Cascading and Inheritance Level 4 (W3C)


### 1. The Cascade

The cascade takes a set of CSS declarations targeting the same element and
determines which declaration wins for each property.

#### 1.1 Cascade Sorting Order

The cascade sorts declarations according to the following criteria, in
descending priority:

1. **Origin and Importance**
2. **Specificity**
3. **Order of Appearance** (source order — later declarations win)

#### 1.2 Cascading Origins

There are three cascade origins:

- **User-Agent Origin**: Default styles provided by the rendering engine.
- **Author Origin**: Styles specified by the document author (page stylesheets).
- **User Origin**: Styles set by the end user (user preferences, accessibility overrides).

#### 1.3 Important Declarations and Origin Priority

A declaration is "important" if it includes the `!important` annotation.

Important declarations from different origins are sorted in **reverse order**
compared to normal declarations. This design ensures that user accessibility
overrides cannot be overridden by page author styles.

**Normal declarations (ascending priority):**

1. User-Agent normal
2. User normal
3. Author normal

**Important declarations (ascending priority):**

4. Author !important
5. User !important
6. User-Agent !important

The complete cascade priority from lowest to highest is therefore:

| Priority | Origin | Importance |
|----------|--------|------------|
| 1 (lowest) | User-Agent | normal |
| 2 | User | normal |
| 3 | Author | normal |
| 4 | Author | !important |
| 5 | User | !important |
| 6 (highest) | User-Agent | !important |

**Key consequence:** A user's `!important` declaration always beats an author's
`!important` declaration for the same property on the same element.

### 2. Specificity

When two declarations have the same origin and importance, specificity
determines which wins.

#### 2.1 Calculating Specificity

A selector's specificity is represented as a triple **(a, b, c)**:

- **a**: Count of **ID selectors** (`#foo`)
- **b**: Count of **class selectors** (`.foo`), **attribute selectors**
  (`[attr]`, `[attr=val]`, `[attr~=val]`, etc.), and **pseudo-classes**
  (`:hover`, `:first-child`, etc.)
- **c**: Count of **type selectors** (`div`, `p`, `h1`) and
  **pseudo-elements** (`::before`, `::after`)

The **universal selector** (`*`) contributes zero to all components.

#### 2.2 Comparing Specificity

Specificity triples are compared **lexicographically** from left to right.
The `a` component is compared first; if equal, the `b` component; if still
equal, the `c` component. Thus `(1, 0, 0)` is greater than `(0, 99, 99)`.

#### 2.3 Specificity Examples

| Selector | (a, b, c) | Reason |
|----------|-----------|--------|
| `p` | (0, 0, 1) | 1 type |
| `.intro` | (0, 1, 0) | 1 class |
| `p.intro` | (0, 1, 1) | 1 class + 1 type |
| `#main` | (1, 0, 0) | 1 ID |
| `a[href]` | (0, 1, 1) | 1 attribute + 1 type |
| `a[data-external="true"]` | (0, 1, 1) | 1 attribute + 1 type |
| `div.content p` | (0, 1, 2) | 1 class + 2 types |
| `.content > p.highlight` | (0, 2, 1) | 2 classes + 1 type |

### 3. Selector Matching

#### 3.1 Descendant Combinator (whitespace)

`A B` matches element B that is a **descendant** of element A at any nesting
depth. Example: `div p` matches any `<p>` inside a `<div>`, regardless of
how deeply nested.

#### 3.2 Child Combinator (`>`)

`A > B` matches element B only when B is a **direct child** of element A.
It does **not** match if B is a grandchild or deeper descendant.

Example: Given `<div class="a"><span class="b"><p></p></span></div>`:
- `.a > p` does **NOT** match `<p>` (p is grandchild of .a)
- `.b > p` **DOES** match `<p>` (p is direct child of .b)
- `.a p` **DOES** match `<p>` (descendant combinator, any depth)

### 4. Shorthand Properties

Shorthand properties set multiple longhand properties simultaneously.

#### 4.1 margin and padding

These shorthands accept 1 to 4 values, mapped to the four sides as follows:

| Count | top | right | bottom | left |
|-------|-----|-------|--------|------|
| 1 value: `v` | v | v | v | v |
| 2 values: `v h` | v | h | v | h |
| 3 values: `v h b` | v | h | b | **h** |
| 4 values: `t r b l` | t | r | b | l |

**Critical note on 3-value form:** In the 3-value syntax `top right bottom`,
the **left** side takes the same value as **right** (the second value), NOT
the bottom (third value). The mnemonic is: omitted left mirrors right.

### 5. CSS-Wide Keywords

These keywords are valid for every CSS property and are resolved during
computed value calculation.

#### 5.1 `initial`

Sets the property to its **initial value** as defined in the property's
specification. The initial value is a fixed default that does not depend on
the element's parent or position in the document tree.

Example: `color: initial` resolves to `black` (the initial value of the
`color` property, not the literal string "initial").

#### 5.2 `inherit`

Takes the property's **computed value from the parent element**. If the
element has no parent (i.e., it is the root element), the property's
initial value is used instead.

#### 5.3 `unset`

Acts as `inherit` if the property is a naturally **inherited property**,
or as `initial` if it is a naturally **non-inherited property**.

Whether a property inherits by default is defined in the property's
specification. Common inherited properties include `color`, `font-size`,
`font-weight`, `font-family`, `line-height`, and `text-align`. Common
non-inherited properties include `display`, `margin-*`, `padding-*`,
`background-color`, `width`, and `height`.

Example: If `color` (inherited) has value `unset`, it behaves as `inherit`.
If `display` (non-inherited) has value `unset`, it behaves as `initial`.

### 6. Inheritance

After the cascade determines a property's cascaded value, inheritance fills
in properties that received no cascaded value:

- **Inherited properties** (e.g., `color`, `font-size`): If no rule sets
  the property on this element, it takes the parent's computed value.
  At the root element, the property's initial value is used.
- **Non-inherited properties** (e.g., `display`, `margin`): If no rule
  sets the property, it takes its initial value regardless of what the
  parent has.
