A multi-module CSS cascade resolver at `/app/` implements CSS Selectors Level 4 cascade resolution in Python. The codebase handles type/class/ID/attribute selectors, `:is()`, `:not()`, `:where()`, `:has()` pseudo-classes, all four combinators, `!important`, and full cascade ordering. A specification reference is at `/app/docs/spec.md`.

The system currently resolves which CSS declarations win per element, but it is missing three critical features required by the CSS specification:

1. **CSS Custom Properties with `var()` substitution** — Custom properties (`--*`) must participate in the cascade. `var(--name)` and `var(--name, fallback)` references must be recursively substituted in property values. Cyclic `var()` references (direct or transitive) must be detected and produce guaranteed-invalid values, falling back where a fallback is provided.

2. **CSS Property Inheritance** — Inherited properties (`color`, `font-size`, `visibility`, etc.) must flow from parent to child through the DOM tree. Custom properties always inherit. The `inherit` keyword must force inheritance for any property; `initial` must reset a property and block inheritance.

3. **CSS Math Functions** — `calc()`, `min()`, `max()`, and `clamp()` expressions in property values must be parsed and evaluated with correct operator precedence, unit-aware arithmetic, and nesting support. `var()` substitution occurs before math evaluation.

These features interact: a custom property may hold a `calc()` expression, be inherited by descendant elements, and substituted via `var()`. The resolver must process the DOM tree top-down so parent values are fully resolved before children inherit them.

Extend the codebase so that `/app/cascade.py` produces correct JSON output for all selector types, custom properties, inheritance, and math functions. Custom properties (`--*`) must not appear in the output — only resolved regular properties with non-empty values.