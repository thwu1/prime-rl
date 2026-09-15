"""
Fix the three semantic bugs in /app/effekt.py's _handle method:

1. SHALLOW HANDLERS: resume must re-install the handler around the
   continuation (deep handler semantics).
2. EFFECT PROPAGATION: unmatched effects must preserve the handler in
   their continuation so later effects in the same body are still caught.
3. RETURN CLAUSE: when the body completes naturally (Pure), the return
   clause must be applied to transform the value.

"""

import re

filepath = "/app/effekt.py"

with open(filepath, "r") as f:
    source = f.read()

# ---- Bug 1: shallow -> deep handler ----
# The resume function currently just calls k(value).
# It must instead call self._handle(k(value), ...) to reinstall the handler.
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

# ---- Bug 2: propagation must preserve handler ----
# Currently: Step(comp.effect, comp.args, comp.cont)
# Fix:       Step(comp.effect, comp.args, lambda v: self._handle(comp.cont(v), ...))
source = source.replace(
    "            # effect not handled here -- propagate\n"
    "            return Step(comp.effect, comp.args, comp.cont)",

    "            # effect not handled here -- propagate with handler preserved\n"
    "            return Step(comp.effect, comp.args,\n"
    "                        lambda v, _k=comp.cont, _hc=handler_clauses,\n"
    "                               _he=handler_env, _rc=return_clause:\n"
    "                            self._handle(_k(v), _hc, _he, _rc))",
)

# ---- Bug 3: return clause not applied ----
# Currently: Pure branch returns Pure(comp.value) unconditionally.
# Fix:       check return_clause and evaluate its body when present.
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

with open(filepath, "w") as f:
    f.write(source)

print("Applied all three fixes to _handle method.")
