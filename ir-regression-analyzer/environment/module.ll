; ModuleID = 'benchmark'
source_filename = "benchmark.c"
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-i128:128-f80:128-n8:16:32:64-S128"
target triple = "x86_64-unknown-linux-gnu"

; Function Attrs: nounwind uwtable
define dso_local i32 @fold_arith(i32 noundef %x, i32 noundef %y) #0 {
entry:
  %a = add i32 %x, 0
  %b = mul i32 %a, 1
  %c = add i32 %b, %y
  %d = sub i32 %c, 0
  ret i32 %d
}

; Function Attrs: nounwind uwtable
define dso_local i32 @sum_fixed(ptr noundef %arr) #0 {
entry:
  br label %for.body

for.body:                                         ; preds = %entry, %for.body
  %i = phi i32 [ 0, %entry ], [ %i.next, %for.body ]
  %sum = phi i32 [ 0, %entry ], [ %sum.next, %for.body ]
  %arrayidx = getelementptr inbounds i32, ptr %arr, i32 %i
  %val = load i32, ptr %arrayidx, align 4
  %sum.next = add nsw i32 %sum, %val
  %i.next = add nuw nsw i32 %i, 1
  %exitcond = icmp ne i32 %i.next, 4
  br i1 %exitcond, label %for.body, label %for.end

for.end:                                          ; preds = %for.body
  ret i32 %sum.next
}

; Function Attrs: nounwind uwtable
define dso_local i64 @dot_fixed(ptr noundef %a, ptr noundef %b) #0 {
entry:
  br label %for.body

for.body:                                         ; preds = %entry, %for.body
  %i = phi i64 [ 0, %entry ], [ %i.next, %for.body ]
  %acc = phi i64 [ 0, %entry ], [ %acc.next, %for.body ]
  %arrayidx.a = getelementptr inbounds i64, ptr %a, i64 %i
  %arrayidx.b = getelementptr inbounds i64, ptr %b, i64 %i
  %va = load i64, ptr %arrayidx.a, align 8
  %vb = load i64, ptr %arrayidx.b, align 8
  %prod = mul nsw i64 %va, %vb
  %acc.next = add nsw i64 %acc, %prod
  %i.next = add nuw nsw i64 %i, 1
  %exitcond = icmp ne i64 %i.next, 8
  br i1 %exitcond, label %for.body, label %for.end

for.end:                                          ; preds = %for.body
  ret i64 %acc.next
}

; Function Attrs: nounwind uwtable
define dso_local i32 @with_dead_code(i32 noundef %x) #0 {
entry:
  %live = add i32 %x, 1
  %dead1 = mul i32 %x, 3
  %dead2 = add i32 %dead1, 42
  %dead3 = mul i32 %dead2, %dead2
  %dead4 = xor i32 %dead3, %dead1
  ret i32 %live
}

; Function Attrs: nounwind uwtable
define dso_local i32 @redundant_loads(ptr noundef %p, i32 noundef %cond) #0 {
entry:
  %v1 = load i32, ptr %p, align 4
  %tobool = icmp sgt i32 %cond, 0
  br i1 %tobool, label %if.then, label %if.else

if.then:                                          ; preds = %entry
  %v2 = load i32, ptr %p, align 4
  %add = add nsw i32 %v1, %v2
  br label %if.end

if.else:                                          ; preds = %entry
  %v3 = load i32, ptr %p, align 4
  %sub = sub nsw i32 %v3, 1
  br label %if.end

if.end:                                           ; preds = %if.then, %if.else
  %result = phi i32 [ %add, %if.then ], [ %sub, %if.else ]
  ret i32 %result
}

attributes #0 = { nounwind uwtable }

!llvm.module.flags = !{!0, !1}
!llvm.ident = !{!2}

!0 = !{i32 1, !"wchar_size", i32 4}
!1 = !{i32 7, !"uwtable", i32 2}
!2 = !{!"clang version 18.1.0"}
