; test11_bitwise: and, or, xor, shl
define i64 @program() {
entry:
  %a = and i64 255, 170
  %b = or i64 %a, 85
  %c = xor i64 %b, 128
  %d = shl i64 1, 5
  %e = add i64 %c, %d
  ret i64 %e
}
