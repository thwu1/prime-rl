(module
  (func $double (param i32) (result i32)
    local.get 0
    i32.const 2
    i32.mul)
  (func (export "quad") (param i32) (result i32)
    local.get 0
    call $double
    call $double)
  (export "double" (func $double)))
