; ModuleID = 'loop.c'
source_filename = "loop.c"
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-i128:128-f80:128-n8:16:32:64-S128"
target triple = "x86_64-pc-linux-gnu"

; Function Attrs: nounwind uwtable
define dso_local i64 @sum_array(ptr noundef %arr, i64 noundef %n) #0 {
entry:
  %cmp = icmp sgt i64 %n, 0
  br i1 %cmp, label %for.body.preheader, label %for.end

for.body.preheader:                               ; preds = %entry
  br label %for.body

for.body:                                         ; preds = %for.body.preheader, %for.body
  %i = phi i64 [ 0, %for.body.preheader ], [ %inc, %for.body ]
  %sum = phi i64 [ 0, %for.body.preheader ], [ %add, %for.body ]
  %arrayidx = getelementptr inbounds i64, ptr %arr, i64 %i
  %val = load i64, ptr %arrayidx, align 8, !tbaa !3
  %add = add nsw i64 %sum, %val
  %inc = add nuw nsw i64 %i, 1
  %exitcond = icmp eq i64 %inc, %n
  br i1 %exitcond, label %for.end, label %for.body

for.end:                                          ; preds = %for.body, %entry
  %result = phi i64 [ 0, %entry ], [ %add, %for.body ]
  ret i64 %result
}

; Function Attrs: nounwind uwtable
define dso_local i64 @dot_product(ptr noundef %a, ptr noundef %b, i64 noundef %n) #0 {
entry:
  %cmp = icmp sgt i64 %n, 0
  br i1 %cmp, label %for.body, label %for.end

for.body:                                         ; preds = %entry, %for.body
  %i = phi i64 [ 0, %entry ], [ %inc, %for.body ]
  %acc = phi i64 [ 0, %entry ], [ %add, %for.body ]
  %arrayidx.a = getelementptr inbounds i64, ptr %a, i64 %i
  %arrayidx.b = getelementptr inbounds i64, ptr %b, i64 %i
  %va = load i64, ptr %arrayidx.a, align 8
  %vb = load i64, ptr %arrayidx.b, align 8
  %mul = mul nsw i64 %va, %vb
  %add = add nsw i64 %acc, %mul
  %inc = add nuw nsw i64 %i, 1
  %exitcond = icmp eq i64 %inc, %n
  br i1 %exitcond, label %for.end, label %for.body

for.end:                                          ; preds = %for.body, %entry
  %result = phi i64 [ 0, %entry ], [ %add, %for.body ]
  ret i64 %result
}

attributes #0 = { nounwind uwtable }

!llvm.module.flags = !{!0, !1}
!0 = !{i32 1, !"wchar_size", i32 4}
!1 = !{i32 7, !"uwtable", i32 2}
!3 = !{!4, !4, i64 0}
!4 = !{!"long", !5, i64 0}
!5 = !{!"omnipotent char", !6, i64 0}
!6 = !{!"Simple C/C++ TBAA"}
