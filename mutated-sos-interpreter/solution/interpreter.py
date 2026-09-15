#!/usr/bin/env python3
"""IMP interpreter that executes programs under operator mappings
extracted from (potentially nonstandard) SOS rules."""


class BreakSignal(Exception):
    pass


class ContinueSignal(Exception):
    pass


class HaltSignal(Exception):
    pass


class IMPError(Exception):
    pass


class Interpreter:
    def __init__(self, arith_map, comp_map, logic_map, unary_map):
        self.store = {}
        self.arith_map = arith_map
        self.comp_map = comp_map
        self.logic_map = logic_map
        self.unary_map = unary_map

    def eval_expr(self, node):
        kind = node[0]
        if kind == 'num':
            return node[1]
        elif kind == 'var':
            name = node[1]
            if name not in self.store:
                raise IMPError(f'Undefined variable: {name}')
            return self.store[name]
        elif kind == 'bool':
            return node[1]
        elif kind == 'binop':
            op = node[1]
            lv = self.eval_expr(node[2])
            rv = self.eval_expr(node[3])
            actual = self.arith_map.get(op, op)
            if actual == '+':
                return lv + rv
            elif actual == '-':
                return lv - rv
            elif actual == '*':
                return lv * rv
            elif actual == '/':
                if rv == 0:
                    raise IMPError('Division by zero')
                return int(lv / rv)
            elif actual == '%':
                if rv == 0:
                    raise IMPError('Modulo by zero')
                return lv % rv
        elif kind == 'relop':
            op = node[1]
            lv = self.eval_expr(node[2])
            rv = self.eval_expr(node[3])
            actual = self.comp_map.get(op, op)
            if actual == '<':
                return lv < rv
            elif actual == '<=':
                return lv <= rv
            elif actual == '>':
                return lv > rv
            elif actual == '>=':
                return lv >= rv
            elif actual == '==':
                return lv == rv
            elif actual == '!=':
                return lv != rv
        elif kind == 'logop':
            op = node[1]
            lv = self.eval_expr(node[2])
            rv = self.eval_expr(node[3])
            actual = self.logic_map.get(op, op)
            if actual == '&&':
                return lv and rv
            elif actual == '||':
                return lv or rv
        elif kind == 'not':
            return not self.eval_expr(node[1])
        elif kind == 'unary':
            op = node[1]
            v = self.eval_expr(node[2])
            behavior = self.unary_map.get(
                op, 'negate' if op == '-' else 'identity'
            )
            if behavior == 'negate':
                return -v
            else:
                return v

    def exec_stmt(self, stmt):
        kind = stmt[0]
        if kind == 'int':
            self.store[stmt[1]] = 0
        elif kind == 'assign':
            name = stmt[1]
            if name not in self.store:
                raise IMPError(f'Assignment to undeclared variable: {name}')
            self.store[name] = self.eval_expr(stmt[2])
        elif kind == 'if':
            if self.eval_expr(stmt[1]):
                self.exec_stmts(stmt[2])
            else:
                self.exec_stmts(stmt[3])
        elif kind == 'while':
            while self.eval_expr(stmt[1]):
                try:
                    self.exec_stmts(stmt[2])
                except BreakSignal:
                    break
                except ContinueSignal:
                    continue
        elif kind == 'break':
            raise BreakSignal()
        elif kind == 'continue':
            raise ContinueSignal()
        elif kind == 'halt':
            raise HaltSignal()

    def exec_stmts(self, stmts):
        for stmt in stmts:
            self.exec_stmt(stmt)

    def run(self, program_ast):
        self.store = {}
        try:
            self.exec_stmts(program_ast)
        except HaltSignal:
            pass
        return dict(self.store)
