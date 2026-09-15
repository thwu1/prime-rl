#!/usr/bin/env Rscript
#
# Reproducibility Evaluator — Implementation Beta
# Alternative evaluation of agent results against stochastic ground truth.
#
# Authors: Research Team B
#

library(jsonlite)

args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 3) {
  cat("Usage: Rscript evaluator_beta.R <ground_truth.json> <agent_reports_dir> <output_dir>\n")
  quit(status = 1)
}

gt_path <- args[1]
reports_dir <- args[2]
output_dir <- args[3]
dir.create(output_dir, showWarnings = FALSE, recursive = TRUE)

gt_data <- fromJSON(gt_path, simplifyVector = FALSE)


compute_intervals <- function(gt_results) {
  first <- gt_results[[1]]
  n <- length(gt_results)
  intervals <- list()

  for (key in names(first)) {
    val <- first[[key]]
    if (!is.numeric(val) || length(val) != 1) next

    values <- sapply(gt_results, function(r) r[[key]])
    mean_val <- mean(values)
    std_val <- sd(values)

    if (is.na(std_val) || std_val == 0) {
      intervals[[key]] <- c(mean_val, mean_val)
      next
    }

    # 95th percentile of t-distribution for 95% interval
    t_val <- qt(0.95, n - 1)
    margin <- t_val * std_val * sqrt(1.0 / n)
    intervals[[key]] <- c(mean_val - margin, mean_val + margin)
  }

  return(intervals)
}


coerce_value <- function(val) {
  if (is.numeric(val)) return(val)
  if (is.character(val)) {
    result <- suppressWarnings(as.numeric(trimws(val)))
    if (!is.na(result)) return(result)
    return(val)
  }
  return(val)
}


evaluate_capsule <- function(gt_capsule, reported) {
  gt_results <- gt_capsule$results
  first <- gt_results[[1]]
  intervals <- compute_intervals(gt_results)

  correct_written <- 0
  correct_vision <- 0
  total_written <- 0
  total_vision <- 0

  for (key in names(first)) {
    gt_val <- first[[key]]

    # Vision question if 'fig' substring appears anywhere in the key
    is_vision <- grepl("fig", key, fixed = TRUE)

    if (is_vision) {
      total_vision <- total_vision + 1
    } else {
      total_written <- total_written + 1
    }

    if (!(key %in% names(reported))) next

    rep_val <- coerce_value(reported[[key]])

    if (is.numeric(gt_val) && length(gt_val) == 1) {
      if (is.numeric(rep_val) && length(rep_val) == 1) {
        bounds <- intervals[[key]]
        if (!is.null(bounds) && rep_val >= bounds[1] && rep_val <= bounds[2]) {
          if (is_vision) {
            correct_vision <- correct_vision + 1
          } else {
            correct_written <- correct_written + 1
          }
        }
      }
    } else if (is.character(gt_val)) {
      # Case-insensitive comparison
      if (tolower(as.character(rep_val)) == tolower(gt_val)) {
        if (is_vision) {
          correct_vision <- correct_vision + 1
        } else {
          correct_written <- correct_written + 1
        }
      }
    } else if (is.list(gt_val) || (is.numeric(gt_val) && length(gt_val) > 1)) {
      if (identical(rep_val, gt_val)) {
        if (is_vision) {
          correct_vision <- correct_vision + 1
        } else {
          correct_written <- correct_written + 1
        }
      }
    }
  }

  return(list(
    capsule_id = gt_capsule$capsule_id,
    correct_written = correct_written,
    correct_vision = correct_vision,
    total_written = total_written,
    total_vision = total_vision
  ))
}


# Evaluate each agent
all_results <- list()
files <- list.files(reports_dir, pattern = "\\.json$", full.names = TRUE)
for (filepath in sort(files)) {
  agent_name <- tools::file_path_sans_ext(basename(filepath))
  report <- fromJSON(filepath, simplifyVector = FALSE)

  capsule_results <- list()
  for (cr in report$capsule_results) {
    gt_capsule <- NULL
    for (g in gt_data) {
      if (g$capsule_id == cr$capsule_id) {
        gt_capsule <- g
        break
      }
    }
    if (is.null(gt_capsule)) next

    reported <- cr$result_report
    if (is.null(reported)) reported <- list()

    result <- evaluate_capsule(gt_capsule, reported)
    capsule_results <- c(capsule_results, list(result))
  }

  all_results[[agent_name]] <- capsule_results
}

# TODO: Implement aggregate scoring per the paper specification
# TODO: Implement prediction interval output file
output <- toJSON(all_results, auto_unbox = TRUE, pretty = TRUE)
writeLines(output, file.path(output_dir, "evaluation_summary.json"))

cat("Beta evaluation complete.\n")
