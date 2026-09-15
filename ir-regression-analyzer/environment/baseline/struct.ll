; ModuleID = 'struct.c'
source_filename = "struct.c"
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-i128:128-f80:128-n8:16:32:64-S128"
target triple = "x86_64-pc-linux-gnu"

%struct.Point = type { double, double, double }

; Function Attrs: nounwind uwtable
define dso_local double @distance(ptr noundef %p1, ptr noundef %p2) #0 {
entry:
  %x1.ptr = getelementptr inbounds %struct.Point, ptr %p1, i64 0, i32 0
  %x1 = load double, ptr %x1.ptr, align 8
  %y1.ptr = getelementptr inbounds %struct.Point, ptr %p1, i64 0, i32 1
  %y1 = load double, ptr %y1.ptr, align 8
  %z1.ptr = getelementptr inbounds %struct.Point, ptr %p1, i64 0, i32 2
  %z1 = load double, ptr %z1.ptr, align 8
  %x2.ptr = getelementptr inbounds %struct.Point, ptr %p2, i64 0, i32 0
  %x2 = load double, ptr %x2.ptr, align 8
  %y2.ptr = getelementptr inbounds %struct.Point, ptr %p2, i64 0, i32 1
  %y2 = load double, ptr %y2.ptr, align 8
  %z2.ptr = getelementptr inbounds %struct.Point, ptr %p2, i64 0, i32 2
  %z2 = load double, ptr %z2.ptr, align 8
  %dx = fsub double %x1, %x2
  %dy = fsub double %y1, %y2
  %dz = fsub double %z1, %z2
  %dx2 = fmul double %dx, %dx
  %dy2 = fmul double %dy, %dy
  %dz2 = fmul double %dz, %dz
  %sum1 = fadd double %dx2, %dy2
  %sum2 = fadd double %sum1, %dz2
  %result = call double @llvm.sqrt.f64(double %sum2)
  ret double %result
}

; Function Attrs: noinline nounwind uwtable
define internal double @square(double noundef %x) #1 {
entry:
  %r = fmul double %x, %x
  ret double %r
}

; Function Attrs: nocallback nofree nosync nounwind speculatable willreturn memory(none)
declare double @llvm.sqrt.f64(double) #2

attributes #0 = { nounwind uwtable }
attributes #1 = { noinline nounwind uwtable }
attributes #2 = { nocallback nofree nosync nounwind speculatable willreturn memory(none) }

!llvm.module.flags = !{!0, !1}
!llvm.ident = !{!2}

!0 = !{i32 1, !"wchar_size", i32 4}
!1 = !{i32 7, !"uwtable", i32 2}
!2 = !{!"clang version 19.0.0"}
