; ModuleID = 'crypto.c'
source_filename = "crypto.c"
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-i128:128-f80:128-n8:16:32:64-S128"
target triple = "x86_64-pc-linux-gnu"

@.str = private unnamed_addr constant [12 x i8] c"hash_error\0A\00", align 1

; Function Attrs: nounwind uwtable
define dso_local i32 @hash_combine(i32 noundef %seed, i32 noundef %value) #0 {
entry:
  %shl = shl i32 %value, 6
  %shr = lshr i32 %value, 2
  %xor1 = xor i32 %seed, %shl
  %add1 = add i32 %xor1, -1640531527
  %xor2 = xor i32 %add1, %shr
  %add2 = add i32 %xor2, %seed
  ret i32 %add2
}

; Function Attrs: nounwind uwtable
define dso_local i32 @rotate_left(i32 noundef %x, i32 noundef %n) #0 {
entry:
  %shl = shl i32 %x, %n
  %sub = sub i32 32, %n
  %shr = lshr i32 %x, %sub
  %or = or i32 %shl, %shr
  ret i32 %or
}

; Function Attrs: nounwind uwtable
define dso_local void @memset_pattern(ptr noundef %dst, i32 noundef %val, i64 noundef %n) #0 {
entry:
  %cmp = icmp eq i64 %n, 0
  br i1 %cmp, label %exit, label %loop

loop:                                             ; preds = %entry, %loop
  %i = phi i64 [ 0, %entry ], [ %i.next, %loop ]
  %ptr = getelementptr inbounds i32, ptr %dst, i64 %i
  store i32 %val, ptr %ptr, align 4
  %i.next = add nuw i64 %i, 1
  %done = icmp eq i64 %i.next, %n
  br i1 %done, label %exit, label %loop

exit:                                             ; preds = %loop, %entry
  ret void
}

declare i32 @printf(ptr, ...)

attributes #0 = { nounwind uwtable }

!llvm.module.flags = !{!0}
!0 = !{i32 1, !"wchar_size", i32 4}
