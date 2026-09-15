(module
  (func (param i32) (result i32)
    local.get 0
    i32.const 2
    i32.mul)
  (func (export "compute") (param i32) (result i32)
    local.get 0
    call 0)
  (export "helper" (func 0)))
