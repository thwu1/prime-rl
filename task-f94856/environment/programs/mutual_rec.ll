declare void @_print_int(i64)

define i1 @is_even(i64 %n) {
entry:
  %cmp = icmp eq i64 %n, 0
  br i1 %cmp, label %base, label %recurse
base:
  ret i1 1
recurse:
  %n1 = sub i64 %n, 1
  %result = call i1 @is_odd(i64 %n1)
  ret i1 %result
}

define i1 @is_odd(i64 %n) {
entry:
  %cmp = icmp eq i64 %n, 0
  br i1 %cmp, label %base, label %recurse
base:
  ret i1 0
recurse:
  %n1 = sub i64 %n, 1
  %result = call i1 @is_even(i64 %n1)
  ret i1 %result
}

define i64 @_program(i64 %argc, i8** %argv) {
  %r1 = call i1 @is_even(i64 42)
  %e1 = zext i1 %r1 to i64
  call void @_print_int(i64 %e1)
  %r2 = call i1 @is_odd(i64 42)
  %e2 = zext i1 %r2 to i64
  call void @_print_int(i64 %e2)
  %r3 = call i1 @is_even(i64 17)
  %e3 = zext i1 %r3 to i64
  call void @_print_int(i64 %e3)
  %r4 = call i1 @is_odd(i64 17)
  %e4 = zext i1 %r4 to i64
  call void @_print_int(i64 %e4)
  ret i64 0
}
