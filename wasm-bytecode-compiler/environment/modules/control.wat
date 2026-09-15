(module
  (func (export "abs") (param i32) (result i32)
    local.get 0
    i32.const 0
    i32.lt_s
    if (result i32)
      i32.const 0
      local.get 0
      i32.sub
    else
      local.get 0
    end)

  (func (export "sum_to_n") (param i32) (result i32)
    (local i32)
    i32.const 0
    local.set 1
    block
      loop
        local.get 0
        i32.eqz
        br_if 1
        local.get 1
        local.get 0
        i32.add
        local.set 1
        local.get 0
        i32.const 1
        i32.sub
        local.set 0
        br 0
      end
    end
    local.get 1)

  (func (export "fib") (param i32) (result i32)
    (local i32 i32 i32)
    i32.const 0
    local.set 1
    i32.const 1
    local.set 2
    block
      loop
        local.get 0
        i32.eqz
        br_if 1
        local.get 2
        local.set 3
        local.get 1
        local.get 2
        i32.add
        local.set 2
        local.get 3
        local.set 1
        local.get 0
        i32.const 1
        i32.sub
        local.set 0
        br 0
      end
    end
    local.get 1))
