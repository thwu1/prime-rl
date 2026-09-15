;
; Matrix multiplication kernel — LLVM IR for NVPTX64.
; Compile with: llc-18 --march=nvptx64 --mcpu=sm_80 -o matmul.ptx matmul.ll

target datalayout = "e-i64:64-i128:128-v16:16-v32:32-n16:32:64"
target triple = "nvptx64-nvidia-cuda"

define void @matmul(ptr addrspace(1) %A, ptr addrspace(1) %B, ptr addrspace(1) %C, i32 %N) {
entry:
  %tid.x = call i32 @llvm.nvvm.read.ptx.sreg.tid.x()
  %ctaid.x = call i32 @llvm.nvvm.read.ptx.sreg.ctaid.x()
  %ntid.x = call i32 @llvm.nvvm.read.ptx.sreg.ntid.x()
  %tid.y = call i32 @llvm.nvvm.read.ptx.sreg.tid.y()
  %ctaid.y = call i32 @llvm.nvvm.read.ptx.sreg.ctaid.y()
  %ntid.y = call i32 @llvm.nvvm.read.ptx.sreg.ntid.y()
  %0 = mul i32 %ctaid.y, %ntid.y
  %row = add i32 %0, %tid.y
  %1 = mul i32 %ctaid.x, %ntid.x
  %col = add i32 %1, %tid.x
  %2 = icmp slt i32 %row, %N
  %3 = icmp slt i32 %col, %N
  %4 = and i1 %2, %3
  br i1 %4, label %loop.preheader, label %exit

loop.preheader:
  %row.ext = sext i32 %row to i64
  %col.ext = sext i32 %col to i64
  %N.ext = sext i32 %N to i64
  br label %loop.header

loop.header:
  %k = phi i32 [0, %loop.preheader], [%k.next, %loop.body]
  %acc = phi float [0.0, %loop.preheader], [%acc.next, %loop.body]
  %5 = icmp slt i32 %k, %N
  br i1 %5, label %loop.body, label %store

loop.body:
  %k.ext = sext i32 %k to i64
  %a.row.off = mul i64 %row.ext, %N.ext
  %a.idx = add i64 %a.row.off, %k.ext
  %a.ptr = getelementptr float, ptr addrspace(1) %A, i64 %a.idx
  %a.val = load float, ptr addrspace(1) %a.ptr
  %b.row.off = mul i64 %k.ext, %N.ext
  %b.idx = add i64 %b.row.off, %col.ext
  %b.ptr = getelementptr float, ptr addrspace(1) %B, i64 %b.idx
  %b.val = load float, ptr addrspace(1) %b.ptr
  %prod = fmul float %a.val, %b.val
  %acc.next = fadd float %acc, %prod
  %k.next = add i32 %k, 1
  br label %loop.header

store:
  %c.row.off = mul i64 %row.ext, %N.ext
  %c.idx = add i64 %c.row.off, %col.ext
  %c.ptr = getelementptr float, ptr addrspace(1) %C, i64 %c.idx
  store float %acc, ptr addrspace(1) %c.ptr
  br label %exit

exit:
  ret void
}

declare i32 @llvm.nvvm.read.ptx.sreg.tid.x()
declare i32 @llvm.nvvm.read.ptx.sreg.tid.y()
declare i32 @llvm.nvvm.read.ptx.sreg.ctaid.x()
declare i32 @llvm.nvvm.read.ptx.sreg.ctaid.y()
declare i32 @llvm.nvvm.read.ptx.sreg.ntid.x()
declare i32 @llvm.nvvm.read.ptx.sreg.ntid.y()

!nvvm.annotations = !{!0}
!0 = !{ptr @matmul, !"kernel", i32 1}
