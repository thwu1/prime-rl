@counter = global i64 0

define void @increment() {
  %val = load i64, i64* @counter
  %new_val = add i64 %val, 1
  store i64 %new_val, i64* @counter
  ret void
}

define i64 @_program(i64 %argc, i8** %argv) {
  call void @increment()
  call void @increment()
  call void @increment()
  call void @increment()
  call void @increment()
  %val = load i64, i64* @counter
  ret i64 %val
}
