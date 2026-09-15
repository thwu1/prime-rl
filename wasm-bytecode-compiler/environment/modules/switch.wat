(module
  (func (export "switch_val") (param i32) (result i32)
    block
      block
        block
          block
            local.get 0
            br_table 0 1 2 3
          end
          i32.const 10
          return
        end
        i32.const 20
        return
      end
      i32.const 30
      return
    end
    i32.const 40))
