#!/usr/bin/env python3
"""
Programmatically identifies and fixes the five bugs in the Lox interpreter.

Bug 1 (parser.py):   For-loop increment is placed before body instead of after.
Bug 2 (interpreter.py): Super/this environment distances are swapped.
Bug 3 (interpreter.py): AND operator truthiness check is inverted.
Bug 4 (callable.py): ReturnException handler in LoxFunction.call doesn't check
                      is_initializer, so return; inside init() yields None
                      instead of this.
Bug 5 (interpreter.py): After defining a class with a superclass the interpreter
                         environment is not restored, corrupting subsequent scope.
"""

import re


def fix_file(path, replacements):
    with open(path, "r") as f:
        content = f.read()
    for old, new in replacements:
        if old not in content:
            raise RuntimeError(
                f"Pattern not found in {path}:\n  {old!r}"
            )
        content = content.replace(old, new, 1)
    with open(path, "w") as f:
        f.write(content)
    return path


# ── Bug 1: for-loop desugaring (parser.py) ──
# Increment must execute AFTER the body, not before.
fix_file(
    "/app/lox/parser.py",
    [
        (
            "body = BlockStmt([ExpressionStmt(increment), body])",
            "body = BlockStmt([body, ExpressionStmt(increment)])",
        )
    ],
)

# ── Bug 2: super/this distance swap (interpreter.py) ──
# super lives at `distance`, this at `distance - 1`.
fix_file(
    "/app/lox/interpreter.py",
    [
        (
            'superclass = self.environment.get_at(distance - 1, "super")\n'
            '            obj = self.environment.get_at(distance, "this")',
            'superclass = self.environment.get_at(distance, "super")\n'
            '            obj = self.environment.get_at(distance - 1, "this")',
        ),
    ],
)

# ── Bug 3: AND short-circuit inverted (interpreter.py) ──
# AND should return left when left is FALSEY, not when it's truthy.
fix_file(
    "/app/lox/interpreter.py",
    [
        (
            "elif expr.operator.ttype == TokenType.AND:\n"
            "                if self.is_truthy(left):\n"
            "                    return left",
            "elif expr.operator.ttype == TokenType.AND:\n"
            "                if not self.is_truthy(left):\n"
            "                    return left",
        ),
    ],
)

# ── Bug 4: init return doesn't return this (callable.py) ──
# When a ReturnException is caught inside an initializer, return this.
fix_file(
    "/app/lox/callable.py",
    [
        (
            "        except ReturnException as ret:\n"
            "            return ret.value",
            "        except ReturnException as ret:\n"
            "            if self.is_initializer:\n"
            "                return self.closure.get_at(0, \"this\")\n"
            "            return ret.value",
        ),
    ],
)

# ── Bug 5: missing environment restore after subclass (interpreter.py) ──
# After creating methods with the super-scope environment, pop back.
fix_file(
    "/app/lox/interpreter.py",
    [
        (
            "            klass = LoxClass(stmt.name.lexeme, superclass, methods)\n"
            "\n"
            "            self.environment.assign(stmt.name, klass)",
            "            klass = LoxClass(stmt.name.lexeme, superclass, methods)\n"
            "\n"
            "            if superclass is not None:\n"
            "                self.environment = self.environment.enclosing\n"
            "\n"
            "            self.environment.assign(stmt.name, klass)",
        ),
    ],
)

print("All 5 bugs fixed successfully.")
