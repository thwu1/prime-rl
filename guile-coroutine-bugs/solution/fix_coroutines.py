#!/usr/bin/env python3
"""Apply the five fixes to the broken /app/coroutines.scm module.

Each fix targets a specific bug in the coroutine library:
  1. coroutine-yield: pass yield value to abort-to-prompt
  2. coroutine-resume: handler returns the yielded value instead of *unspecified*
  3. coroutine-send: pass sent value to continuation instead of *unspecified*
  4. run-all: remove dead coroutines from active queue
  5. coroutine-fluid-set!: store assq-set! result back into the record

"""

import sys

with open("/app/coroutines.scm", "r") as f:
    code = f.read()

original = code

# ---- Fix 1: coroutine-yield must pass val to abort-to-prompt ----
# Broken:  (abort-to-prompt tag))))
# Fixed:   (abort-to-prompt tag val))))
code = code.replace(
    "      (abort-to-prompt tag))))",
    "      (abort-to-prompt tag val))))",
)

# ---- Fix 2: coroutine-resume handler must return yielded value ----
# Broken:  handler returns *unspecified*
# Fixed:   handler returns (if (pair? rest) (car rest) *unspecified*)
# The (if ...) wrapper adds one nesting level, so we need one extra closing paren.
code = code.replace(
    "            ;; Return value from the handler — should be the yielded value\n"
    "            *unspecified*)))))\n",
    "            (if (pair? rest) (car rest) *unspecified*))))))\n",
)

# ---- Fix 3: coroutine-send must pass value to continuation ----
# Broken:  (cont *unspecified*)
# Fixed:   (cont value)
# We target the specific line in coroutine-send with its comment
code = code.replace(
    "            ;; Resume with the sent value — the continuation receives it\n"
    "            (cont *unspecified*))",
    "            (cont value))",
)

# ---- Fix 4: run-all must not re-append dead coroutines ----
# Broken:  always appends co back and conditionally adds to results
# Fixed:   branch on dead? to either drop co or re-append it
code = code.replace(
    "          ;; Rotate the coroutine back into the queue regardless of state\n"
    "          (loop (append rest (list co))\n"
    "                (if (coroutine-dead? co)\n"
    "                    (cons (coroutine-result co) results)\n"
    "                    results))))))",
    "          (if (coroutine-dead? co)\n"
    "              (loop rest (cons (coroutine-result co) results))\n"
    "              (loop (append rest (list co)) results))))))",
)

# ---- Fix 5: coroutine-fluid-set! must update the record ----
# Broken:  calls assq-set! but doesn't store result back
# Fixed:   wraps in set-coroutine-fluid-store!
code = code.replace(
    "      ;; NOTE: assq-set! returns a (possibly new) list, but the result\n"
    "      ;; is not stored back into the record.\n"
    "      (assq-set! (coroutine-fluid-store co) cf val))))",
    "      (set-coroutine-fluid-store! co\n"
    "        (assq-set! (coroutine-fluid-store co) cf val)))))",
)

if code == original:
    print("WARNING: No changes were applied — the broken code may have changed.", file=sys.stderr)
    sys.exit(1)

with open("/app/coroutines.scm", "w") as f:
    f.write(code)

print("All 5 fixes applied successfully.")
