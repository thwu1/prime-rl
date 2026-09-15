
    .text

    .globl vec_add_f32
    .type vec_add_f32, @function
# Float vector add: dst[i] = src1[i] + src2[i]
vec_add_f32:
    blez    a3, .Ladd_end
.Ladd_loop:
    vsetvli t0, a3, e32, m1, ta, ma
    vle32.v v8, (a1)
    vle32.v v10, (a2)
    vsetvli t0, a3, e32, m1, ta, ma
    vfadd.vv v12, v8, v10
    vse32.v v12, (a0)
    sub     a3, a3, t0
    slli    t1, t0, 2
    add     a0, a0, t1
    add     a1, a1, t1
    add     a2, a2, t1
    bnez    a3, .Ladd_loop
.Ladd_end:
    ret

    .globl vec_saxpy_f64
    .type vec_saxpy_f64, @function
# Double SAXPY: y[i] = a*x[i] + y[i]
vec_saxpy_f64:
    blez    a2, .Lsaxpy_end
.Lsaxpy_loop:
    vsetvli t0, a2, e64, m2, ta, ma
    vle64.v v8, (a1)
    vle64.v v12, (a0)
    vsetvli t0, a2, e64, m2, ta, ma
    vfmadd.vf v8, fa0, v12
    vse64.v v8, (a0)
    sub     a2, a2, t0
    slli    t1, t0, 3
    add     a0, a0, t1
    add     a1, a1, t1
    bnez    a2, .Lsaxpy_loop
.Lsaxpy_end:
    ret

    .globl vec_convert
    .type vec_convert, @function
# Widen int16 to int32
vec_convert:
    blez    a2, .Lcvt_end
.Lcvt_loop:
    vsetvli t0, a2, e16, m1, ta, ma
    vle16.v v8, (a1)
    vsetvli t0, a2, e32, m2, ta, ma
    vsext.vf2 v12, v8
    vse32.v v12, (a0)
    sub     a2, a2, t0
    slli    t1, t0, 2
    add     a0, a0, t1
    slli    t2, t0, 1
    add     a1, a1, t2
    bnez    a2, .Lcvt_loop
.Lcvt_end:
    ret
