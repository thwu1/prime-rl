; ModuleID = 'edge_cases'
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-i128:128-f80:128-n8:16:32:64-S128"
target triple = "x86_64-unknown-linux-gnu"

%struct.Tree = type { i32, ptr, ptr }
%struct.Pair = type { i64, i64 }
%struct.Tagged = type { i32, [4 x double] }

define i32 @tree_depth(ptr %node) {
entry:
  %is_null = icmp eq ptr %node, null
  br i1 %is_null, label %base, label %recurse

recurse:
  %lp = getelementptr %struct.Tree, ptr %node, i64 0, i32 1
  %left = load ptr, ptr %lp, align 8
  %rp = getelementptr %struct.Tree, ptr %node, i64 0, i32 2
  %right = load ptr, ptr %rp, align 8
  %ld = call i32 @tree_depth(ptr %left)
  %rd = call i32 @tree_depth(ptr %right)
  %cmp = icmp sgt i32 %ld, %rd
  %max = select i1 %cmp, i32 %ld, i32 %rd
  %depth = add i32 %max, 1
  ret i32 %depth

base:
  ret i32 0
}

define double @tagged_get(ptr %t, i32 %idx) {
entry:
  %arr_base = getelementptr %struct.Tagged, ptr %t, i64 0, i32 1, i32 0
  %elem = getelementptr double, ptr %arr_base, i32 %idx
  %val = load double, ptr %elem, align 8
  ret double %val
}

define i64 @pair_sum_array() {
entry:
  %pairs = alloca [10 x %struct.Pair], align 8
  %first = getelementptr [10 x %struct.Pair], ptr %pairs, i64 0, i64 0
  %f_a = getelementptr %struct.Pair, ptr %first, i64 0, i32 0
  %va = load i64, ptr %f_a, align 8
  %f_b = getelementptr %struct.Pair, ptr %first, i64 0, i32 1
  %vb = load i64, ptr %f_b, align 8
  %sum = add i64 %va, %vb
  ret i64 %sum
}

define i32 @conditional_load(ptr %a, ptr %b, i1 %cond) {
entry:
  %chosen = select i1 %cond, ptr %a, ptr %b
  %val = load i32, ptr %chosen, align 4
  ret i32 %val
}
