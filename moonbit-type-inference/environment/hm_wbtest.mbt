//
// Whitebox tests for type inference engine.
// The function `infer_type(expr : String) -> String` must be implemented
// in the same package.

///|
test "int_literal" {
  inspect!(infer_type("42"), content="Int")
}

///|
test "bool_literal" {
  inspect!(infer_type("true"), content="Bool")
}

///|
test "identity_function" {
  inspect!(infer_type("(fn x x)"), content="a -> a")
}

///|
test "const_function" {
  inspect!(infer_type("(fn x (fn y x))"), content="a -> b -> a")
}

///|
test "apply_identity" {
  inspect!(infer_type("((fn x x) 42)"), content="Int")
}

///|
test "let_monomorphic" {
  inspect!(infer_type("(let x 42 x)"), content="Int")
}

///|
test "let_polymorphic_use" {
  inspect!(infer_type("(let id (fn x x) (id 42))"), content="Int")
}

///|
test "let_polymorphic_return" {
  inspect!(infer_type("(let id (fn x x) id)"), content="a -> a")
}

///|
test "arithmetic" {
  inspect!(infer_type("(+ 1 2)"), content="Int")
}

///|
test "comparison" {
  inspect!(infer_type("(== 1 2)"), content="Bool")
}

///|
test "if_expression" {
  inspect!(infer_type("(if true 1 2)"), content="Int")
}

///|
test "higher_order" {
  inspect!(infer_type("(fn f (fn x (f (f x))))"), content="(a -> a) -> a -> a")
}

///|
test "letrec_factorial" {
  inspect!(infer_type("(letrec f (fn n (if (== n 0) 1 (* n (f (- n 1))))) (f 5))"), content="Int")
}

///|
test "occurs_check_fails" {
  inspect!(infer_type("(fn x (x x))"), content="TYPE ERROR")
}

///|
test "type_mismatch" {
  inspect!(infer_type("(+ true 1)"), content="TYPE ERROR")
}
