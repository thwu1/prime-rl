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
  %combined = or i32 %shl, %shr
  %xor1 = xor i32 %seed, %combined
  %result = add i32 %xor1, -1640531527
  ret i32 %result
}

; Function Attrs: nounwind uwtable
define dso_local i32 @rotate_left(i32 noundef %x, i32 noundef %n) #0 {
entry:
  %masked = and i32 %n, 31
  %shl = shl i32 %x, %masked
  %sub = sub i32 32, %masked
  %shr = lshr i32 %x, %sub
  %or = or i32 %shl, %shr
  ret i32 %or
}

; Function Attrs: nounwind uwtable
define dso_local void @memset_pattern(ptr noundef %dst, i32 noundef %val, i64 noundef %n) #0 {
entry:
  %cmp = icmp eq i64 %n, 0
  br i1 %cmp, label %exit, label %do.memset

do.memset:                                        ; preds = %entry
  %nbytes = shl i64 %n, 2
  %trunc = trunc i32 %val to i8
  call void @llvm.memset.p0.i64(ptr align 4 %dst, i8 %trunc, i64 %nbytes, i1 false)
  br label %exit

exit:                                             ; preds = %do.memset, %entry
  ret void
}

declare void @llvm.memset.p0.i64(ptr, i8, i64, i1)
declare i32 @printf(ptr, ...)

attributes #0 = { nounwind uwtable }

!llvm.module.flags = !{!0}
!0 = !{i32 1, !"wchar_size", i32 4}
