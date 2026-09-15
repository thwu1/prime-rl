# gating.R — Flow Cytometry Gating
#
# Implements rectangle gating and population statistics computation
# for flow cytometry analysis.
#

#' Apply a rectangle gate
#'
#' A rectangle gate selects events whose values fall within specified
#' ranges for one or more channels simultaneously.
#'
#' @param exprs    Numeric matrix (events x parameters)
#' @param gate_def Named list: channel names as keys, each value is
#'                 a length-2 numeric vector c(lower, upper)
#' @return Logical vector: TRUE for events inside the gate
rectangle_gate <- function(exprs, gate_def) {
  in_gate <- rep(TRUE, nrow(exprs))

  for (channel in names(gate_def)) {
    if (!channel %in% colnames(exprs)) {
      stop("Gate channel not found in data: ", channel)
    }
    bounds <- gate_def[[channel]]
    lower  <- bounds[1]
    upper  <- bounds[2]
    values <- exprs[, channel]
    in_gate <- in_gate & (values >= lower) & (values <= upper)
  }

  in_gate
}

#' Compute population statistics for gated events
#'
#' @param exprs    Numeric matrix (events x parameters)
#' @param in_gate  Logical vector from rectangle_gate()
#' @param channels Character vector of channels to summarize
#' @return List with count, total, percentage, and per-channel stats
gate_statistics <- function(exprs, in_gate, channels) {
  total <- nrow(exprs)
  count <- sum(in_gate)
  pct   <- count / total * 100

  gated_data <- exprs[in_gate, , drop = FALSE]

  channel_stats <- list()
  for (ch in channels) {
    if (count > 0) {
      vals <- gated_data[, ch]
      channel_stats[[ch]] <- list(
        mean   = mean(vals),
        median = median(vals),
        sd     = sd(vals),
        min    = min(vals),
        max    = max(vals)
      )
    } else {
      channel_stats[[ch]] <- list(
        mean = NA, median = NA, sd = NA, min = NA, max = NA
      )
    }
  }

  list(
    count         = count,
    total         = total,
    percentage    = pct,
    channel_stats = channel_stats
  )
}
