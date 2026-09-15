; test03_chain: chained arithmetic operations
define i64 @program() {
  %a = add i64 10, 20
  %b = mul i64 %a, 3
  %c = sub i64 %b, 41
  ret i64 %c
}
