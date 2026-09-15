# Joos 1W Language Restrictions

Joos 1W is a subset of Java 1.3 used in compiler construction courses. The
following restrictions apply relative to standard Java. When the JLS permits
a construct that Joos 1W does not support, the JLS rule does not apply.

## Type System Restrictions
- No covariant return types: overriding methods must have exactly the same
  return type as the overridden method (not merely assignment-compatible).
- No generics, parameterized types, or wildcard types.
- No enums, annotations, or record types.

## Class and Interface Restrictions
- No inner classes, anonymous classes, or local classes.
- No default methods in interfaces (all interface methods are abstract).
- No static methods in interfaces.
- Interfaces may only contain abstract method declarations.
- Each source file contains exactly one public type declaration.

## Modifier Restrictions
- Permitted class modifiers: public, abstract, final.
- Permitted method modifiers: public, protected, static, final, abstract, native.
- All type declarations are public (no package-private types).
- A method may not be both abstract and final.
- A method may not be both abstract and static.

## Inheritance Model
- Single class inheritance: a class may extend at most one other class.
- Multiple interface implementation: a class may implement zero or more interfaces.
- Interfaces may extend zero or more other interfaces.
- If two supertypes contribute methods with the same signature but different
  return types, and the inheriting type does not declare its own method with
  that signature, this is a compile-time error.

## Constructor Requirements
- Every class must have at least one explicitly declared constructor.
- No implicit default constructors are generated.
