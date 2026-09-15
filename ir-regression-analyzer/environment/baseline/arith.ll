; ModuleID = 'arith.c'
source_filename = "arith.c"
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-i128:128-f80:128-n8:16:32:64-S128"
target triple = "x86_64-pc-linux-gnu"

; Function Attrs: noinline nounwind uwtable
define dso_local i32 @fold_constants(i32 noundef %x) #0 {
entry:
  %a = add i32 %x, 0
  %b = mul i32 %a, 1
  %c = add i32 %b, 5
  %d = sub i32 %c, 3
  %e = add i32 %d, 8
  ret i32 %e
}

; Function Attrs: noinline nounwind uwtable
define dso_local i32 @strength_reduce(i32 noundef %x) #0 {
entry:
  %a = mul i32 %x, 8
  %b = add i32 %a, %x
  ret i32 %b
}

attributes #0 = { noinline nounwind uwtable }

!llvm.module.flags = !{!0, !1}
!llvm.ident = !{!2}

!0 = !{i32 1, !"wchar_size", i32 4}
!1 = !{i32 7, !"uwtable", i32 2}
!2 = !{!"clang version 19.0.0"}
