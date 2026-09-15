#!/usr/bin/env python3
"""
Implement while loops with break/continue in the Monkey language compiler+VM.

Modifies:
  - token/token.go: add While, Break, Continue keywords
  - ast/while.go: new AST node types (WhileExpression, BreakStatement, ContinueStatement)
  - parser/parser.go: parse while expressions, break and continue statements
  - compiler/compiler.go: compile while/break/continue to bytecode
  - vm/vm.go: fix two bugs in postfix operator (offset reads + in-place mutation)
"""

import sys
import os


def patch_file(path, replacements):
    """Apply a list of (old, new) string replacements to a file. Each must match exactly once."""
    with open(path) as f:
        content = f.read()
    for old, new in replacements:
        if old not in content:
            print(f"ERROR: Pattern not found in {path}:")
            print(f"  Looking for: {repr(old[:120])}")
            sys.exit(1)
        if content.count(old) > 1:
            print(f"WARNING: Pattern found {content.count(old)} times in {path}, replacing first:")
            print(f"  Pattern: {repr(old[:120])}")
        content = content.replace(old, new, 1)
    with open(path, "w") as f:
        f.write(content)
    print(f"  Patched {path}")


def modify_tokens():
    """Add While, Break, Continue token types and keywords."""
    print("1. Modifying token/token.go ...")
    patch_file("/app/token/token.go", [
        # Add token type constants after Return
        (
            '\tReturn   = "RETURN"\n)',
            '\tReturn   = "RETURN"\n'
            '\tWhile    = "WHILE"\n'
            '\tBreak    = "BREAK"\n'
            '\tContinue = "CONTINUE"\n)'
        ),
        # Add entries to the keywords map
        (
            '\t"return": Return,\n}',
            '\t"return":   Return,\n'
            '\t"while":    While,\n'
            '\t"break":    Break,\n'
            '\t"continue": Continue,\n}'
        ),
    ])


def create_ast_nodes():
    """Create ast/while.go with WhileExpression, BreakStatement, ContinueStatement."""
    print("2. Creating ast/while.go ...")
    path = "/app/ast/while.go"
    with open(path, "w") as f:
        f.write('''\
package ast

import (
\t"bytes"

\t"github.com/bradford-hamilton/monkey-lang/token"
)

// WhileExpression represents: while (<condition>) { <body> }
type WhileExpression struct {
\tToken     token.Token // The 'while' token
\tCondition Expression
\tBody      *BlockStatement
}

func (we *WhileExpression) expressionNode()      {}
func (we *WhileExpression) TokenLiteral() string  { return we.Token.Literal }
func (we *WhileExpression) String() string {
\tvar out bytes.Buffer
\tout.WriteString("while(")
\tout.WriteString(we.Condition.String())
\tout.WriteString(")")
\tout.WriteString(we.Body.String())
\treturn out.String()
}

// BreakStatement represents: break;
type BreakStatement struct {
\tToken token.Token
}

func (bs *BreakStatement) statementNode()       {}
func (bs *BreakStatement) TokenLiteral() string  { return bs.Token.Literal }
func (bs *BreakStatement) String() string        { return "break" }

// ContinueStatement represents: continue;
type ContinueStatement struct {
\tToken token.Token
}

func (cs *ContinueStatement) statementNode()       {}
func (cs *ContinueStatement) TokenLiteral() string  { return cs.Token.Literal }
func (cs *ContinueStatement) String() string        { return "continue" }
''')
    print(f"  Created {path}")


