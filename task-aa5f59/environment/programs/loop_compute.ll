; ModuleID = 'loop_compute'
source_filename = "loop_compute.ll"
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-i128:128-f80:128-n8:16:32:64-S128"
target triple = "x86_64-unknown-linux-gnu"

define i64 @accumulate(ptr %data, i64 %len, i64 %multiplier, i64 %addend) {
entry:
  %cmp0 = icmp sgt i64 %len, 0
  br i1 %cmp0, label %loop, label %exit

loop:
  %i = phi i64 [0, %entry], [%i.next, %loop]
  %acc = phi i64 [0, %entry], [%acc.next, %loop]
  %factor = mul i64 %multiplier, %addend
  %offset = add i64 %factor, 7
  %scale = mul i64 %offset, %multiplier
  %dead1 = mul i64 %multiplier, 88001
  %dead2 = add i64 %dead1, 88002
  %dead3 = mul i64 %dead2, 88003
  %dead4 = add i64 %dead3, 88004
  %ptr = getelementptr i64, ptr %data, i64 %i
  %val = load i64, ptr %ptr, align 8
  %weighted = mul i64 %val, %scale
  %acc.next = add i64 %acc, %weighted
  %i.next = add i64 %i, 1
  %cmp = icmp slt i64 %i.next, %len
  br i1 %cmp, label %loop, label %exit

exit:
  %result = phi i64 [0, %entry], [%acc.next, %loop]
  ret i64 %result
}
