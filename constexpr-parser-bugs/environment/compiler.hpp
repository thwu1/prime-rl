#ifndef CXVM_COMPILER_HPP
#define CXVM_COMPILER_HPP


#include "bytecode.hpp"
#include <string_view>

namespace cxvm {

// --------------------------------------------------------------------------
// compile() — translate an expression into a cxvm::Program at compile time.
//
// Grammar (lowest to highest precedence):
//
//   expr       := let_expr
//   let_expr   := 'let' IDENT '=' expr 'in' expr
//              |  ternary
//   ternary    := comparison ('?' expr ':' expr)?
//   comparison := additive (('<'|'>'|'<='|'>='|'=='|'!=') additive)?
//   additive   := term (('+'|'-') term)*
//   term       := power (('*'|'/'|'%') power)*
//   power      := unary ('^' power)?        // right-to-left associative
//   unary      := '-' unary | primary
//   primary    := NUMBER | FUNC '(' args ')' | IDENT | '(' expr ')'
//
// FEATURES:
//
// 1) Literals: integer and floating-point (42, 3.14, 0.5)
//
// 2) Binary arithmetic: +, -, *, /, % (fmod), ^ (power)
//    Standard precedence. +/- lowest, then *//%, then ^.
//    +, -, *, /, % are left-to-right. ^ is RIGHT-TO-LEFT.
//
// 3) Unary minus: prefix '-', chains (--x == x)
//
// 4) Parentheses: ( expr )
//
// 5) Variables: single lowercase letter a-z -> LOAD_VAR (index 0-25)
//    Variables referenced inside a let-binding body that match the
//    binding name must use LOAD_LOCAL instead.
//
// 6) Built-in functions:
//      abs(expr)        -> CALL_ABS
//      min(expr, expr)  -> CALL_MIN
//      max(expr, expr)  -> CALL_MAX
//      sqrt(expr)       -> CALL_SQRT
//
// 7) Comparison operators (non-associative, produce 1.0 or 0.0):
//      <  ->  CMP_LT        >  ->  CMP_GT
//      <= ->  CMP_LE        >= ->  CMP_GE
//      == ->  CMP_EQ        != ->  CMP_NE
//
// 8) Ternary conditional: cond ? then_expr : else_expr
//    Emit: <cond>, JZ else_label, <then>, JMP end_label,
//          else_label: <else>, end_label: ...
//
// 9) Let-bindings: let <var> = <init> in <body>
//    Emit: <init>, STORE_LOCAL slot, <body using LOAD_LOCAL slot>
//    Local variables shadow global variables of the same name.
//    Nested let-bindings may reuse variable names (inner shadows outer).
//    Each binding gets a unique slot index (0, 1, 2, ...).
//
// 10) Constant folding & optimization:
//     a) Constant sub-expressions fold to a single PUSH_CONST.
//     b) Constant comparisons fold to PUSH_CONST 1.0 or 0.0.
//     c) Ternary with constant condition: eliminate dead branch entirely
//        (no JZ/JMP, emit only the live branch).
//     d) Let-bindings where the init expression is a constant: propagate
//        the constant value to all uses in the body (replace LOAD_LOCAL
//        with PUSH_CONST), then remove the STORE_LOCAL.
//     e) Function calls with all-constant arguments fold to PUSH_CONST.
//     f) Power and modulo with constant operands fold to PUSH_CONST.
//
// 11) Whitespace: arbitrary spaces between tokens.
//
// 12) The returned Program must be finalized (terminated with HALT).
//
// All of the above must work in a constexpr context.
// --------------------------------------------------------------------------

template<int MaxLen = 256>
constexpr Program<MaxLen> compile([[maybe_unused]] std::string_view expr) {
    Program<MaxLen> prog;
    // TODO: implement expression compiler
    prog.finalize();
    return prog;
}

} // namespace cxvm

#endif // CXVM_COMPILER_HPP
