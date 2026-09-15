(module
  (func (export "classify") (param i32) (result i32)
    block
      block
        block
          local.get 0
          i32.const 0
          i32.lt_s
          br_if 0
          local.get 0
          i32.const 10
          i32.gt_s
          br_if 1
          br 2
        end
        i32.const -1
        return
      end
      i32.const 1
      return
    end
    i32.const 0))
