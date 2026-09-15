declare void @_print_int(i64)

define i64 @factorial(i64 %n) {
entry:
  br label %loop
loop:
  %i = phi i64 [1, %entry], [%next_i, %loop]
  %acc = phi i64 [1, %entry], [%next_acc, %loop]
  %next_acc = mul i64 %acc, %i
  %next_i = add i64 %i, 1
  %cmp = icmp sle i64 %next_i, %n
  br i1 %cmp, label %loop, label %exit
exit:
  ret i64 %next_acc
}

define i64 @_program(i64 %argc, i8** %argv) {
  %r1 = call i64 @factorial(i64 5)
  call void @_print_int(i64 %r1)
  %r2 = call i64 @factorial(i64 10)
  call void @_print_int(i64 %r2)
  ret i64 0
}
