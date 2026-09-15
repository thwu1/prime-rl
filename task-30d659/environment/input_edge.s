
    .text

    .globl vec_sub_fusable
    .type vec_sub_fusable, @function
# Integer subtract with broadcast in subtrahend position
vec_sub_fusable:
    vsetvli t0, a0, e32, m1, ta, ma
    vle32.v v8, (a1)
    vmv.v.x v10, a4
    vsub.vv v12, v8, v10
    vse32.v v12, (a0)
    ret

    .globl vec_sub_nonfusable
    .type vec_sub_nonfusable, @function
# Integer subtract with broadcast in minuend position
vec_sub_nonfusable:
    vsetvli t0, a0, e32, m1, ta, ma
    vle32.v v8, (a1)
    vmv.v.x v10, a4
    vsub.vv v12, v10, v8
    vse32.v v12, (a0)
    ret

    .globl vsetvli_diff_rd
    .type vsetvli_diff_rd, @function
# Two vsetvli with identical config but writing to different registers
vsetvli_diff_rd:
    vsetvli t0, a2, e32, m1, ta, ma
    vle32.v v8, (a0)
    vfadd.vv v8, v8, v8
    vsetvli t1, a2, e32, m1, ta, ma
    vse32.v v8, (a0)
    mv      a0, t1
    ret

    .globl broadcast_before_kill
    .type broadcast_before_kill, @function
# Broadcast register overwritten between fusable use and later vector use
broadcast_before_kill:
    vsetvli t0, a0, e32, m1, ta, ma
    vle32.v v0, (a1)
    vle32.v v2, (a2)
    vmv.v.x v4, a4
    vadd.vv v6, v0, v4
    vle32.v v4, (a3)
    vadd.vv v8, v2, v4
    vse32.v v6, (a0)
    vse32.v v8, (a3)
    ret
