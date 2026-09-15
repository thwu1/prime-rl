(module
  (func $double (param i32) (result i32)
    local.get 0
    local.get 0
    i32.add)
  (func (export "quadruple") (param i32) (result i32)
    local.get 0
    call 0
    call 0)
  (func (export "sum_doubles") (param i32 i32) (result i32)
    local.get 0
    call 0
    local.get 1
    call 0
    i32.add))
