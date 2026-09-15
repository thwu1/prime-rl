#!/usr/bin/env Rscript
# mseries.R - Measurement Series Library
# Implements the "mseries" S3 class for time-indexed measurement data
#

# ===========================================================================
# Constructor
# ===========================================================================

mseries <- function(timestamps, values, labels = NULL) {
  stopifnot(
    is.numeric(timestamps),
    is.numeric(values),
    length(timestamps) == length(values)
  )
  if (!is.null(labels)) {
    stopifnot(is.character(labels), length(labels) == length(values))
  }
  ord <- order(timestamps, method = "radix")
  structure(
    list(
      timestamps = as.double(timestamps[ord]),
      values     = as.double(values[ord]),
      labels     = if (!is.null(labels)) labels[ord] else NULL
    ),
    class = "mseries"
  )
}

# ===========================================================================
# Basic S3 methods
# ===========================================================================

print.mseries <- function(x, ...) {
  n <- length(x$timestamps)
  cat(sprintf("mseries [%d observations]\n", n))
  if (n > 0L) {
    tr <- range(x$timestamps)
    vr <- range(x$values, na.rm = TRUE)
    cat(sprintf("  Timestamps : [%.6f, %.6f]\n", tr[1], tr[2]))
    cat(sprintf("  Values     : [%.6g, %.6g]\n", vr[1], vr[2]))
    if (!is.null(x$labels)) {
      ul <- unique(x$labels)
      cat(sprintf("  Labels     : %d unique (%s)\n",
                  length(ul), paste(head(ul, 5), collapse = ", ")))
    }
  }
  invisible(x)
}

format.mseries <- function(x, ...) {
  if (length(x$timestamps) == 0L) return(character(0))
  ts_str  <- formatC(x$timestamps, format = "f", digits = 6)
  val_str <- formatC(x$values, format = "g", digits = 6)
  if (!is.null(x$labels)) {
    paste0("[", ts_str, "] ", val_str, " (", x$labels, ")")
  } else {
    paste0("[", ts_str, "] ", val_str)
  }
}

length.mseries <- function(x) length(x$timestamps)

# ===========================================================================
# Subsetting
# ===========================================================================

"[.mseries" <- function(x, i, ...) {
  mseries(
    x$timestamps[i],
    x$values[i],
    if (!is.null(x$labels)) x$labels[i] else NULL
  )
}

# ===========================================================================
# Combine
# ===========================================================================

c.mseries <- function(...) {
  args <- list(...)
  args <- args[!vapply(args, is.null, logical(1))]
  if (length(args) == 0L) return(mseries(numeric(0), numeric(0)))

  all_ts   <- do.call(c, lapply(args, `[[`, "timestamps"))
  all_vals <- do.call(c, lapply(args, `[[`, "values"))

  has_labels <- any(vapply(args, function(a) !is.null(a$labels), logical(1)))
  all_labs <- NULL
  if (has_labels) {
    all_labs <- do.call(c, lapply(args, function(a) {
      if (is.null(a$labels)) rep(NA_character_, length(a$timestamps))
      else a$labels
    }))
  }
  mseries(all_ts, all_vals, all_labs)
}

# ===========================================================================
# Windowed aggregation
# ===========================================================================

window_aggregate <- function(x, window_width, FUN = mean, ...) {
  stopifnot(inherits(x, "mseries"), is.numeric(window_width), window_width > 0)
  if (length(x) == 0L) return(mseries(numeric(0), numeric(0)))

  t_min <- min(x$timestamps)
  t_max <- max(x$timestamps)

  breaks <- seq(t_min, t_max, by = window_width)
  if (breaks[length(breaks)] < t_max) {
    breaks <- c(breaks, breaks[length(breaks)] + window_width)
  }

  bins <- findInterval(x$timestamps, breaks, rightmost.closed = FALSE)

  valid <- bins >= 1L & bins < length(breaks)
  if (!any(valid)) return(mseries(numeric(0), numeric(0)))

  binf     <- factor(bins[valid], levels = seq_len(length(breaks) - 1L))
  agg_vals <- as.numeric(tapply(x$values[valid], binf, FUN, ...))
  agg_ts   <- as.numeric(tapply(x$timestamps[valid], binf, mean))

  keep <- !is.na(agg_vals)
  mseries(agg_ts[keep], agg_vals[keep])
}

# ===========================================================================
# Deduplication
# ===========================================================================

deduplicate <- function(x, by = c("time", "time_and_label")) {
  by <- match.arg(by)
  stopifnot(inherits(x, "mseries"))
  if (length(x) == 0L) return(x)

  if (by == "time") {
    keys <- sprintf("%.10g", x$timestamps)
  } else {
    lab  <- if (is.null(x$labels)) rep("", length(x$timestamps)) else x$labels
    keys <- paste(sprintf("%.10g", x$timestamps), lab, sep = "|")
  }

  keep <- !duplicated(keys)
  mseries(
    x$timestamps[keep], x$values[keep],
    if (!is.null(x$labels)) x$labels[keep] else NULL
  )
}

