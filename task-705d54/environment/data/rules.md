# Type Hierarchy Validation Rules

These rules are derived from the Java Language Specification (JLS) Chapters 8 and 9,
as used in the Joos 1W language subset. A hierarchy validator must check all 14 rules.

## Terminology

- **Signature**: A method's signature consists of its name and parameter types (order matters). Return type and modifiers are NOT part of the signature.
- **Replace**: A method `m` in type `T` **replaces** a method `m'` in supertype `S` if `m` and `m'` have the same signature. This covers both overriding (instance methods) and hiding (static methods).
- **Contain**: A type **contains** a method if it either declares it or inherits it. When a declared method replaces an inherited method, only the declared version is considered "contained" (the inherited version is replaced).

## Rules

### Rule 1: Class must not extend an interface
A class's `extends` clause must reference a class, not an interface. (JLS 8.1.3)

### Rule 2: Class must not implement a class
A class's `implements` clause must reference interfaces only, not classes. (JLS 8.1.4)

### Rule 3: No repeated interface
An interface must not be repeated in an `implements` clause of a class, or in an `extends` clause of an interface. (JLS 8.1.4)

### Rule 4: Must not extend a final class
A class must not extend a class that has the `final` modifier. (JLS 8.1.1.2, 8.1.3)

### Rule 5: Interface must not extend a class
An interface's `extends` clause must reference interfaces only, not classes. (JLS 9.1.2)

### Rule 6: Acyclic hierarchy
The type hierarchy (considering both `extends` and `implements`/interface-`extends` relationships) must be acyclic. Every type involved in a cycle violates this rule. (JLS 8.1.3, 9.1.2)

### Rule 7: No duplicate method signatures
A class or interface must not declare two methods with the same signature (same name and parameter types). (JLS 8.4, 9.4)

### Rule 8: No duplicate constructor signatures
A class must not declare two constructors with the same parameter types. (JLS 8.8.2)

### Rule 9: No conflicting inherited methods
A class or interface must not contain two methods with the same signature but different return types. This catches the case where two unrelated supertypes provide methods with the same signature but incompatible return types, and neither is replaced by a local declaration. (JLS 8.4.6.3, 8.4.6.4, 9.2, 9.4.1)

### Rule 10: Abstract methods require abstract class
A class that contains (declares or inherits) any abstract methods must itself be declared `abstract`. This includes abstract methods inherited transitively through the superclass chain or from implemented interfaces. (JLS 8.1.1.1)

### Rule 11: Non-static must not replace static
A non-static method must not replace a static method from a supertype. (JLS 8.4.6.1)

### Rule 12: Replacement must preserve return type
A method must not replace a method with a different return type. Covariant return types are NOT allowed. (JLS 8.4.6.3)

### Rule 13: Must not narrow access
A protected method must not replace a public method. Access may stay the same or widen, but must not narrow. (JLS 8.4.6.3)

### Rule 14: Must not replace final method
A method must not replace a method that has the `final` modifier. (JLS 8.4.3.3)

## Checking guidance

- Rules 1-5, 7, 8 can be checked locally without full inheritance traversal.
- Rule 6 requires graph-based cycle detection across the full hierarchy.
- Rules 9-14 require computing inherited methods by traversing the inheritance chain.
- For types involved in inheritance cycles (Rule 6), only report Rule 6. Do not attempt inheritance-based checks (Rules 9-14) since the chain cannot be resolved.
- When collecting inherited methods, the same method may be reachable through multiple paths (diamond inheritance). Deduplicate by tracking the type where the method was originally declared.
