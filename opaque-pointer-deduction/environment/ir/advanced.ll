; ModuleID = 'advanced'
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-i128:128-f80:128-n8:16:32:64-S128"
target triple = "x86_64-unknown-linux-gnu"

%struct.Node = type { i32, ptr }
%struct.Matrix = type { i32, i32, ptr }

@g_count = global i32 0, align 4
@g_buffer = global [256 x i8] zeroinitializer, align 16

define void @inc_count() {
entry:
  %v = load i32, ptr @g_count, align 4
  %v1 = add i32 %v, 1
  store i32 %v1, ptr @g_count, align 4
  ret void
}

define void @clear_buffer() {
entry:
  %p = getelementptr [256 x i8], ptr @g_buffer, i64 0, i64 0
  store i8 0, ptr %p, align 1
  ret void
}

define i32 @list_sum(ptr %head) {
entry:
  %null_check = icmp eq ptr %head, null
  br i1 %null_check, label %done, label %loop

loop:
  %cur = phi ptr [ %head, %entry ], [ %next, %loop ]
  %acc = phi i32 [ 0, %entry ], [ %acc_next, %loop ]
  %val_ptr = getelementptr %struct.Node, ptr %cur, i64 0, i32 0
  %val = load i32, ptr %val_ptr, align 4
  %acc_next = add i32 %acc, %val
  %next_ptr = getelementptr %struct.Node, ptr %cur, i64 0, i32 1
  %next = load ptr, ptr %next_ptr, align 8
  %is_null = icmp eq ptr %next, null
  br i1 %is_null, label %done, label %loop

done:
  %result = phi i32 [ 0, %entry ], [ %acc_next, %loop ]
  ret i32 %result
}

define double @matrix_get(ptr %m, i32 %row, i32 %col) {
entry:
  %cols_ptr = getelementptr %struct.Matrix, ptr %m, i64 0, i32 1
  %cols = load i32, ptr %cols_ptr, align 4
  %offset = mul i32 %row, %cols
  %idx = add i32 %offset, %col
  %data_ptr = getelementptr %struct.Matrix, ptr %m, i64 0, i32 2
  %data = load ptr, ptr %data_ptr, align 8
  %elem_ptr = getelementptr double, ptr %data, i32 %idx
  %val = load double, ptr %elem_ptr, align 8
  ret double %val
}

define void @init_node(ptr %n, i32 %val) {
entry:
  %vp = getelementptr %struct.Node, ptr %n, i64 0, i32 0
  store i32 %val, ptr %vp, align 4
  %np = getelementptr %struct.Node, ptr %n, i64 0, i32 1
  store ptr null, ptr %np, align 8
  ret void
}

define ptr @create_node(i32 %val) {
entry:
  %n = alloca %struct.Node, align 8
  call void @init_node(ptr %n, i32 %val)
  ret ptr %n
}

define void @store_value(ptr %dst) {
entry:
  store double 0x4009000000000000, ptr %dst, align 8
  ret void
}

define void @process(ptr %target) {
entry:
  call void @store_value(ptr %target)
  ret void
}

define void @caller() {
entry:
  %buf = alloca double, align 8
  call void @process(ptr %buf)
  ret void
}
