Implement a complete Hindley-Milner type inference system for Mini-ML, a small functional language. The system must parse source code, infer principal types, and expose a CLI.

## Starting State

`/app/` contains provided AST definitions (`ml_ast.py`), type representations (`ml_types.py`), and stubs for unification (`ml_unify.py`), inference (`ml_infer.py`), parser (`ml_parser.py`), CLI (`ml_cli.py`), and an empty Lark grammar (`grammar.lark`). A `Makefile` orchestrates builds. Do not modify `ml_ast.py` or `ml_types.py`.

## Language

```
e ::= n | true | false | ()
    | x
    | e + e | e - e | e * e | e / e
    | e == e | e < e | e > e | e <= e | e >= e
    | e && e | e || e
    | -e | not e
    | if e then e else e
    | fun x -> e
    | e e                              (left-assoc application)
    | let x = e in e | let rec f = e in e
    | (e, e) | fst e | snd e
    | [] | e :: e                      (right-assoc cons)
    | match e with [] -> e | x :: x -> e
```

Types: `int`, `bool`, `unit`, type variables, `t -> t`, `t * t`, `t list`.

Arithmetic/comparison operators require `int` operands. Logical operators require `bool`. `let`/`let rec` bindings are polymorphic; `fun` bindings are monomorphic. Unification must include the occurs check.

## Requirements

- Parser uses Lark with `/app/grammar.lark` (Earley parser, start rule `start`).
- `python3 /app/ml_cli.py <file>` reads a source file, infers its type, prints the type to stdout, exits 0 on success or non-zero on type error.
- `make test` passes in `/app/`.