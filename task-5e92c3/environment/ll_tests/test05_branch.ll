; test05_branch: conditional branching
define i64 @max(i64 %a, i64 %b) {
entry:
  %cmp = icmp sgt i64 %a, %b
  br i1 %cmp, label %then, label %else

then:
  ret i64 %a

else:
  ret i64 %b
}

define i64 @program() {
entry:
  %r = call i64 @max(i64 17, i64 42)
  ret i64 %r
}
