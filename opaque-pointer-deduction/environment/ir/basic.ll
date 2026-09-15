; ModuleID = 'basic_types'
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-i128:128-f80:128-n8:16:32:64-S128"
target triple = "x86_64-unknown-linux-gnu"

%struct.Point = type { double, double }
%struct.Rect = type { %struct.Point, %struct.Point }
%struct.Color = type { i8, i8, i8, i8 }

define i32 @scalar_ops() {
entry:
  %x = alloca i32, align 4
  %y = alloca i64, align 8
  %f = alloca float, align 4
  store i32 42, ptr %x, align 4
  store i64 100, ptr %y, align 8
  store float 0x40091EB860000000, ptr %f, align 4
  %xv = load i32, ptr %x, align 4
  ret i32 %xv
}

define double @point_get_x(ptr %p) {
entry:
  %xptr = getelementptr %struct.Point, ptr %p, i64 0, i32 0
  %x = load double, ptr %xptr, align 8
  ret double %x
}

define void @point_set(ptr %p, double %x, double %y) {
entry:
  %xptr = getelementptr %struct.Point, ptr %p, i64 0, i32 0
  store double %x, ptr %xptr, align 8
  %yptr = getelementptr %struct.Point, ptr %p, i64 0, i32 1
  store double %y, ptr %yptr, align 8
  ret void
}

define double @rect_origin_x(ptr %r) {
entry:
  %ox = getelementptr %struct.Rect, ptr %r, i64 0, i32 0, i32 0
  %v = load double, ptr %ox, align 8
  ret double %v
}

define void @rect_set_corner(ptr %r, double %x, double %y) {
entry:
  %cx = getelementptr %struct.Rect, ptr %r, i64 0, i32 1, i32 0
  store double %x, ptr %cx, align 8
  %cy = getelementptr %struct.Rect, ptr %r, i64 0, i32 1, i32 1
  store double %y, ptr %cy, align 8
  ret void
}

define i32 @array_sum(ptr %arr, i32 %n) {
entry:
  br label %loop
loop:
  %i = phi i32 [ 0, %entry ], [ %inext, %loop ]
  %s = phi i32 [ 0, %entry ], [ %snext, %loop ]
  %ep = getelementptr i32, ptr %arr, i32 %i
  %ev = load i32, ptr %ep, align 4
  %snext = add i32 %s, %ev
  %inext = add i32 %i, 1
  %cmp = icmp slt i32 %inext, %n
  br i1 %cmp, label %loop, label %exit
exit:
  ret i32 %snext
}

define i32 @deref_pp(ptr %pp) {
entry:
  %p = load ptr, ptr %pp, align 8
  %v = load i32, ptr %p, align 4
  ret i32 %v
}

define i8 @get_alpha(ptr %c) {
entry:
  %aptr = getelementptr %struct.Color, ptr %c, i64 0, i32 3
  %a = load i8, ptr %aptr, align 1
  ret i8 %a
}

define ptr @rect_origin_ptr(ptr %r) {
entry:
  %op = getelementptr %struct.Rect, ptr %r, i64 0, i32 0, i32 0
  ret ptr %op
}

define ptr @rect_corner_y_ptr(ptr %r) {
entry:
  %cy = getelementptr %struct.Rect, ptr %r, i64 0, i32 1, i32 1
  ret ptr %cy
}
