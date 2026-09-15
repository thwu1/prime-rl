; ModuleID = 'alloca_heavy'
source_filename = "alloca_heavy.ll"
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-i128:128-f80:128-n8:16:32:64-S128"
target triple = "x86_64-unknown-linux-gnu"

define i64 @compute(i64 %a, i64 %b, i64 %c) {
entry:
  %x = alloca i64, align 8
  %y = alloca i64, align 8
  %z = alloca i64, align 8
  %w = alloca i64, align 8
  store i64 %a, ptr %x, align 8
  store i64 %b, ptr %y, align 8
  store i64 %c, ptr %z, align 8
  store i64 0, ptr %w, align 8
  %v0 = load i64, ptr %x, align 8
  %v1 = load i64, ptr %y, align 8
  %sum1 = add i64 %v0, %v1
  store i64 %sum1, ptr %w, align 8
  %v2 = load i64, ptr %x, align 8
  %v3 = load i64, ptr %z, align 8
  %prod1 = mul i64 %v2, %v3
  %v4 = load i64, ptr %w, align 8
  %sum2 = add i64 %v4, %prod1
  store i64 %sum2, ptr %w, align 8
  %v5 = load i64, ptr %y, align 8
  %v6 = load i64, ptr %z, align 8
  %prod2 = mul i64 %v5, %v6
  %v7 = load i64, ptr %w, align 8
  %sum3 = add i64 %v7, %prod2
  ret i64 %sum3
}
