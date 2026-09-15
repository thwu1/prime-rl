# Cool Type Checking Rules

## Built-in Classes

### Object (root of hierarchy, parent = None)
- `abort() : Object`
- `type_name() : String`
- `copy() : SELF_TYPE`

### IO (parent = Object)
- `out_string(x : String) : SELF_TYPE`
- `out_int(x : Int) : SELF_TYPE`
- `in_string() : String`
- `in_int() : Int`

### Int (parent = Object) — no user-accessible methods
### Bool (parent = Object) — no user-accessible methods
### String (parent = Object)
- `length() : Int`
- `concat(s : String) : String`
- `substr(i : Int, l : Int) : String`

## Hierarchy Rules

- Every class without an explicit `inherits` clause inherits from Object.
- It is an error to redefine Object, IO, Int, String, Bool, or SELF_TYPE.
- It is an error to inherit from Int, String, or Bool.
- The inheritance graph must be acyclic.
- Every program must have a class Main with a method `main()` taking no arguments.

## Attribute Rules

- Inherited attributes cannot be redefined in subclasses.
- Attribute initializer type must conform to the declared type.

## Method Override Rules

- If class C overrides method f inherited from P, then:
  - Same number of formal parameters
  - Each formal parameter has exactly the same type
  - Same return type

## SELF_TYPE Rules

- SELF_TYPE may appear as: return type of a method, declared type of an attribute, declared type in a let binding, or in `new SELF_TYPE`.
- SELF_TYPE may NOT appear as: a formal parameter type, a case branch type, or a parent class.
- `self` has static type SELF_TYPE.

## Conformance (subtyping)

- A <= A (reflexive)
- If C inherits P, then C <= P
- Transitive: if A <= C and C <= P, then A <= P
- SELF_TYPE_C <= SELF_TYPE_C
- SELF_TYPE_C <= P if C <= P
- Nothing conforms to SELF_TYPE except SELF_TYPE itself (in the same class context)

## Least Upper Bound (LUB)

- LUB(A, B) = the least (most specific) type C such that A <= C and B <= C
- LUB(SELF_TYPE_D, A) = LUB(D, A)
- Computed by walking ancestors of both types and finding the first common ancestor.

## Expression Type Rules

### Constants
- Integer literal: Int
- String literal: String
- Boolean literal: Bool

### self
- Static type: SELF_TYPE

### Identifier
- Static type: looked up from the current scope (let bindings, formals, attributes)

### Assignment (id <- expr)
- Cannot assign to `self`.
- expr type must conform to the declared type of id.
- Static type of assignment: type of expr.

### Dispatch (e.f(args))
- Let T = static type of e. Let T' = T resolved (if T is SELF_TYPE, resolve to current class).
- Method f must exist in T'.
- Argument types must conform to formal parameter types.
- If f has return type SELF_TYPE, the dispatch has static type T (the original, possibly SELF_TYPE).
- If f has a concrete return type R, the dispatch has static type R.

### Static Dispatch (e@T.f(args))
- Static type of e must conform to T.
- Method f is looked up in class T (not in e's type).
- Return type rules same as regular dispatch.

### Self Dispatch (f(args))
- Shorthand for self.f(args).
- Method f must exist in the current class.
- If f returns SELF_TYPE, the dispatch type is SELF_TYPE.

### Conditional (if pred then e1 else e2 fi)
- pred must have type Bool.
- Static type: LUB(type(e1), type(e2)).

### Loop (while pred loop body pool)
- pred must have type Bool.
- Static type: Object.

### Block ({ e1; e2; ... en; })
- Static type: type of the last expression en.

### Let (let id : T [<- init] in body)
- If init is present, its type must conform to T.
- id is NOT in scope during init evaluation.
- id IS in scope during body evaluation with declared type T.
- Static type: type of body.

### Case (case e of id1:T1 => e1; ... esac)
- Each branch introduces id with type T in a new scope.
- Duplicate branch types are an error.
- Static type: LUB of all branch body types.

### New (new T)
- Static type: T (which may be SELF_TYPE).

### Isvoid (isvoid e)
- Static type: Bool.

### Arithmetic (+, -, *, /)
- Both operands must have type Int.
- Static type: Int.

### Integer Negation (~e)
- Operand must have type Int.
- Static type: Int.

### Comparisons (<, <=)
- Both operands must have type Int.
- Static type: Bool.

### Equality (=)
- If either operand is Int, String, or Bool, the other must be the same type.
- Otherwise, any types are permitted.
- Static type: Bool.

### Boolean Not (not e)
- Operand must have type Bool.
- Static type: Bool.