# ===========================================================================
# Nearest-neighbor merge
# ===========================================================================

nearest_merge <- function(x, ref, max_gap = Inf) {
  stopifnot(inherits(x, "mseries"), inherits(ref, "mseries"))
  if (length(x) == 0L) {
    return(data.frame(
      timestamp = numeric(0), x_value = numeric(0),
      ref_value = numeric(0), distance = numeric(0)
    ))
  }
  if (length(ref) == 0L) stop("Reference series is empty")

  n_ref <- length(ref)

  idx <- findInterval(x$timestamps, ref$timestamps)
  idx <- pmax(idx, 1L)
  idx <- pmin(idx, n_ref)

  dist <- abs(x$timestamps - ref$timestamps[idx])
  matched_vals <- ref$values[idx]

  matched_vals[dist > max_gap] <- NA_real_
  dist[dist > max_gap]         <- NA_real_

  data.frame(
    timestamp = x$timestamps,
    x_value   = x$values,
    ref_value = matched_vals,
    distance  = dist
  )
}

# ===========================================================================
# Differencing
# ===========================================================================

diff_series <- function(x, lag = 1L, differences = 1L) {
  stopifnot(inherits(x, "mseries"))
  lag <- as.integer(lag)
  differences <- as.integer(differences)
  stopifnot(lag >= 1L, differences >= 1L)

  n    <- length(x)
  drop <- lag * differences
  if (n <= drop) stop("Series too short for requested differencing")

  dv <- diff(x$values, lag = lag, differences = differences)
  m  <- length(dv)

  dt <- x$timestamps[seq_len(m)]
  dl <- if (!is.null(x$labels)) x$labels[seq_len(m)] else NULL

  mseries(dt, dv, dl)
}

# ===========================================================================
# Summary
# ===========================================================================

summary.mseries <- function(object, ...) {
  n <- length(object)
  if (n == 0L) {
    cat("Empty measurement series\n")
    return(invisible(NULL))
  }
  dt <- diff(object$timestamps)
  out <- list(
    n             = n,
    time_range    = range(object$timestamps),
    time_span     = diff(range(object$timestamps)),
    mean_interval = if (n > 1L) mean(dt) else NA_real_,
    value_summary = summary(object$values),
    n_labels      = if (!is.null(object$labels)) length(unique(object$labels)) else 0L
  )
  class(out) <- "mseries_summary"
  out
}

print.mseries_summary <- function(x, ...) {
  cat(sprintf("Measurement series summary (%d observations)\n", x$n))
  cat(sprintf("  Time span      : %.6f units\n", x$time_span))
  cat(sprintf("  Mean interval  : %.6f units\n", x$mean_interval))
  cat("  Values:\n")
  print(x$value_summary)
  if (x$n_labels > 0L) cat(sprintf("  Distinct labels: %d\n", x$n_labels))
  invisible(x)
}

# ===========================================================================
# Time-based subsetting
# ===========================================================================

time_subset <- function(x, from = -Inf, to = Inf) {
  stopifnot(inherits(x, "mseries"))
  mask <- x$timestamps >= from & x$timestamps <= to
  x[mask]
}

# ===========================================================================
# Value transformation
# ===========================================================================

transform_values <- function(x, FUN, ...) {
  stopifnot(inherits(x, "mseries"))
  new_vals <- FUN(x$values, ...)
  stopifnot(is.numeric(new_vals), length(new_vals) == length(x$values))
  mseries(x$timestamps, new_vals, x$labels)
}

# ===========================================================================
# Resampling
# ===========================================================================

resample <- function(x, target_times, method = c("linear", "nearest", "locf"), max_gap = Inf) {
  method <- match.arg(method)
  stopifnot(inherits(x, "mseries"), is.numeric(target_times))
  target_times <- sort(as.double(target_times))

  if (length(x) == 0L) return(mseries(numeric(0), numeric(0)))

  n <- length(x)
  m <- length(target_times)

  if (method == "linear") {
    if (n < 2L) stop("Need >= 2 observations for linear interpolation")
    interp <- approx(x$timestamps, x$values, xout = target_times,
                      rule = 1, ties = mean)
    return(mseries(interp$x, interp$y))
  }

  stop(paste0("Method '", method, "' is not yet implemented"))
}

# ===========================================================================
# Rolling apply
# ===========================================================================

rolling_apply <- function(x, width, FUN = mean, align = "right", ...) {
  stopifnot(inherits(x, "mseries"), is.numeric(width), width >= 1L)
  n <- length(x)
  w <- as.integer(width)
  if (n < w) stop("Series shorter than window width")

  out_vals <- rep(NA_real_, n)
  for (i in w:n) {
    out_vals[i] <- FUN(x$values[(i - w + 1L):i], ...)
  }
  if (align == "right") {
    mseries(x$timestamps, out_vals, x$labels)
  } else {
    keep <- !is.na(out_vals)
    mseries(x$timestamps[keep], out_vals[keep],
            if (!is.null(x$labels)) x$labels[keep] else NULL)
  }
}
