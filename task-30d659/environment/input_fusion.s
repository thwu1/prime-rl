
    .text

    .globl fma_splat
    .type fma_splat, @function
# FMA with scalar broadcast (from SPEC2017 554.roms_r hot loop pattern)
fma_splat:
    vsetvli t0, a0, e32, m1, ta, ma
    vle32.v v4, (a1)
    vle32.v v21, (a2)
    vfmv.v.f v6, fa4
    vfmadd.vv v4, v6, v21
    vse32.v v4, (a0)
    ret

    .globl fma_splat_stored
    .type fma_splat_stored, @function
# FMA with scalar broadcast, but broadcast value also stored to memory
fma_splat_stored:
    vsetvli t0, a0, e32, m1, ta, ma
    vle32.v v4, (a1)
    vle32.v v21, (a2)
    vfmv.v.f v6, fa4
    vfmadd.vv v4, v6, v21
    vse32.v v6, (a3)
    vse32.v v4, (a0)
    ret

    .globl int_add_scalar
    .type int_add_scalar, @function
# Integer add with broadcast scalar
int_add_scalar:
    vsetvli t0, a0, e32, m1, ta, ma
    vle32.v v8, (a1)
    vmv.v.x v10, a4
    vadd.vv v12, v8, v10
    vse32.v v12, (a0)
    ret

    .globl int_add_scalar_stored
    .type int_add_scalar_stored, @function
# Integer add with broadcast, but broadcast value stored to memory
int_add_scalar_stored:
    vsetvli t0, a0, e32, m1, ta, ma
    vle32.v v8, (a1)
    vmv.v.x v10, a4
    vadd.vv v12, v8, v10
    vse32.v v10, (a2)
    vse32.v v12, (a0)
    ret

    .globl multi_fuse
    .type multi_fuse, @function
# Scalar broadcast used in multiple fusable arithmetic operations
multi_fuse:
    vsetvli t0, a0, e32, m1, ta, ma
    vle32.v v8, (a1)
    vle32.v v14, (a2)
    vmv.v.x v10, a4
    vadd.vv v12, v8, v10
    vadd.vv v16, v14, v10
    vse32.v v12, (a0)
    vse32.v v16, (a3)
    ret
