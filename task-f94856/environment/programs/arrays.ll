declare i64* @_alloc_array(i64)

define i64 @_program(i64 %argc, i8** %argv) {
entry:
  %arr = call i64* @_alloc_array(i64 5)
  %p0 = getelementptr i64, i64* %arr, i64 0
  store i64 10, i64* %p0
  %p1 = getelementptr i64, i64* %arr, i64 1
  store i64 20, i64* %p1
  %p2 = getelementptr i64, i64* %arr, i64 2
  store i64 30, i64* %p2
  %p3 = getelementptr i64, i64* %arr, i64 3
  store i64 40, i64* %p3
  %p4 = getelementptr i64, i64* %arr, i64 4
  store i64 50, i64* %p4
  %v0 = load i64, i64* %p0
  %v1 = load i64, i64* %p1
  %s1 = add i64 %v0, %v1
  %v2 = load i64, i64* %p2
  %s2 = add i64 %s1, %v2
  %v3 = load i64, i64* %p3
  %s3 = add i64 %s2, %v3
  %v4 = load i64, i64* %p4
  %s4 = add i64 %s3, %v4
  ret i64 %s4
}
