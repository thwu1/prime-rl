# Cool AST Format

The Cool parser (`cool_parser.py`) produces ASTs as nested Python dicts. Every node has a `"kind"` field identifying its type. Expression nodes also have a `"line"` field.

## Program

```
{"kind": "program", "classes": [<class>, ...]}
```

## Class

```
{"kind": "class", "name": str, "parent": str | None, "features": [<feature>, ...], "line": int}
```

`parent` is `None` if no `inherits` clause (defaults to Object).

## Features

### Method
```
{"kind": "method", "name": str, "formals": [<formal>, ...], "return_type": str, "body": <expr>, "line": int}
```

### Attribute
```
{"kind": "attr", "name": str, "type_decl": str, "init": <expr> | None, "line": int}
```

### Formal parameter
```
{"name": str, "type": str}
```

## Expressions

### Constants
```
{"kind": "int_const", "value": int, "line": int}
{"kind": "string_const", "value": str, "line": int}
{"kind": "bool_const", "value": bool, "line": int}
```

### Identifiers
```
{"kind": "identifier", "name": str, "line": int}
{"kind": "self", "line": int}
```

### Assignment
```
{"kind": "assign", "name": str, "expr": <expr>, "line": int}
```

### Dispatch
```
{"kind": "dispatch", "object": <expr>, "method": str, "args": [<expr>, ...], "line": int}
{"kind": "static_dispatch", "object": <expr>, "type_name": str, "method": str, "args": [<expr>, ...], "line": int}
{"kind": "self_dispatch", "method": str, "args": [<expr>, ...], "line": int}
```

`self_dispatch` is shorthand for dispatching on `self` (e.g., `foo(x)` means `self.foo(x)`).

### Control flow
```
{"kind": "cond", "predicate": <expr>, "then_expr": <expr>, "else_expr": <expr>, "line": int}
{"kind": "loop", "predicate": <expr>, "body": <expr>, "line": int}
{"kind": "block", "body": [<expr>, ...], "line": int}
```

### Let
```
{"kind": "let", "binding": {"name": str, "type_decl": str, "init": <expr> | None}, "body": <expr>, "line": int}
```

Multi-binding `let` is desugared into nested single-binding `let` nodes.

### Case
```
{"kind": "case", "expr": <expr>, "branches": [{"name": str, "type_decl": str, "body": <expr>}, ...], "line": int}
```

### Object creation
```
{"kind": "new", "type_name": str, "line": int}
```

### Isvoid
```
{"kind": "isvoid", "expr": <expr>, "line": int}
```

### Arithmetic
```
{"kind": "plus"|"sub"|"mul"|"div", "left": <expr>, "right": <expr>, "line": int}
{"kind": "neg", "expr": <expr>, "line": int}
```

### Comparison
```
{"kind": "lt"|"le"|"eq", "left": <expr>, "right": <expr>, "line": int}
```

### Boolean
```
{"kind": "not", "expr": <expr>, "line": int}
```
