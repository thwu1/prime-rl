define i64 @abs(i64 %x) {
entry:
  %cmp = icmp slt i64 %x, 0
  br i1 %cmp, label %neg, label %pos
neg:
  %negx = sub i64 0, %x
  br label %done
pos:
  br label %done
done:
  %result = phi i64 [%negx, %neg], [%x, %pos]
  ret i64 %result
}

define i64 @_program(i64 %argc, i8** %argv) {
  %r1 = call i64 @abs(i64 -37)
  %r2 = call i64 @abs(i64 5)
  %r3 = add i64 %r1, %r2
  ret i64 %r3
}
