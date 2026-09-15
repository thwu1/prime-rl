# compensation.R — Spillover Matrix Compensation
#
# Parses the $SPILLOVER keyword from FCS metadata and applies
# spectral compensation to fluorescence channels.
#

#' Parse a spillover matrix from the $SPILLOVER keyword value
#'
#' FCS standard format: "n,ch1,ch2,...,chN,m11,m12,...,m1N,m21,...,mNN"
#' where n is the number of channels and mij are matrix entries
#' stored sequentially.
#'
#' @param spillover_string Character string from the $SPILLOVER keyword
#' @return A list with components:
#'   - matrix: n x n numeric spillover matrix
#'   - channels: character vector of channel names
parse_spillover <- function(spillover_string) {
  parts <- strsplit(spillover_string, ",")[[1]]
  n <- as.integer(parts[1])

  if (n <= 0 || length(parts) < n + 1 + n * n) {
    stop("Invalid $SPILLOVER keyword format")
  }

  channels <- trimws(parts[2:(n + 1)])
  values   <- as.numeric(parts[(n + 2):length(parts)])

  if (length(values) != n * n) {
    stop("Spillover matrix value count mismatch: expected ",
         n * n, ", got ", length(values))
  }

  # Construct the spillover matrix from the sequential values
  mat <- matrix(values, nrow = n, ncol = n)
  colnames(mat) <- channels
  rownames(mat) <- channels

  list(matrix = mat, channels = channels)
}

#' Apply spillover compensation to expression data
#'
#' Compensation removes spectral overlap between fluorescence channels.
#' Given raw fluorescence measurements F and spillover matrix S,
#' the compensated values are computed from the relationship between
#' measured and true fluorescence.
#'
#' @param exprs   Numeric matrix (events x parameters)
#' @param spillover_matrix  The n x n spillover matrix
#' @param channels Character vector of fluorescence channel names
#' @return Compensated expression matrix (same dimensions as input)
compensate_data <- function(exprs, spillover_matrix, channels) {
  # Validate that all channels exist in the expression matrix
  missing <- setdiff(channels, colnames(exprs))
  if (length(missing) > 0) {
    stop("Channels not found in data: ", paste(missing, collapse = ", "))
  }

  # Extract fluorescence columns for compensation
  fl_data <- exprs[, channels, drop = FALSE]

  # Apply compensation transformation
  compensated <- fl_data %*% spillover_matrix

  # Replace fluorescence columns with compensated values
  result <- exprs
  result[, channels] <- compensated

  result
}
