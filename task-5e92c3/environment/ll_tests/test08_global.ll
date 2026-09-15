; test08_global: global variable read and write
@gval = global i64 100

define i64 @program() {
entry:
  %v = load i64, i64* @gval
  %r = add i64 %v, 55
  store i64 %r, i64* @gval
  %result = load i64, i64* @gval
  ret i64 %result
}
