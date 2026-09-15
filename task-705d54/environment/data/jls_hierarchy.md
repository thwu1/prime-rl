# Type Hierarchy Specification (JLS Chapters 8 and 9)

This document specifies the compile-time rules governing class and interface
type hierarchies as defined by the Java Language Specification, Second Edition.
A conforming compiler must reject any program that violates these rules.

## 8.1.1 Class Modifiers

A class declaration may include the modifier `abstract` or `final` (but not
both). An abstract class is incomplete and cannot be instantiated directly.

### 8.1.1.1 abstract Classes

A class C has abstract methods if any of the following is true:

- C explicitly contains a declaration of an abstract method.
- C inherits an abstract method: that is, a method declared abstract in a
  superclass or superinterface of C such that C contains no method declaration
  that overrides it.

It is a compile-time error if a class that is not declared abstract contains
(declares or inherits) any abstract method. In the presence of multi-level
inheritance, the set of abstract obligations must be computed transitively.
For example, if class A implements interface I and declares some of I's
methods, and concrete class B extends A, class B is still responsible for
providing implementations of any of I's methods that A left unimplemented.
The effective method set of a class is the union of its own declared methods
and all methods inherited from every supertype (class and interface), with
declared methods taking precedence over inherited methods of the same
signature.

### 8.1.1.2 final Classes

A class can be declared final if its definition is considered complete and no
subclasses are permitted. It is a compile-time error if the name of a final
class appears in the extends clause of another class declaration.

## 8.1.3 Superclasses and Subclasses

The optional extends clause in a class declaration specifies the direct
superclass of the current class. The following constraints apply:

- The type named in the extends clause of a class must be a class type, not
  an interface type. It is a compile-time error if a class attempts to extend
  an interface.
- The class hierarchy must be acyclic. That is, a class C cannot extend a
  class S if S is the same class as C, or if S extends C either directly or
  indirectly. A compile-time error occurs if such a cycle is detected.

## 8.1.4 Superinterfaces

The optional implements clause in a class declaration lists the interfaces
that are direct superinterfaces of the class being declared.

- Each name in the implements clause must name an interface type, not a class
  type. It is a compile-time error if any name in the implements clause of a
  class declaration names a class rather than an interface.
- A type name must not appear more than once in a single implements clause
  of a class, even if the interface is named through different qualified paths.
  Duplicate interface references are a compile-time error.

## 8.4 Method Declarations

### 8.4 Signatures

A class or interface must not declare two methods with the same signature.
The signature of a method consists of its name and the ordered list of
formal parameter types. The return type, modifiers, and throws clause are
not part of the signature. Two methods with the same name but different
parameter type lists are considered overloaded, which is permitted.

### 8.4.3.3 final Methods

A method can be declared final to prevent subclasses from overriding or
hiding it. It is a compile-time error if a method declaration overrides or
hides a method that was declared final in a supertype. This check must
consider the full supertype chain, not just the direct superclass, since a
final method may be declared several levels up in the hierarchy.

## 8.4.6 Inheritance, Overriding, and Hiding

A method declared in class C replaces a method declared in a supertype S of
C if both methods have the same signature. This subsumes both overriding
(instance methods) and hiding (static methods). Replacement is checked
against the full transitive set of inherited methods, not just the direct
superclass.

### 8.4.6.1 Static and Non-Static

If a non-static method replaces a static method, a compile-time error
occurs. The reverse (a static method hiding a non-static method) is also
an error in general, but only the former is checked at this stage.

### 8.4.6.3 Requirements in Overriding and Hiding

The following requirements must be satisfied when a method d1 overrides or
hides another method d2:

Return type: The return type of d1 must be identical to that of d2.
Covariant return types are not permitted.

Access: The access modifier of d1 must provide at least as much access as
d2. In particular, if d2 is public, d1 must also be public. A protected
method must not override a public method, as this would narrow the access.

### 8.4.6.4 Inheriting Methods with Override-Equivalent Signatures

A class or interface may inherit multiple methods with the same signature
from different supertypes, particularly in the case of diamond inheritance
through interfaces. If these methods have different return types and the
inheriting type does not itself declare a method with that signature that
resolves the conflict, a compile-time error results. When inherited methods
have the same signature and the same return type, they are considered
compatible and no error occurs. The deduplication of inherited methods must
track the originating declaration to correctly handle the diamond pattern
where the same method is reachable through multiple paths.

## 8.8.2 Constructor Declarations

It is a compile-time error for a class to declare two constructors with the
same parameter types. Constructor signatures consist only of the parameter
type list.

## 9.1.2 Superinterfaces of Interfaces

An interface may extend one or more other interfaces by naming them in its
extends clause. The following rules apply:

- The names in the extends clause of an interface declaration must name
  interface types, not class types. It is a compile-time error if an
  interface attempts to extend a class.
- No interface name may appear more than once in a single extends clause of
  an interface. Duplicate extends references are a compile-time error.
- The interface hierarchy must be acyclic. If an interface I extends an
  interface J, and J extends I (directly or indirectly), a compile-time
  error occurs. The acyclicity check for interfaces and classes must be
  unified: the overall type hierarchy combining both extends and implements
  relationships must form a directed acyclic graph.

## 9.2 Interface Members

The members of an interface include both those declared in the interface body
and those inherited from direct superinterfaces. An interface inherits from
its direct superinterfaces all abstract methods of those superinterfaces.
The effective method set of an interface is the union of its own declared
methods and all methods inherited from its superinterfaces, with declared
methods taking precedence.

## 9.4 Abstract Method Declarations

Every method declaration in the body of an interface is implicitly abstract
and public. Interface methods carry no implementation.
