"""
Compiler from mini-Effekt AST to Guile Scheme.

Generates Scheme code using a free-monad approach: effects are represented
as SRFI-9 record types (pure/step), and handlers drive the computation
by pattern-matching on effect names and providing deep resumption
continuations.

"""

import sys
sys.path.insert(0, "/app")

from effekt import (
    Expr, IntLit, BoolLit, StrLit, UnitLit, Var, Let, LetRec,
    Lam, App, If, BinOp, UnaryOp, Do, Handle, HandlerClause,
    ReturnClause, Seq, Print,
)


class EffektToScheme:
    """Tree-walking compiler from mini-Effekt AST to Guile Scheme."""

    def __init__(self):
        self._counter = 0

    def _gensym(self, prefix="__g"):
        self._counter += 1
        return f"{prefix}{self._counter}"

    def compile(self, ast):
        """Compile an AST to a self-contained Guile Scheme program."""
        self._counter = 0
        body = self._emit(ast)
        return self._preamble() + self._main(body)

    # ------------------------------------------------------------------
    # Scheme runtime preamble
    # ------------------------------------------------------------------

    def _preamble(self):
        return """\
(use-modules (srfi srfi-9))

;;; ==== Free monad record types ====
(define-record-type <pure>
  (make-pure value)
  pure?
  (value pure-value))

(define-record-type <step>
  (make-step effect args cont)
  step?
  (effect step-effect)
  (args step-args)
  (cont step-cont))

;;; ==== Monadic bind ====
(define (flat-map comp f)
  (cond
    [(pure? comp) (f (pure-value comp))]
    [(step? comp)
     (make-step (step-effect comp)
                (step-args comp)
                (lambda (v) (flat-map ((step-cont comp) v) f)))]
    [else (error "flat-map: unknown computation" comp)]))

;;; ==== Effect handler (deep semantics) ====
(define (handle comp clauses return-clause)
  (cond
    [(pure? comp)
     (if return-clause
         (return-clause (pure-value comp))
         (make-pure (pure-value comp)))]
    [(step? comp)
     (let find-handler ([cs clauses])
       (cond
         [(null? cs)
          ;; unmatched effect -- propagate, preserving this handler
          (make-step (step-effect comp)
                     (step-args comp)
                     (lambda (v)
                       (handle ((step-cont comp) v) clauses return-clause)))]
         [(string=? (car (car cs)) (step-effect comp))
          ;; matched -- create deep resume and invoke handler body
          (let* ([handler-fn (cadr (car cs))]
                 [resume-fn (lambda (v)
                              (handle ((step-cont comp) v)
                                      clauses return-clause))])
            (handler-fn (step-args comp) resume-fn))]
         [else (find-handler (cdr cs))]))]
    [else (error "handle: unknown computation" comp)]))

;;; ==== Execute (drive effect-free computation to value) ====
(define (execute comp)
  (cond
    [(pure? comp) (pure-value comp)]
    [(step? comp) (error "Unhandled effect" (step-effect comp))]
    [else (error "execute: unknown computation" comp)]))

;;; ==== Print helper (matches Python str() formatting) ====
(define (effekt-print v)
  (cond
    [(eq? v #t) (display "True")]
    [(eq? v #f) (display "False")]
    [(eq? v 'unit) (display "()")]
    [else (display v)])
  (newline))

;;; ==== Result formatting ====
(define (effekt-format v)
  (cond
    [(eq? v #t) "True"]
    [(eq? v #f) "False"]
    [(eq? v 'unit) "()"]
    [(number? v) (number->string v)]
    [(string? v) v]
    [else (let ([p (open-output-string)])
            (display v p)
            (get-output-string p))]))

"""

    # ------------------------------------------------------------------
    # Main block
    # ------------------------------------------------------------------

    def _main(self, body_code):
        return f"""\
;;; ==== Compiled program ====
(let ([__result (execute {body_code})])
  (display "---RESULT---")
  (newline)
  (display (effekt-format __result))
  (newline))
"""

    # ------------------------------------------------------------------
    # AST emission
    # ------------------------------------------------------------------

    def _emit(self, expr):
        """Emit Scheme code for a single AST node (returns a Computation)."""

        if isinstance(expr, IntLit):
            return f"(make-pure {expr.value})"

        elif isinstance(expr, BoolLit):
            return f"(make-pure {'#t' if expr.value else '#f'})"

        elif isinstance(expr, StrLit):
            escaped = expr.value.replace("\\", "\\\\").replace('"', '\\"')
            return f'(make-pure "{escaped}")'

        elif isinstance(expr, UnitLit):
            return "(make-pure 'unit)"

        elif isinstance(expr, Var):
            return f"(make-pure {self._san(expr.name)})"

        elif isinstance(expr, Let):
            val = self._emit(expr.value)
            body = self._emit(expr.body)
            return f"(flat-map {val} (lambda ({self._san(expr.name)}) {body}))"

        elif isinstance(expr, LetRec):
            name = self._san(expr.name)
            func = self._emit_lambda_raw(expr.func)
            body = self._emit(expr.body)
            return f"(letrec ([{name} {func}]) {body})"

        elif isinstance(expr, Lam):
            return f"(make-pure {self._emit_lambda_raw(expr)})"

        elif isinstance(expr, App):
            return self._emit_app(expr)

        elif isinstance(expr, If):
            v = self._gensym("__c")
            cond = self._emit(expr.cond)
            then = self._emit(expr.then_br)
            else_br = self._emit(expr.else_br)
            return f"(flat-map {cond} (lambda ({v}) (if {v} {then} {else_br})))"

        elif isinstance(expr, BinOp):
            return self._emit_binop(expr)

        elif isinstance(expr, UnaryOp):
            return self._emit_unaryop(expr)

        elif isinstance(expr, Do):
            return self._emit_do(expr)

        elif isinstance(expr, Handle):
            return self._emit_handle(expr)

        elif isinstance(expr, Seq):
            return self._emit_seq(expr.exprs)

        elif isinstance(expr, Print):
            v = self._gensym("__pv")
            val = self._emit(expr.value)
            return f"(flat-map {val} (lambda ({v}) (effekt-print {v}) (make-pure 'unit)))"

        else:
            raise ValueError(f"Unknown AST node type: {type(expr).__name__}")

    # ------------------------------------------------------------------
    # Compound emission helpers
    # ------------------------------------------------------------------

    def _emit_lambda_raw(self, lam):
        """Emit a raw Scheme lambda (not wrapped in make-pure)."""
        params = " ".join(self._san(p) for p in lam.params)
        body = self._emit(lam.body)
        return f"(lambda ({params}) {body})"

    def _emit_app(self, expr):
        """Compile function application with argument evaluation chain."""
        func_code = self._emit(expr.func)
        fv = self._gensym("__f")

        if not expr.args:
            return f"(flat-map {func_code} (lambda ({fv}) ({fv})))"

        arg_vars = [self._gensym("__a") for _ in expr.args]

        # Innermost: call function with all evaluated arg values
        call = f"({fv} {' '.join(arg_vars)})"

        # Wrap in flat-maps for each argument (right to left)
        result = call
        for i in range(len(expr.args) - 1, -1, -1):
            arg_code = self._emit(expr.args[i])
            result = f"(flat-map {arg_code} (lambda ({arg_vars[i]}) {result}))"

        return f"(flat-map {func_code} (lambda ({fv}) {result}))"

    def _emit_binop(self, expr):
        """Compile binary operation."""
        lv = self._gensym("__l")
        rv = self._gensym("__r")
        left = self._emit(expr.left)
        right = self._emit(expr.right)
        op_expr = self._scheme_binop_expr(expr.op, lv, rv)
        return (f"(flat-map {left} (lambda ({lv}) "
                f"(flat-map {right} (lambda ({rv}) "
                f"(make-pure {op_expr})))))")

    def _emit_unaryop(self, expr):
        """Compile unary operation."""
        v = self._gensym("__u")
        operand = self._emit(expr.operand)
        op_fn = "not" if expr.op == "not" else "-"
        return f"(flat-map {operand} (lambda ({v}) (make-pure ({op_fn} {v}))))"

    def _emit_do(self, expr):
        """Compile effect performance (Do)."""
        if not expr.args:
            return (f'(make-step "{expr.effect}" (list) '
                    f'(lambda (v) (make-pure v)))')

        arg_vars = [self._gensym("__da") for _ in expr.args]
        innermost = (f'(make-step "{expr.effect}" '
                     f'(list {" ".join(arg_vars)}) '
                     f'(lambda (v) (make-pure v)))')

        result = innermost
        for i in range(len(expr.args) - 1, -1, -1):
            arg_code = self._emit(expr.args[i])
            result = f"(flat-map {arg_code} (lambda ({arg_vars[i]}) {result}))"

        return result

    def _emit_handle(self, expr):
        """Compile a Handle expression."""
        body = self._emit(expr.body)

        clause_strs = [self._emit_handler_clause(c) for c in expr.handlers]
        clauses_list = f"(list {' '.join(clause_strs)})" if clause_strs else "(list)"

        if expr.return_clause:
            rc_param = self._san(expr.return_clause.param)
            rc_body = self._emit(expr.return_clause.body)
            ret = f"(lambda ({rc_param}) {rc_body})"
        else:
            ret = "#f"

        return f"(handle {body} {clauses_list} {ret})"

    def _emit_handler_clause(self, clause):
        """Compile a single handler clause to a (list effect-name handler-fn) pair."""
        resume = self._san(clause.resume_name)
        body = self._emit(clause.body)

        if clause.params:
            bindings = " ".join(
                f"[{self._san(p)} (list-ref __hargs {i})]"
                for i, p in enumerate(clause.params)
            )
            handler_fn = (f"(lambda (__hargs __hresume) "
                          f"(let ({bindings} [{resume} __hresume]) "
                          f"{body}))")
        else:
            handler_fn = (f"(lambda (__hargs __hresume) "
                          f"(let ([{resume} __hresume]) "
                          f"{body}))")

        return f'(list "{clause.effect}" {handler_fn})'

    def _emit_seq(self, exprs):
        """Compile a sequence of expressions."""
        if not exprs:
            return "(make-pure 'unit)"
        if len(exprs) == 1:
            return self._emit(exprs[0])

        first = self._emit(exprs[0])
        rest = self._emit_seq(exprs[1:])
        v = self._gensym("__sq")
        return f"(flat-map {first} (lambda ({v}) {rest}))"

    # ------------------------------------------------------------------
    # Name sanitization and operator mapping
    # ------------------------------------------------------------------

    def _san(self, name):
        """Sanitize a variable name for Scheme (avoid keyword conflicts)."""
        return f"_e_{name}"

    def _scheme_binop_expr(self, op, lv, rv):
        """Map a mini-Effekt binop to a Scheme expression string."""
        if op == "!=":
            return f"(not (equal? {lv} {rv}))"
        simple = {
            "+": "+", "-": "-", "*": "*",
            "//": "quotient", "%": "remainder",
            "==": "equal?", "<": "<", ">": ">",
            "<=": "<=", ">=": ">=",
        }
        if op not in simple:
            raise ValueError(f"Unknown binary operator: {op}")
        return f"({simple[op]} {lv} {rv})"


def compile_program(ast):
    """Compile a mini-Effekt AST to a self-contained Guile Scheme program."""
    compiler = EffektToScheme()
    return compiler.compile(ast)
