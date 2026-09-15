; ModuleID = 'interop'
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-i128:128-f80:128-n8:16:32:64-S128"
target triple = "x86_64-unknown-linux-gnu"

%struct.Widget = type { i32, double, ptr }
%struct.Panel = type { %struct.Widget, %struct.Widget, i32 }

define void @widget_set_value(ptr %w) {
entry:
  %vp = getelementptr %struct.Widget, ptr %w, i64 0, i32 1
  store double 1.000000e+00, ptr %vp, align 8
  ret void
}

define void @init_widget(ptr %w) {
entry:
  call void @widget_set_value(ptr %w)
  ret void
}

define double @read_widget_value(ptr %w) {
entry:
  %vp = getelementptr %struct.Widget, ptr %w, i64 0, i32 1
  %v = load double, ptr %vp, align 8
  ret double %v
}

define double @panel_primary_value(ptr %p) {
entry:
  %vp = getelementptr %struct.Panel, ptr %p, i64 0, i32 0, i32 1
  %v = load double, ptr %vp, align 8
  ret double %v
}

define ptr @panel_value_ptr(ptr %p) {
entry:
  %vp = getelementptr %struct.Panel, ptr %p, i64 0, i32 0, i32 1
  ret ptr %vp
}

define ptr @panel_label_ptr(ptr %p) {
entry:
  %lp = getelementptr %struct.Panel, ptr %p, i64 0, i32 0, i32 2
  ret ptr %lp
}
