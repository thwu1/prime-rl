"""
Apply all fixes to the Mini Effekt project.

"""

import sys

# ================================================================
# Fix 1: Test runner -- expose exception details
# ================================================================
filepath = "/app/run_all.py"
with open(filepath, "r") as f:
    source = f.read()

source = source.replace(
    "    try:\n"
    "        return interp.run(prog)\n"
    "    except Exception:\n"
    "        return None, []",

    "    try:\n"
    "        return interp.run(prog)\n"
    "    except Exception as e:\n"
    "        print(f\"    ERROR: {type(e).__name__}: {e}\")\n"
    "        return None, []",
)

with open(filepath, "w") as f:
    f.write(source)
print("Fixed run_all.py: exception details now reported")

# ================================================================
# Fix 2-5: Interpreter -- handler bugs + LetRec implementation
# ================================================================
filepath = "/app/effekt.py"
with open(filepath, "r") as f:
    source = f.read()

# --- Bug fix: shallow -> deep handler ---
# resume must re-install the handler around the resumed continuation
source = source.replace(
    "                    def _make_resume(k):\n"
    "                        def _resume(value):\n"
    "                            return k(value)\n"
    "                        return _resume",

    "                    def _make_resume(k, _hc=handler_clauses,\n"
    "                                     _he=handler_env, _rc=return_clause):\n"
    "                        def _resume(value):\n"
    "                            return self._handle(k(value), _hc, _he, _rc)\n"
    "                        return _resume",
)

# --- Bug fix: propagation must preserve handler context ---
# When an effect is not handled here, the continuation must still
# be wrapped so the current handler stays active for later effects
source = source.replace(
    "            # effect not handled here -- propagate\n"
    "            return Step(comp.effect, comp.args, comp.cont)",

    "            # effect not handled here -- propagate with handler preserved\n"
    "            return Step(comp.effect, comp.args,\n"
    "                        lambda v, _k=comp.cont, _hc=handler_clauses,\n"
    "                               _he=handler_env, _rc=return_clause:\n"
    "                            self._handle(_k(v), _hc, _he, _rc))",
)

# --- Bug fix: return clause not applied in Pure branch ---
source = source.replace(
    "        if isinstance(comp, Pure):\n"
    "            return Pure(comp.value)\n",

    "        if isinstance(comp, Pure):\n"
    "            if return_clause is not None:\n"
    "                ret_env = dict(handler_env)\n"
    "                ret_env[return_clause.param] = comp.value\n"
    "                return self.evaluate(return_clause.body, ret_env)\n"
    "            return Pure(comp.value)\n",
)

# --- Implement LetRec ---
# Create a closure and inject self-reference for recursion
source = source.replace(
    "        elif isinstance(expr, LetRec):\n"
    "            # TODO: implement recursive function binding\n"
    "            raise NotImplementedError(\"LetRec evaluation not implemented\")",

    "        elif isinstance(expr, LetRec):\n"
    "            closure = Closure(expr.func.params, expr.func.body, dict(env))\n"
    "            closure.env[expr.name] = closure\n"
    "            new_env = dict(env)\n"
    "            new_env[expr.name] = closure\n"
    "            return self.evaluate(expr.body, new_env)",
)

with open(filepath, "w") as f:
    f.write(source)
print("Fixed effekt.py: handler bugs + LetRec implemented")

# ================================================================
# Fix 6: Correct wrong expected value in resume_return.py
# ================================================================
filepath = "/app/programs/resume_return.py"
with open(filepath, "r") as f:
    source = f.read()

# The return clause computes x*2+1 where x=21, giving 43 (not 42)
source = source.replace(
    "    return prog, 42, []",
    "    return prog, 43, []",
)

with open(filepath, "w") as f:
    f.write(source)
print("Fixed resume_return.py: expected value corrected to 43")

print("\nAll fixes applied successfully.")
