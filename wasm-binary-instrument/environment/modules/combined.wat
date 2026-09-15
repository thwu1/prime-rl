(module
  (import "env" "log" (func (param i32)))
  (import "env" "base_val" (global i32))
  (global (mut i32) (i32.const 0))
  (func (param i32 i32) (result i32)
    local.get 0
    local.get 1
    i32.add)
  (func (export "run") (param i32) (result i32)
    local.get 0
    i32.const 10
    call 1)
  (export "adder" (func 1))
  (export "my_counter" (global 1)))
