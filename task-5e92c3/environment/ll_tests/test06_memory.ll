; test06_memory: alloca, store, load
define i64 @program() {
entry:
  %x = alloca i64
  store i64 42, i64* %x
  %v = load i64, i64* %x
  ret i64 %v
}
