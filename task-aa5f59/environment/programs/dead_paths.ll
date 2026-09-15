; ModuleID = 'dead_paths'
source_filename = "dead_paths.ll"
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-i128:128-f80:128-n8:16:32:64-S128"
target triple = "x86_64-unknown-linux-gnu"

define i32 @process(i32 %n, i32 %mode) {
entry:
  %cmp = icmp eq i32 %mode, 0
  br i1 %cmp, label %path_a, label %path_b

path_a:
  %a1 = mul i32 %n, %n
  %a2 = add i32 %a1, %n
  %dead_a1 = add i32 %n, 77001
  %dead_a2 = mul i32 %dead_a1, 77002
  %dead_a3 = add i32 %dead_a2, 77003
  %dead_a4 = mul i32 %dead_a3, 77004
  br label %merge

path_b:
  %b1 = sub i32 %n, 1
  %b2 = mul i32 %b1, %n
  %dead_b1 = add i32 %n, 77005
  %dead_b2 = mul i32 %dead_b1, 77006
  %dead_b3 = sub i32 %dead_b2, 77007
  br label %merge

merge:
  %result = phi i32 [%a2, %path_a], [%b2, %path_b]
  %dead_c1 = add i32 %result, 77008
  %dead_c2 = mul i32 %dead_c1, 77009
  ret i32 %result
}
