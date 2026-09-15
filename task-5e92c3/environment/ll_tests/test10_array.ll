; test10_array: dynamic array allocation and GEP
declare i64* @ll_alloc_array(i64)

define i64 @program() {
entry:
  %arr = call i64* @ll_alloc_array(i64 5)

  %p0 = getelementptr i64, i64* %arr, i64 0
  store i64 10, i64* %p0

  %p1 = getelementptr i64, i64* %arr, i64 1
  store i64 20, i64* %p1

  %p2 = getelementptr i64, i64* %arr, i64 2
  store i64 30, i64* %p2

  %v0 = load i64, i64* %p0
  %v1 = load i64, i64* %p1
  %v2 = load i64, i64* %p2

  %s1 = add i64 %v0, %v1
  %s2 = add i64 %s1, %v2
  ret i64 %s2
}
