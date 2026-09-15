"""Bytecode compiler: AST -> stack-based bytecode instructions.

The compiler translates the AST into a flat list of instructions for the VM.
Each instruction is a list: [opcode] or [opcode, arg1, ...].

Jump targets are initially labels (strings) and resolved to absolute
instruction indices before output.
"""

import json
import sys
from ast_nodes import (
    Program, FuncDef, AssignStmt, IfStmt, WhileStmt, ReturnStmt,
    PrintStmt, IntLit, VarRef, BinOp, UnaryOp, FuncCall,
)

# Opcode constants
OP_PUSH_INT = "PUSH_INT"
OP_POP = "POP"
OP_DUP = "DUP"
OP_ADD = "ADD"
OP_SUB = "SUB"
OP_MUL = "MUL"
OP_DIV = "DIV"
OP_MOD = "MOD"
OP_NEG = "NEG"
OP_EQ = "EQ"
OP_NE = "NE"
OP_LT = "LT"
OP_LE = "LE"
OP_GT = "GT"
OP_GE = "GE"
OP_NOT = "NOT"
OP_AND = "AND"
OP_OR = "OR"
OP_LOAD = "LOAD"
OP_STORE = "STORE"
OP_JMP = "JMP"
OP_JMP_FALSE = "JMP_FALSE"
OP_CALL = "CALL"
OP_RET = "RET"
OP_PRINT = "PRINT"
OP_HALT = "HALT"

BINARY_OP_MAP = {
    '+': OP_ADD, '-': OP_SUB, '*': OP_MUL, '/': OP_DIV, '%': OP_MOD,
    '==': OP_EQ, '!=': OP_NE, '<': OP_LT, '<=': OP_LE,
    '>': OP_GT, '>=': OP_GE, '&&': OP_AND, '||': OP_OR,
}


class CompileError(Exception):
    pass


class Compiler:
    def __init__(self):
        self.functions = {}
        self.code = []
        self._label_counter = 0

    def _new_label(self):
        self._label_counter += 1
        return f"__L{self._label_counter}"

    def compile(self, program):
        for func in program.functions:
            self._compile_func(func)
        for stmt in program.main_body:
            self._compile_stmt(stmt, self.code)
        self.code.append([OP_HALT])
        self._resolve_labels(self.code)
        for fname in self.functions:
            self._resolve_labels(self.functions[fname]["code"])
        return {"main": self.code, "functions": self.functions}

    def _compile_func(self, func):
        code = []
        for stmt in func.body:
            self._compile_stmt(stmt, code)
        code.append([OP_PUSH_INT, 0])
        code.append([OP_RET])
        self.functions[func.name] = {"params": func.params, "code": code}

    def _compile_stmt(self, stmt, code):
        if isinstance(stmt, AssignStmt):
            self._compile_expr(stmt.expr, code)
            code.append([OP_STORE, stmt.name])
        elif isinstance(stmt, PrintStmt):
            for expr in stmt.exprs:
                self._compile_expr(expr, code)
            code.append([OP_PRINT, len(stmt.exprs)])
        elif isinstance(stmt, IfStmt):
            self._compile_expr(stmt.cond, code)
            if stmt.else_body:
                else_label = self._new_label()
                end_label = self._new_label()
                code.append([OP_JMP_FALSE, else_label])
                for s in stmt.then_body:
                    self._compile_stmt(s, code)
                code.append([OP_JMP, end_label])
                code.append(["LABEL", else_label])
                for s in stmt.else_body:
                    self._compile_stmt(s, code)
                code.append(["LABEL", end_label])
            else:
                end_label = self._new_label()
                code.append([OP_JMP_FALSE, end_label])
                for s in stmt.then_body:
                    self._compile_stmt(s, code)
                code.append(["LABEL", end_label])
        elif isinstance(stmt, WhileStmt):
            start_label = self._new_label()
            end_label = self._new_label()
            code.append(["LABEL", start_label])
            self._compile_expr(stmt.cond, code)
            code.append([OP_JMP_FALSE, end_label])
            for s in stmt.body:
                self._compile_stmt(s, code)
            code.append([OP_JMP, start_label])
            code.append(["LABEL", end_label])
        elif isinstance(stmt, ReturnStmt):
            self._compile_expr(stmt.expr, code)
            code.append([OP_RET])
        else:
            raise CompileError(f"Unknown statement type: {type(stmt).__name__}")

    def _compile_expr(self, expr, code):
        if isinstance(expr, IntLit):
            code.append([OP_PUSH_INT, expr.value])
        elif isinstance(expr, VarRef):
            code.append([OP_LOAD, expr.name])
        elif isinstance(expr, BinOp):
            self._compile_expr(expr.left, code)
            self._compile_expr(expr.right, code)
            if expr.op in BINARY_OP_MAP:
                code.append([BINARY_OP_MAP[expr.op]])
            else:
                raise CompileError(f"Unknown binary operator: {expr.op}")
        elif isinstance(expr, UnaryOp):
            self._compile_expr(expr.operand, code)
            if expr.op == '-':
                code.append([OP_NEG])
            elif expr.op == '!':
                code.append([OP_NOT])
            else:
                raise CompileError(f"Unknown unary operator: {expr.op}")
        elif isinstance(expr, FuncCall):
            for arg in expr.args:
                self._compile_expr(arg, code)
            code.append([OP_CALL, expr.name, len(expr.args)])
        else:
            raise CompileError(f"Unknown expression type: {type(expr).__name__}")

    def _resolve_labels(self, code):
        """Replace label references with absolute instruction indices."""
        labels = {}
        real_idx = 0
        for instr in code:
            if instr[0] == "LABEL":
                labels[instr[1]] = real_idx
            else:
                real_idx += 1
        new_code = []
        for instr in code:
            if instr[0] == "LABEL":
                continue
            if instr[0] in (OP_JMP, OP_JMP_FALSE) and isinstance(instr[1], str):
                new_code.append([instr[0], labels[instr[1]]])
            else:
                new_code.append(list(instr))
        code.clear()
        code.extend(new_code)


def compile_source(source):
    """Compile MiniCalc source code to bytecode dict."""
    from lexer import Lexer
    from parser import Parser
    tokens = Lexer(source).tokenize()
    ast = Parser(tokens).parse()
    return Compiler().compile(ast)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python3 compiler.py <input.mc> <output.json>", file=sys.stderr)
        sys.exit(1)
    with open(sys.argv[1]) as f:
        source = f.read()
    bytecode = compile_source(source)
    with open(sys.argv[2], "w") as f:
        json.dump(bytecode, f, indent=2)
