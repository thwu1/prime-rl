
    .text

    .globl mixed_opts
    .type mixed_opts, @function
# Mixed: redundant vsetvli and fusable broadcast in one function
mixed_opts:
    vsetvli t0, a3, e32, m1, ta, ma
    vle32.v v0, (a0)
    vle32.v v2, (a1)
    vle32.v v4, (a2)
    vfmv.v.f v6, fa0
    vfmul.vv v8, v0, v6
    vsetvli t0, a3, e32, m1, ta, ma
    vfadd.vv v2, v2, v4
    vse32.v v8, (a0)
    vse32.v v2, (a1)
    ret

    .globl across_label
    .type across_label, @function
# Two identical vsetvli separated by a branch target label
across_label:
    vsetvli t0, a2, e32, m1, ta, ma
    beqz    a2, .Lskip
    vle32.v v8, (a0)
    vadd.vi v8, v8, 1
    vse32.v v8, (a0)
.Lskip:
    vsetvli t0, a2, e32, m1, ta, ma
    vle32.v v10, (a1)
    vadd.vi v10, v10, 2
    vse32.v v10, (a1)
    ret

    .globl chain_fusion
    .type chain_fusion, @function
# Multiple consecutive broadcast-then-use patterns
chain_fusion:
    vsetvli t0, a2, e64, m1, ta, ma
    vle64.v v0, (a0)
    vle64.v v2, (a1)
    vfmv.v.f v4, fa0
    vfmul.vv v6, v0, v4
    vfmv.v.f v8, fa1
    vfmadd.vv v2, v8, v6
    vse64.v v2, (a0)
    ret
