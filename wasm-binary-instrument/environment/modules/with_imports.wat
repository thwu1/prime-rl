(module
  (import "env" "print" (func $print (param i32)))
  (import "env" "base" (global $base i32))
  (global $state (mut i32) (i32.const 0))
  (func (export "init") (param i32)
    local.get 0
    global.get $base
    i32.add
    global.set $state
    global.get $state
    call $print)
  (func (export "get_state") (result i32)
    global.get $state))
