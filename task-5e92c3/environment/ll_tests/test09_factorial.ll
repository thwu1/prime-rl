; test09_factorial: recursive function, 5! = 120
define i64 @factorial(i64 %n) {
entry:
  %cmp = icmp sle i64 %n, 1
  br i1 %cmp, label %base, label %rec

base:
  ret i64 1

rec:
  %n1 = sub i64 %n, 1
  %r = call i64 @factorial(i64 %n1)
  %result = mul i64 %n, %r
  ret i64 %result
}

define i64 @program() {
entry:
  %r = call i64 @factorial(i64 5)
  ret i64 %r
}