def modify_parser():
    """Add while/break/continue parsing to the parser."""
    print("3. Modifying parser/parser.go ...")

    # First: add prefix registration for while and statement cases for break/continue
    patch_file("/app/parser/parser.go", [
        # Register while as a prefix expression parser (after LeftBrace/hash)
        (
            '\tp.registerPrefix(token.LeftBrace, p.parseHashLiteral)\n',
            '\tp.registerPrefix(token.LeftBrace, p.parseHashLiteral)\n'
            '\tp.registerPrefix(token.While, p.parseWhileExpression)\n'
        ),
        # Add break/continue as statement types (before default case)
        (
            '\tcase token.Return:\n\t\treturn p.parseReturnStatement()\n\tdefault:',
            '\tcase token.Return:\n\t\treturn p.parseReturnStatement()\n'
            '\tcase token.Break:\n\t\treturn p.parseBreakStatement()\n'
            '\tcase token.Continue:\n\t\treturn p.parseContinueStatement()\n'
            '\tdefault:'
        ),
    ])

    # Append the parsing method implementations
    with open("/app/parser/parser.go", "a") as f:
        f.write('''
func (p *Parser) parseWhileExpression() ast.Expression {
\texpr := &ast.WhileExpression{Token: p.currentToken}

\tif !p.expectPeekType(token.LeftParen) {
\t\treturn nil
\t}

\tp.nextToken()
\texpr.Condition = p.parseExpr(Lowest)

\tif !p.expectPeekType(token.RightParen) {
\t\treturn nil
\t}

\tif !p.expectPeekType(token.LeftBrace) {
\t\treturn nil
\t}

\texpr.Body = p.parseBlockStatement()

\treturn expr
}

func (p *Parser) parseBreakStatement() *ast.BreakStatement {
\tstmt := &ast.BreakStatement{Token: p.currentToken}
\tif p.peekTokenTypeIs(token.Semicolon) {
\t\tp.nextToken()
\t}
\treturn stmt
}

func (p *Parser) parseContinueStatement() *ast.ContinueStatement {
\tstmt := &ast.ContinueStatement{Token: p.currentToken}
\tif p.peekTokenTypeIs(token.Semicolon) {
\t\tp.nextToken()
\t}
\treturn stmt
}
''')
    print("  Appended parser methods")


def modify_compiler():
    """Add while/break/continue compilation with loop context tracking."""
    print("4. Modifying compiler/compiler.go ...")
    patch_file("/app/compiler/compiler.go", [
        # 1. Add loopContext type before CompilationScope
        (
            '// CompilationScope -',
            '// loopContext tracks loop state during compilation for break/continue back-patching\n'
            'type loopContext struct {\n'
            '\tcontinueTarget int   // bytecode position to jump to for continue\n'
            '\tbreakPositions []int // bytecode positions of break jumps to back-patch\n'
            '}\n\n'
            '// CompilationScope -'
        ),
        # 2. Add loops field to Compiler struct
        (
            '\tscopeIndex  int\n}',
            '\tscopeIndex  int\n'
            '\tloops       []loopContext\n}'
        ),
        # 3. Initialize loops slice in New()
        (
            '\t\tscopeIndex:  0,\n\t}',
            '\t\tscopeIndex:  0,\n'
            '\t\tloops:       []loopContext{},\n\t}'
        ),
        # 4. Add WhileExpression/BreakStatement/ContinueStatement cases in Compile()
        #    Insert before the CallExpression case
        (
            '\tcase *ast.CallExpression:',
            '\tcase *ast.WhileExpression:\n'
            '\t\t// Record loop start position (target for continue and backward jump)\n'
            '\t\tloopStart := len(c.currentInstructions())\n'
            '\t\tc.loops = append(c.loops, loopContext{continueTarget: loopStart})\n'
            '\n'
            '\t\t// Compile the loop condition\n'
            '\t\terr := c.Compile(node.Condition)\n'
            '\t\tif err != nil {\n'
            '\t\t\treturn err\n'
            '\t\t}\n'
            '\n'
            '\t\t// Jump past the loop body if condition is false (back-patch later)\n'
            '\t\texitJump := c.emit(code.OpJumpNotTruthy, 9999)\n'
            '\n'
            '\t\t// Compile the loop body\n'
            '\t\terr = c.Compile(node.Body)\n'
            '\t\tif err != nil {\n'
            '\t\t\treturn err\n'
            '\t\t}\n'
            '\n'
            '\t\t// Jump back to the condition check\n'
            '\t\tc.emit(code.OpJump, loopStart)\n'
            '\n'
            '\t\t// Back-patch the condition exit jump to here\n'
            '\t\tafterLoop := len(c.currentInstructions())\n'
            '\t\tc.changeOperand(exitJump, afterLoop)\n'
            '\n'
            '\t\t// While expression evaluates to Null\n'
            '\t\tc.emit(code.OpNull)\n'
            '\n'
            '\t\t// Back-patch all break jumps to afterLoop (before the OpNull)\n'
            '\t\tloop := c.loops[len(c.loops)-1]\n'
            '\t\tfor _, pos := range loop.breakPositions {\n'
            '\t\t\tc.changeOperand(pos, afterLoop)\n'
            '\t\t}\n'
            '\n'
            '\t\t// Pop loop context\n'
            '\t\tc.loops = c.loops[:len(c.loops)-1]\n'
            '\n'
            '\tcase *ast.BreakStatement:\n'
            '\t\tif len(c.loops) == 0 {\n'
            '\t\t\treturn fmt.Errorf("break outside of loop")\n'
            '\t\t}\n'
            '\t\tpos := c.emit(code.OpJump, 9999)\n'
            '\t\tc.loops[len(c.loops)-1].breakPositions = append(\n'
            '\t\t\tc.loops[len(c.loops)-1].breakPositions, pos,\n'
            '\t\t)\n'
            '\n'
            '\tcase *ast.ContinueStatement:\n'
            '\t\tif len(c.loops) == 0 {\n'
            '\t\t\treturn fmt.Errorf("continue outside of loop")\n'
            '\t\t}\n'
            '\t\tc.emit(code.OpJump, c.loops[len(c.loops)-1].continueTarget)\n'
            '\n'
            '\tcase *ast.CallExpression:'
        ),
    ])


