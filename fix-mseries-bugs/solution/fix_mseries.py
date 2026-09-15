#!/usr/bin/env python3
"""
Apply all fixes to /app/mseries.R: fix 4 correctness defects and
implement the complete resample() function.

"""
import re
import sys

with open("/app/mseries.R") as f:
    code = f.read()

changes = 0

# -----------------------------------------------------------------------
# Fix 1: window_aggregate – rightmost.closed must be TRUE so that the
# observation at t_max (which falls on a break) is assigned to the last
# window instead of being silently dropped.
# -----------------------------------------------------------------------
if "rightmost.closed = FALSE" in code:
    code = code.replace("rightmost.closed = FALSE", "rightmost.closed = TRUE")
    changes += 1
    print("Fix 1: window_aggregate boundary (rightmost.closed = TRUE)")

# -----------------------------------------------------------------------
# Fix 2: deduplicate – sprintf must use enough precision to distinguish
# timestamps that differ at the 14th significant digit or at sub-ms
# offsets from Unix epoch values (~1.7e9).
# -----------------------------------------------------------------------
if 'sprintf("%.10g"' in code:
    code = code.replace('sprintf("%.10g"', 'sprintf("%.17g"')
    changes += 1
    print("Fix 2: deduplicate precision (%.17g)")

# -----------------------------------------------------------------------
# Fix 3: nearest_merge – the original only checks the left neighbour
# from findInterval; it must compare BOTH left and right neighbours
# and pick the one with smaller absolute distance.
# -----------------------------------------------------------------------
nn_pattern = (
    r'  idx <- pmax\(idx, 1L\)\s*\n'
    r'  idx <- pmin\(idx, n_ref\)\s*\n'
    r'\s*\n'
    r'  dist <- abs\(x\$timestamps - ref\$timestamps\[idx\]\)\s*\n'
    r'  matched_vals <- ref\$values\[idx\]'
)
nn_replacement = (
    "  idx_left  <- pmax(idx, 1L)\n"
    "  idx_right <- pmin(idx + 1L, n_ref)\n"
    "\n"
    "  dist_left  <- abs(x$timestamps - ref$timestamps[idx_left])\n"
    "  dist_right <- abs(x$timestamps - ref$timestamps[idx_right])\n"
    "\n"
    "  use_right <- dist_right < dist_left\n"
    "  idx  <- ifelse(use_right, idx_right, idx_left)\n"
    "  dist <- ifelse(use_right, dist_right, dist_left)\n"
    "  matched_vals <- ref$values[idx]"
)
if re.search(nn_pattern, code):
    code = re.sub(nn_pattern, nn_replacement, code)
    changes += 1
    print("Fix 3: nearest_merge bilateral search")

# -----------------------------------------------------------------------
# Fix 4: diff_series – timestamps and labels must come from the LATER
# positions (drop+1 .. n), not the earlier positions (1 .. m).
# -----------------------------------------------------------------------
if "x$timestamps[seq_len(m)]" in code:
    code = code.replace(
        "dt <- x$timestamps[seq_len(m)]",
        "dt <- x$timestamps[(drop + 1L):n]",
    )
    code = code.replace(
        "dl <- if (!is.null(x$labels)) x$labels[seq_len(m)] else NULL",
        "dl <- if (!is.null(x$labels)) x$labels[(drop + 1L):n] else NULL",
    )
    changes += 1
    print("Fix 4: diff_series timestamp alignment (later positions)")

# -----------------------------------------------------------------------
# Fix 5: Replace the incomplete resample() with a full implementation
# supporting linear, nearest, and locf methods with max_gap and labels.
# Uses regex to locate the function reliably regardless of whitespace.
# -----------------------------------------------------------------------
RESAMPLE_IMPL = '''\
resample <- function(x, target_times, method = c("linear", "nearest", "locf"), max_gap = Inf) {
  method <- match.arg(method)
  stopifnot(inherits(x, "mseries"), is.numeric(target_times))
  target_times <- sort(as.double(target_times))

  n <- length(x)
  m <- length(target_times)

  if (m == 0L) return(mseries(numeric(0), numeric(0)))
  if (n == 0L) return(mseries(target_times, rep(NA_real_, m)))

  vals <- rep(NA_real_, m)
  has_labels <- !is.null(x$labels)
  labs <- if (has_labels) rep(NA_character_, m) else NULL

  if (method == "linear") {
    if (n < 2L) stop("Need >= 2 observations for linear interpolation")
    interp <- approx(x$timestamps, x$values, xout = target_times,
                      rule = 1, ties = mean)
    vals <- interp$y
    # Enforce max_gap: NA when either bracketing observation is too far away
    if (is.finite(max_gap)) {
      idx_mg <- findInterval(target_times, x$timestamps)
      for (j in seq_len(m)) {
        if (is.na(vals[j])) next
        il <- idx_mg[j]
        ir <- il + 1L
        # If target is at or beyond last obs and not NA, it is exact
        if (ir > n) next
        if (il < 1L) next
        if (abs(target_times[j] - x$timestamps[il]) > max_gap ||
            abs(target_times[j] - x$timestamps[ir]) > max_gap) {
          vals[j] <- NA_real_
        }
      }
    }
    # Labels remain NA for linear interpolation

  } else if (method == "nearest") {
    # For each target, compare left and right neighbours
    idx_nn <- findInterval(target_times, x$timestamps)
    for (j in seq_len(m)) {
      il <- max(idx_nn[j], 1L)
      ir <- min(idx_nn[j] + 1L, n)
      dl <- abs(target_times[j] - x$timestamps[il])
      dr <- abs(target_times[j] - x$timestamps[ir])
      if (dr < dl) {
        best <- ir; best_d <- dr
      } else {
        best <- il; best_d <- dl
      }
      if (best_d <= max_gap) {
        vals[j] <- x$values[best]
        if (has_labels) labs[j] <- x$labels[best]
      }
    }

  } else {
    # locf: last observation carried forward
    idx_lf <- findInterval(target_times, x$timestamps)
    for (j in seq_len(m)) {
      if (idx_lf[j] < 1L) next
      d <- target_times[j] - x$timestamps[idx_lf[j]]
      if (d <= max_gap) {
        vals[j] <- x$values[idx_lf[j]]
        if (has_labels) labs[j] <- x$labels[idx_lf[j]]
      }
    }
  }

  mseries(target_times, vals, labs)
}'''

# Match from "resample <- function(" to the first unindented closing brace
resample_pat = r'resample <- function\(.*?\n\}'
match = re.search(resample_pat, code, flags=re.DOTALL)
if match:
    code = code[:match.start()] + RESAMPLE_IMPL + code[match.end():]
    changes += 1
    print("Fix 5: resample() complete implementation (linear/nearest/locf)")
else:
    print("ERROR: Could not locate resample function", file=sys.stderr)
    sys.exit(1)

# -----------------------------------------------------------------------
# Verify all fixes were applied
# -----------------------------------------------------------------------
assert "rightmost.closed = TRUE" in code, "Verification failed: Fix 1"
assert '%.17g' in code, "Verification failed: Fix 2"
assert "idx_left" in code, "Verification failed: Fix 3"
assert "(drop + 1L):n" in code, "Verification failed: Fix 4"
assert "idx_lf" in code, "Verification failed: Fix 5 (locf)"
assert "best_d <= max_gap" in code, "Verification failed: Fix 5 (nearest)"
assert 'method == "nearest"' in code, "Verification failed: Fix 5 (nearest branch)"

with open("/app/mseries.R", "w") as f:
    f.write(code)

print(f"\nAll {changes} fixes applied successfully to /app/mseries.R")
