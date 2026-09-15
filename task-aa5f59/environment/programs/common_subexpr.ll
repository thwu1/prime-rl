; ModuleID = 'common_subexpr'
source_filename = "common_subexpr.ll"
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-i128:128-f80:128-n8:16:32:64-S128"
target triple = "x86_64-unknown-linux-gnu"

define i64 @redundant(i64 %a, i64 %b, i64 %c, i64 %d) {
entry:
  %sum1 = add i64 %a, %b
  %prod1 = mul i64 %sum1, %c
  %sum2 = add i64 %a, %b
  %prod2 = mul i64 %sum2, %d
  %sum3 = add i64 %a, %b
  %prod3 = mul i64 %sum3, %sum3
  %x = mul i64 %prod1, %c
  %y = mul i64 %prod1, %c
  %r1 = add i64 %prod1, %prod2
  %r2 = add i64 %r1, %prod3
  %r3 = add i64 %r2, %x
  %r4 = add i64 %r3, %y
  ret i64 %r4
}
