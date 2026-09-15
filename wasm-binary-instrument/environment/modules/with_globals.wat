(module
  (global $counter (mut i32) (i32.const 0))
  (global $limit i32 (i32.const 100))
  (func (export "get_counter") (result i32)
    global.get $counter)
  (func (export "increment") (result i32)
    global.get $counter
    i32.const 1
    i32.add
    global.set $counter
    global.get $counter))
