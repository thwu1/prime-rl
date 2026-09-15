# GLSL ES 3.00 -- Link-Time Validation Rules (Excerpts)

## Section 4.3.10: Linking of Varying Variables

Fragment shader `in` variables form the input interface. These are matched by
name against vertex shader `out` variables.

### Type Matching
The type of a vertex shader `out` variable must exactly match the type of the
corresponding fragment shader `in` variable. When the types differ, a link
error must be generated.

### Precision Qualifiers
If both matching declarations carry explicit precision qualifiers (`lowp`,
`mediump`, `highp`), the qualifiers must agree. When either side omits an
explicit precision qualifier (relying on the stage's default precision), no
link error is generated for precision.

### Interpolation Qualifiers
Interpolation qualifiers (`smooth`, `flat`) must match between vertex output
and fragment input. `smooth` is the default when no interpolation qualifier is
specified. `centroid` is an auxiliary storage qualifier that modifies
interpolation sampling; for link-matching purposes it is treated as a distinct
qualifier -- a `centroid out` declaration does NOT match a bare `out`
declaration (which implies `smooth` without `centroid`).

### Invariant Qualification
If either the vertex output or fragment input is declared `invariant`, then
both must be declared `invariant`. A mismatch in invariant qualification
constitutes a link error.

### Array Dimensions
When varyings are arrays, the array sizes must match between the vertex output
and fragment input. Both declaration forms -- `type[N] name` and
`type name[N]` -- are valid and semantically equivalent.

### Struct Types
Struct-typed varyings are matched structurally: member names, member types,
and member declaration order must all match. The struct type name itself may
differ between compilation units.

### Layout Qualifiers
If both the vertex output and fragment input carry explicit
`layout(location = N)` qualifiers, the location values must agree. Whitespace
within the layout qualifier syntax is permitted; for example
`layout( location = 0 )` is equivalent to `layout(location=0)`.

## Section 4.3.5: Uniform Variables

Uniform variables with the same name appearing in both vertex and fragment
shaders must have matching types. A type mismatch in shared uniform variables
is a link error.

## Section 4.3.4: Declarations

Multiple variables may be declared in a single declaration statement,
separated by commas:

    out vec4 varA, varB, varC;

This is equivalent to three separate declarations and each variable inherits
all qualifiers from the declaration.
