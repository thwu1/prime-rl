# pipeline.R — Flow Cytometry Analysis Pipeline
#
# Orchestrates the full analysis: FCS parsing -> compensation ->
# logicle transform -> gating -> output.
#
# Usage: Rscript pipeline.R <input.fcs> <output_dir>
#

source("/app/fcs_parser.R")
source("/app/compensation.R")
source("/app/transforms.R")
source("/app/gating.R")

# ---- Minimal JSON serializer (no external dependencies) -------------------

to_json <- function(x, indent = 0) {
  pad  <- paste(rep("  ", indent), collapse = "")
  pad1 <- paste(rep("  ", indent + 1), collapse = "")

  if (is.list(x) && !is.null(names(x))) {
    if (length(x) == 0) return("{}")
    items <- vapply(names(x), function(key) {
      paste0(pad1, '"', key, '": ', to_json(x[[key]], indent + 1))
    }, character(1))
    paste0("{\n", paste(items, collapse = ",\n"), "\n", pad, "}")
  } else if (is.numeric(x) && length(x) == 1) {
    if (is.na(x)) "null"
    else if (is.infinite(x)) paste0('"', as.character(x), '"')
    else formatC(x, digits = 10, format = "g")
  } else if (is.integer(x) && length(x) == 1) {
    as.character(x)
  } else if (is.logical(x) && length(x) == 1) {
    tolower(as.character(x))
  } else if (is.character(x) && length(x) == 1) {
    paste0('"', gsub('"', '\\\\"', x, fixed = TRUE), '"')
  } else if (is.numeric(x) || is.integer(x)) {
    paste0("[", paste(formatC(x, digits = 10, format = "g"),
                      collapse = ", "), "]")
  } else {
    paste0('"', as.character(x), '"')
  }
}

# ---- Main pipeline --------------------------------------------------------

main <- function() {
  args <- commandArgs(trailingOnly = TRUE)
  if (length(args) != 2) {
    stop("Usage: Rscript pipeline.R <input.fcs> <output_dir>")
  }

  input_fcs  <- args[1]
  output_dir <- args[2]
  dir.create(output_dir, showWarnings = FALSE, recursive = TRUE)

  # ---- Step 1: Parse FCS file ----
  cat("Parsing FCS file:", input_fcs, "\n")
  fcs <- parse_fcs(input_fcs)

  write.csv(fcs$exprs,
            file.path(output_dir, "parsed_data.csv"),
            row.names = FALSE)

  # ---- Step 2: Spillover Compensation ----
  cat("Applying compensation...\n")
  spillover_str <- fcs$keywords[["$SPILLOVER"]]
  if (is.null(spillover_str)) {
    spillover_str <- fcs$keywords[["SPILLOVER"]]
  }

  if (!is.null(spillover_str)) {
    spill <- parse_spillover(spillover_str)
    compensated <- compensate_data(fcs$exprs, spill$matrix, spill$channels)
  } else {
    cat("No spillover matrix found, skipping compensation\n")
    compensated <- fcs$exprs
  }

  write.csv(compensated,
            file.path(output_dir, "compensated_data.csv"),
            row.names = FALSE)

  # ---- Step 3: Logicle Transform ----
  cat("Applying logicle transform...\n")
  fl_channels <- grep("^FL\\d+-", colnames(compensated), value = TRUE)

  transformed <- compensated
  for (ch in fl_channels) {
    transformed[, ch] <- logicle_transform(
      compensated[, ch],
      T_ = 262144, W = 0.5, M = 4.5, A = 0
    )
  }

  write.csv(transformed,
            file.path(output_dir, "transformed_data.csv"),
            row.names = FALSE)

  # ---- Step 4: Rectangle Gating ----
  cat("Applying gates...\n")

  # Gate 1: Lymphocyte scatter gate
  lymph_gate_def <- list(
    "FSC-H" = c(200, 800),
    "SSC-H" = c(50, 500)
  )
  in_lymph <- rectangle_gate(transformed, lymph_gate_def)

  # Gate 2: Fluorescence positivity gate (logicle scale)
  fl_gate_def <- list(
    "FL1-H" = c(2.0, 4.5),
    "FL2-H" = c(1.5, 4.5)
  )
  in_fl <- rectangle_gate(transformed, fl_gate_def)

  # Gate 3: Combined (intersection)
  in_combined <- in_lymph & in_fl

  # Compute statistics
  lymph_stats    <- gate_statistics(transformed, in_lymph, colnames(transformed))
  fl_stats       <- gate_statistics(transformed, in_fl, fl_channels)
  combined_stats <- gate_statistics(transformed, in_combined, fl_channels)

  gate_results <- list(
    lymphocyte_gate = list(
      count      = as.integer(lymph_stats$count),
      total      = as.integer(lymph_stats$total),
      percentage = lymph_stats$percentage
    ),
    fluorescence_gate = list(
      count      = as.integer(fl_stats$count),
      total      = as.integer(fl_stats$total),
      percentage = fl_stats$percentage
    ),
    combined_gate = list(
      count      = as.integer(combined_stats$count),
      total      = as.integer(combined_stats$total),
      percentage = combined_stats$percentage
    )
  )

  writeLines(to_json(gate_results),
             file.path(output_dir, "gate_results.json"))

  # ---- Step 5: Summary ----
  summary_data <- list(
    n_events   = as.integer(nrow(fcs$exprs)),
    n_params   = as.integer(ncol(fcs$exprs)),
    param_names = paste(fcs$param_names, collapse = ","),
    fl_channels = paste(fl_channels, collapse = ",")
  )

  writeLines(to_json(summary_data),
             file.path(output_dir, "summary.json"))

  cat("Pipeline complete. Output written to:", output_dir, "\n")
}

main()
