#!/usr/bin/env python3
"""Fix the 5 bugs in the SysY interpreter at /app/sysy_interp."""

with open('/app/sysy_interp') as f:
    code = f.read()

# Bug 1: Integer division uses Python floor division (//) instead of
# C-style truncation toward zero (int(a/b)).
code = code.replace(
    "if op=='/': return lv//rv if rv else 0",
    "if op=='/': return int(lv/rv) if rv else 0"
)

# Bug 2: Modulo uses Python's % (result has sign of divisor) instead of
# C semantics (a % b == a - (a/b)*b, result has sign of dividend).
code = code.replace(
    "if op=='%': return lv%rv if rv else 0",
    "if op=='%': return lv-int(lv/rv)*rv if rv else 0"
)

# Bug 3: Logical AND (&&) evaluates both operands unconditionally instead
# of short-circuiting (not evaluating RHS when LHS is 0).
code = code.replace(
    "if op=='&&':\n"
    "                lv=s._ev(l,env); rv=s._ev(r,env)\n"
    "                return 1 if (lv!=0 and rv!=0) else 0",
    "if op=='&&':\n"
    "                lv=s._ev(l,env)\n"
    "                return 0 if lv==0 else (1 if s._ev(r,env)!=0 else 0)"
)

# Bug 4: Array arguments are shallow-copied via list() when passed to
# functions, breaking pass-by-reference semantics.
code = code.replace(
    "args.append(list(obj) if isinstance(obj,list) else obj)",
    "args.append(obj)"
)

# Bug 5: Block statements don't create a new lexical scope, so variable
# declarations inside { } leak into the enclosing scope.
code = code.replace(
    "def _xblk(s,node,penv):\n"
    "        for it in node[1]: s._xitem(it,penv)",
    "def _xblk(s,node,penv):\n"
    "        env=Env(penv)\n"
    "        for it in node[1]: s._xitem(it,env)"
)

with open('/app/sysy_interp', 'w') as f:
    f.write(code)

print("Applied 5 fixes to /app/sysy_interp")
