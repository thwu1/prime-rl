; test04_call: function definition and call
define i64 @double(i64 %x) {
  %r = add i64 %x, %x
  ret i64 %r
}

define i64 @program() {
  %r = call i64 @double(i64 21)
  ret i64 %r
}
