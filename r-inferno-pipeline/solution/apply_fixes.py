"""Apply all 9 fixes across the three R source files.

Each fix addresses a distinct R language pitfall documented in
'The R Inferno' by Patrick Burns.  Bugs are distributed across
/app/lib/transforms.R, /app/lib/statistics.R, and /app/pipeline.R.
"""



def fix_file(path, replacements):
    """Apply a list of (old, new) string replacements to a file."""
    with open(path) as f:
        content = f.read()
    for old, new in replacements:
        if old not in content:
            raise ValueError(f"Pattern not found in {path}: {old!r}")
        content = content.replace(old, new, 1)
    with open(path, "w") as f:
        f.write(content)


# ── Fix transforms.R (4 bugs) ──────────────────────────────────

fix_file("/app/lib/transforms.R", [
    # Bug 1: Factor-to-numeric coercion (Circle 8.2.1)
    # as.numeric(factor) gives level indices, not actual values
    (
        "as.numeric(data$concentration)",
        "as.numeric(as.character(data$concentration))",
    ),
    # Bug 2a: NA equality (Circle 8.1.4) — != NA always yields NA
    (
        "data$measurement != NA",
        "!is.na(data$measurement)",
    ),
    # Bug 2b: NA equality — == NA always yields NA
    (
        "data$measurement == NA",
        "is.na(data$measurement)",
    ),
    # Bug 4: which.min returns INDEX not VALUE
    (
        "ref_baselines[j] <- which.min(abs(site_baselines - reference))",
        "ref_baselines[j] <- site_baselines[which.min(abs(site_baselines - reference))]",
    ),
])

# Bug 3: Closure variable capture via lazy evaluation (Circle 8.3.16)
# All closures share the same environment; i holds its final value.
# Fix: use lapply which creates a fresh scope per iteration.
with open("/app/lib/transforms.R") as f:
    content = f.read()

old_closure = """\
  normalizers <- list()
  for (i in seq_along(sites)) {
    normalizers[[i]] <- function(x) x / baselines_by_site[i]
  }
  return(normalizers)"""

new_closure = """\
  normalizers <- lapply(seq_along(sites), function(i) {
    force(i)
    function(x) x / baselines_by_site[i]
  })
  return(normalizers)"""

content = content.replace(old_closure, new_closure)
with open("/app/lib/transforms.R", "w") as f:
    f.write(content)

# ── Fix statistics.R (3 bugs) ──────────────────────────────────

fix_file("/app/lib/statistics.R", [
    # Bug 5: Floating-point comparison (Circle 1)
    # seq(0,1,by=0.1) == 0.3 fails due to IEEE-754 representation
    (
        "w <- weight_seq[weight_seq == target]",
        "w <- weight_seq[which.min(abs(weight_seq - target))]",
    ),
    # Bug 6: mean() multi-argument trap
    # mean(a, b, c) treats b as trim parameter, c as na.rm
    (
        "mean(effects[1], effects[2], effects[3])",
        "mean(c(effects[1], effects[2], effects[3]))",
    ),
])

# Bug 7: apply() transposition (Circle 8.1.47)
# apply(mat, 1, f) returns result columns for each input row
with open("/app/lib/statistics.R") as f:
    content = f.read()

content = content.replace(
    "return(derived)",
    "return(t(derived))",
)

with open("/app/lib/statistics.R", "w") as f:
    f.write(content)

# ── Fix pipeline.R (2 bugs) ────────────────────────────────────

fix_file("/app/pipeline.R", [
    # Bug 8: Vector recycling (Circle 8.1.6)
    # == c("drug","placebo") recycles the short vector
    (
        'data$treatment == c("drug", "placebo")',
        'data$treatment %in% c("drug", "placebo")',
    ),
    # Bug 9: min() vs pmin() (Circle 8.2.22)
    # min(vec, scalar) returns overall minimum, not element-wise
    (
        "capped <- min(site_meas, cap)",
        "capped <- pmin(site_meas, cap)",
    ),
])

# ── Pipeline section 8: replace lapply with explicit for-loop ──
# setNames(lapply(...)) can produce inconsistent jsonlite serialization;
# a direct for-loop populating named list elements is more reliable.
with open("/app/pipeline.R") as f:
    content = f.read()

old_sec8 = """results$robust_means <- setNames(
  lapply(seq_along(sites), function(j) {
    list(
      huber_mean = round(huber_results$estimates[j], 6),
      iterations = as.integer(huber_results$iterations[j])
    )
  }),
  sites
)"""

new_sec8 = """results$robust_means <- list()
for (j in seq_along(sites)) {
  results$robust_means[[sites[j]]] <- list(
    huber_mean = round(huber_results$estimates[j], 6),
    iterations = huber_results$iterations[j]
  )
}"""

content = content.replace(old_sec8, new_sec8)
with open("/app/pipeline.R", "w") as f:
    f.write(content)

print("All 9 fixes applied across 3 R source files")
