; test14_cmp_ops: various comparison operators with zext
define i64 @program() {
entry:
  %a = icmp eq i64 5, 5
  %b = icmp ne i64 5, 3
  %c = icmp slt i64 3, 5
  %d = icmp sge i64 5, 5
  %ae = zext i1 %a to i64
  %be = zext i1 %b to i64
  %ce = zext i1 %c to i64
  %de = zext i1 %d to i64
  %s1 = add i64 %ae, %be
  %s2 = add i64 %s1, %ce
  %s3 = add i64 %s2, %de
  ret i64 %s3
}
