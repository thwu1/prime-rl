; test07_loop: while loop computing sum 1..10 = 55
define i64 @program() {
entry:
  %sum_ptr = alloca i64
  %i_ptr = alloca i64
  store i64 0, i64* %sum_ptr
  store i64 1, i64* %i_ptr
  br label %loop

loop:
  %i = load i64, i64* %i_ptr
  %cmp = icmp sle i64 %i, 10
  br i1 %cmp, label %body, label %done

body:
  %sum = load i64, i64* %sum_ptr
  %new_sum = add i64 %sum, %i
  store i64 %new_sum, i64* %sum_ptr
  %new_i = add i64 %i, 1
  store i64 %new_i, i64* %i_ptr
  br label %loop

done:
  %result = load i64, i64* %sum_ptr
  ret i64 %result
}