def fix_vm_postfix():
    """Fix two bugs in the VM's executePostfixOperator.

    Bug 1 — In-place Integer mutation corrupts the constant pool:
    The original code does operand.(*object.Integer).Value++ which mutates
    the Integer object in place. Since globals/locals initially point to
    constant pool entries (from OpConstant), the constant is also modified.
    When 'let x = 0' is inside a loop, re-executing it pushes the (now
    corrupted) constant — so x starts at the previously incremented value
    instead of 0. This causes infinite loops when a break condition depends
    on the re-initialized counter.
    Fix: create a new *object.Integer with the computed value.

    Bug 2 — Wrong bytecode offsets for reading variable indices:
    The original code reads from ins[ip-5:] for globals and ins[ip-3:] for
    locals. The actual operands are at ins[ip-2:] (globals, 2-byte uint16)
    and ins[ip-1:] (locals, 1-byte uint8). The original offsets happened to
    read the correct value by coincidence in non-loop contexts (the preceding
    instruction was always OpSetGlobal/OpSetLocal with the same operand).
    Inside while loops, the preceding instruction is OpJumpNotTruthy or
    OpJump, so the wrong bytes are read.
    """
    print("5. Fixing vm/vm.go postfix operator ...")
    patch_file("/app/vm/vm.go", [
        # Fix 1: Create new Integer instead of mutating in-place
        (
            '\tif op == code.OpPlusPlus {\n'
            '\t\toperand.(*object.Integer).Value++\n'
            '\t} else {\n'
            '\t\toperand.(*object.Integer).Value--\n'
            '\t}',
            '\tvar newValue int64\n'
            '\tif op == code.OpPlusPlus {\n'
            '\t\tnewValue = operand.(*object.Integer).Value + 1\n'
            '\t} else {\n'
            '\t\tnewValue = operand.(*object.Integer).Value - 1\n'
            '\t}\n'
            '\toperand = &object.Integer{Value: newValue}'
        ),
        # Fix 2: Correct bytecode offset for reading global variable index
        (
            'globalIndex := code.ReadUint16(ins[ip-5:])',
            'globalIndex := code.ReadUint16(ins[ip-2:])'
        ),
        # Fix 3: Correct bytecode offset for reading local variable index
        (
            'localIndex := code.ReadUint8(ins[ip-3:])',
            'localIndex := code.ReadUint8(ins[ip-1:])'
        ),
    ])


def main():
    print("Implementing while/break/continue in Monkey language compiler+VM\n")
    modify_tokens()
    create_ast_nodes()
    modify_parser()
    modify_compiler()
    fix_vm_postfix()
    print("\nAll modifications applied successfully.")


if __name__ == "__main__":
    main()
