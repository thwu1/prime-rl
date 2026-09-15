; test15_fib_print: fibonacci with external print call
declare void @ll_print_int(i64)

define i64 @fib(i64 %n) {
entry:
  %cmp = icmp sle i64 %n, 1
  br i1 %cmp, label %base, label %rec

base:
  ret i64 %n

rec:
  %n1 = sub i64 %n, 1
  %n2 = sub i64 %n, 2
  %f1 = call i64 @fib(i64 %n1)
  %f2 = call i64 @fib(i64 %n2)
  %result = add i64 %f1, %f2
  ret i64 %result
}

define i64 @program() {
entry:
  %r = call i64 @fib(i64 10)
  call void @ll_print_int(i64 %r)
  ret i64 %r
}
