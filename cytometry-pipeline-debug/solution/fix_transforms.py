#!/usr/bin/env python3
"""
Fix the logicle transform defects in transforms.R.

Defect 1: compute_logicle_params has a sign error in the equation for
           parameter d. The term b * (x0 - x1) should be b * (x1 - x0).

Defect 2: logicle_inverse uses a single-step secant approximation instead of
           iterative Newton's method. It also mishandles negative input values
           (maps them all to y=0) and clamps the output to [0, 1] which
           discards the linearization region mapping for near-zero/negative data.
           Must be replaced with proper Newton's method implementation.

"""


def find_function_end(content, func_start):
    """Find the closing brace of an R function definition by counting braces."""
    depth = 0
    for i in range(func_start, len(content)):
        if content[i] == '{':
            depth += 1
        elif content[i] == '}':
            depth -= 1
            if depth == 0:
                return i + 1
    return len(content)


def main():
    with open('/app/transforms.R', 'r') as f:
        content = f.read()

    # ---- Fix 1: Sign error in logicle parameter d equation ----
    # The equation 2*(ln(d) - ln(b)) + b*(x1 - x0) = 0 is correct.
    # Since x1 = x2 + w and x0 = x2 + 2w, we have x1 - x0 = -w (negative).
    # The code incorrectly uses x0 - x1 = +w, giving the wrong d value.
    content = content.replace("b * (x0 - x1)", "b * (x1 - x0)")

    # ---- Fix 2: Replace broken logicle_inverse with Newton's method ----
    # Find the roxygen comment block + function definition
    start_marker = "#' Invert the biexponential function"
    start = content.find(start_marker)
    if start == -1:
        raise ValueError("Could not find logicle_inverse roxygen comments")

    # Find the function definition
    func_def = "logicle_inverse <- function(x, params) {"
    func_start = content.find(func_def, start)
    if func_start == -1:
        raise ValueError("Could not find logicle_inverse function definition")

    # Find the closing brace
    func_end = find_function_end(content, func_start)

    # The correct implementation using Newton's method
    new_func = """#' Invert the biexponential function for a single value
#'
#' Given x, find y such that B(y) = x using Newton's method.
#' Then scale y to the [0, M] display range.
#'
logicle_inverse <- function(x, params) {
  a  <- params$a
  b  <- params$b
  c_ <- params$c
  d  <- params$d
  f  <- params$f
  M  <- params$M

  # Biexponential function B(y) and its derivative B'(y)
  B  <- function(y) a * exp(b * y) - c_ * exp(-d * y) + f
  Bp <- function(y) a * b * exp(b * y) + c_ * d * exp(-d * y)

  # Initial guess based on dominant term
  if (x > 0) {
    y <- max(log(max(x / a, 1e-30)) / b, params$x1)
  } else if (x < 0) {
    y <- min(-log(max(-x / c_, 1e-30)) / d, params$x1)
  } else {
    y <- params$x1
  }

  # Newton iterations
  for (iter in seq_len(100)) {
    By  <- B(y)
    Bpy <- Bp(y)
    if (abs(Bpy) < .Machine$double.eps) break
    delta <- (By - x) / Bpy
    y <- y - delta
    if (abs(delta) < 1e-12) break
  }

  # Scale from [0,1] normalized to [0,M] display range
  y * M
}"""

    content = content[:start] + new_func + content[func_end:]

    with open('/app/transforms.R', 'w') as f:
        f.write(content)

    print("Fixed: sign error in parameter d equation (x0-x1 -> x1-x0)")
    print("Fixed: replaced single-step secant with iterative Newton's method")
    print("  - Added analytical derivative B'(y)")
    print("  - Added proper initial guess for negative and zero values")
    print("  - Added convergence loop with tolerance check")
    print("  - Removed incorrect [0,1] output clamping")


if __name__ == "__main__":
    main()
