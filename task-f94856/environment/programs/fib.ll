define i64 @fib(i64 %n) {
entry:
  %cmp1 = icmp sle i64 %n, 0
  br i1 %cmp1, label %ret_zero, label %check_one
ret_zero:
  ret i64 0
check_one:
  %cmp2 = icmp eq i64 %n, 1
  br i1 %cmp2, label %ret_one, label %compute
ret_one:
  ret i64 1
compute:
  %n1 = sub i64 %n, 1
  %n2 = sub i64 %n, 2
  %f1 = call i64 @fib(i64 %n1)
  %f2 = call i64 @fib(i64 %n2)
  %result = add i64 %f1, %f2
  ret i64 %result
}

define i64 @_program(i64 %argc, i8** %argv) {
  %r = call i64 @fib(i64 15)
  ret i64 %r
}
