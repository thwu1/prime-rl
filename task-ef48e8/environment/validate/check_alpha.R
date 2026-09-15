#!/usr/bin/env Rscript
# Independent R computation of Krippendorff's alpha for cross-validation.
# Reads annotation data and computes alpha using the coincidence matrix
# approach for nominal categorical data.

# Read annotation labels from SQLite via system sqlite3 command
data <- read.csv(pipe('sqlite3 -header -csv /app/data/annotations.db "SELECT case_id, annotator_id, sentence_id, relevance FROM annotations"'),
                 stringsAsFactors = FALSE)

categories <- c("essential", "supplementary", "not-relevant")
n_cats <- length(categories)

# Build coincidence matrix
coincidence <- matrix(0, nrow = n_cats, ncol = n_cats)
rownames(coincidence) <- categories
colnames(coincidence) <- categories

# Create unique unit identifiers
data$unit_id <- paste(data$case_id, data$sentence_id, sep = "_")
units <- unique(data$unit_id)

for (u in units) {
    unit_labels <- data$relevance[data$unit_id == u]
    m_u <- length(unit_labels)
    if (m_u < 2) next

    for (c_name in categories) {
        n_c <- sum(unit_labels == c_name)
        # Diagonal entry
        coincidence[c_name, c_name] <- coincidence[c_name, c_name] +
            n_c * (n_c - 1) / (m_u - 1)
        # Off-diagonal entries
        for (k_name in categories) {
            if (k_name != c_name) {
                n_k <- sum(unit_labels == k_name)
                coincidence[c_name, k_name] <- coincidence[c_name, k_name] +
                    n_c * n_k / (m_u - 1)
            }
        }
    }
}

# Marginals
n_marginals <- rowSums(coincidence)
n_total <- sum(n_marginals)

# Observed disagreement
diag_sum <- sum(diag(coincidence))
D_o <- (n_total - diag_sum) / n_total

# Expected disagreement
D_e <- 0
for (i in 1:(n_cats - 1)) {
    for (j in (i + 1):n_cats) {
        D_e <- D_e + n_marginals[i] * n_marginals[j]
    }
}
D_e <- D_e / (n_total^2)

# Alpha
alpha <- 1 - D_o / D_e

# Write result
dir.create("/app/output", showWarnings = FALSE, recursive = TRUE)
writeLines(sprintf("%.6f", alpha), "/app/output/alpha_validation.txt")
cat("R-computed alpha:", alpha, "\n")
