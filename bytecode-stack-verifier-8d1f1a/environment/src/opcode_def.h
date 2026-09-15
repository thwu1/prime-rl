/*
 * Bytecode VM Opcode Definitions — Authoritative Specification
 *
 * Inspired by the QuickJS bytecode interpreter opcode table.
 *
 * DEF(name, size, n_pop, n_push)
 *   name:   opcode mnemonic
 *   size:   total instruction size in bytes (opcode byte + operand bytes)
 *   n_pop:  number of values popped from the stack.  -1 = variable
 *   n_push: number of values pushed onto the stack
 *
 * Operand encoding (little-endian, follows the opcode byte):
 *   i32  — signed 32-bit   (size = 5)
 *   u32  — unsigned 32-bit (size = 5)
 *   u16  — unsigned 16-bit (size = 3)
 *
 * Branch offsets (if_false, if_true, goto_op, catch) are signed 32-bit
 * integers giving a byte offset RELATIVE TO THE START of the branch
 * instruction itself.
 *
 * The 'call' instruction carries a u16 operand specifying the argument
 * count.  It pops (arg_count + 1) values from the stack: the callee
 * (function object) plus each argument.  It pushes 1 value: the result.
 *
 * The 'catch' instruction registers an exception handler.  In normal
 * (non-exceptional) execution it is a no-op (pop 0, push 0).  When an
 * exception is thrown inside the protected region, the VM transfers
 * control to the handler offset with the exception value pushed on top
 * of the stack — so the handler entry stack depth is one greater than
 * the depth after the catch instruction on the normal path.
 *
 */

#ifdef DEF

/* -- Values -------------------------------------------------------- */
DEF(invalid,       1, 0, 0)  /* opcode 0, never emitted              */
DEF(push_i32,      5, 0, 1)  /* operand: i32 value                   */
DEF(push_const,    5, 0, 1)  /* operand: u32 constant-pool index     */
DEF(undefined,     1, 0, 1)
DEF(null_val,      1, 0, 1)
DEF(push_false,    1, 0, 1)
DEF(push_true,     1, 0, 1)
DEF(object,        1, 0, 1)  /* push empty object                    */

/* -- Stack manipulation -------------------------------------------- */
DEF(drop,          1, 1, 0)  /* a ->                                 */
DEF(dup,           1, 1, 2)  /* a -> a a                             */
DEF(dup2,          1, 2, 4)  /* a b -> a b a b                       */
DEF(swap,          1, 2, 2)  /* a b -> b a                           */
DEF(rot3l,         1, 3, 3)  /* a b c -> b c a                       */

/* -- Arithmetic ---------------------------------------------------- */
DEF(add,           1, 2, 1)
DEF(sub,           1, 2, 1)
DEF(mul,           1, 2, 1)
DEF(div_op,        1, 2, 1)
DEF(mod_op,        1, 2, 1)
DEF(neg,           1, 1, 1)
DEF(inc,           1, 1, 1)
DEF(dec,           1, 1, 1)

/* -- Bitwise ------------------------------------------------------- */
DEF(shl,           1, 2, 1)
DEF(sar,           1, 2, 1)
DEF(shr,           1, 2, 1)
DEF(bit_and,       1, 2, 1)
DEF(bit_or,        1, 2, 1)
DEF(bit_xor,       1, 2, 1)
DEF(bit_not,       1, 1, 1)
DEF(lnot,          1, 1, 1)

/* -- Comparison ---------------------------------------------------- */
DEF(eq,            1, 2, 1)
DEF(neq,           1, 2, 1)
DEF(strict_eq,     1, 2, 1)
DEF(strict_neq,    1, 2, 1)
DEF(lt,            1, 2, 1)
DEF(lte,           1, 2, 1)
DEF(gt,            1, 2, 1)
DEF(gte,           1, 2, 1)

/* -- Locals / arguments -------------------------------------------- */
DEF(get_loc,       3, 0, 1)  /* operand: u16 local index             */
DEF(put_loc,       3, 1, 0)  /* operand: u16 local index             */
DEF(set_loc,       3, 1, 1)  /* operand: u16 local index             *
                               * like put_loc but KEEPS the value on  *
                               * the stack  (pop 1, push 1)           */
DEF(get_arg,       3, 0, 1)  /* operand: u16 argument index          */
DEF(put_arg,       3, 1, 0)  /* operand: u16 argument index          */

/* -- Property access ----------------------------------------------- */
DEF(get_field,     5, 1, 1)  /* operand: u32 field-name id           */
DEF(put_field,     5, 2, 0)  /* operand: u32 field-name id           */
DEF(get_array_el,  1, 2, 1)  /* obj idx -> val                       */
DEF(put_array_el,  1, 3, 0)  /* obj idx val ->                       */

/* -- Control flow -------------------------------------------------- */
DEF(call,          3,-1, 1)  /* operand: u16 arg_count               *
                               * pops (arg_count + 1), pushes 1       */
DEF(return_val,    1, 1, 0)
DEF(return_undef,  1, 0, 0)
DEF(if_false,      5, 1, 0)  /* operand: i32 relative offset         */
DEF(if_true,       5, 1, 0)  /* operand: i32 relative offset         */
DEF(goto_op,       5, 0, 0)  /* operand: i32 relative offset         */

/* -- Exceptions ---------------------------------------------------- */
DEF(catch,         5, 0, 0)  /* operand: i32 handler relative offset *
                               * normal flow: no-op                   *
                               * handler entry: exception pushed      */
DEF(end_catch,     1, 0, 0)  /* deregister exception handler         */
DEF(throw_op,      1, 1, 0)  /* pop value and throw                  */

/* -- Miscellaneous ------------------------------------------------- */
DEF(typeof_op,     1, 1, 1)
DEF(instanceof_op, 1, 2, 1)
DEF(in_op,         1, 2, 1)
DEF(nop,           1, 0, 0)

#undef DEF
#endif /* DEF */
