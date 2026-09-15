#' Tree similarity measures
#'
#' Measure tree similarity or difference.
#'
#' Estabrook et al. (1985, table 2) define four similarity metrics in terms
#' of the total number of quartets (N, their Q), the number of quartets
#' resolved in the same manner in two trees (s), the number resolved
#' differently in both trees (d), the number resolved in tree 1 or 2 but
#' unresolved in the other tree (r1, r2), and the number that are unresolved
#' in both trees (u).
#'
#' The similarity metrics are then given as below. The dissimilarity metrics
#' are their complement (i.e. 1 - similarity), and can be calculated
#' algebraically using the identity N = s + d + r1 + r2 + u.
#'
#' Note that throughout this code, N = 2 * Q where Q = choose(n_tips, 4).
#'
#' * Do Not Conflict (DC): (s + r1 + r2 + u) / N
#'
#' * Explicitly Agree (EA): s / N
#'
#' * Strict Joint Assertions (SJA): s / (s + d)
#'
#' * SemiStrict Joint Assertions (SSJA): s / (s + d + u)
#'
#' Steel & Penny (1993) propose a further metric, denoted d_Q:
#'
#' * Steel & Penny's quartet metric (dQ): (s + u) / N
#'
#' Symmetric difference normalizations:
#'
#' * Symmetric Difference (SD): (2d + r1 + r2) / (2d + 2s + r1 + r2)
#'
#' * Marczewski-Steinhaus (MS): (2d + r1 + r2) / (2d + s + r1 + r2)
#'
#' * Symmetric Divergence: (d + d + r1 + r2) / N
#'
#' @param elementStatus Status vector or matrix with columns named
#'   N, Q, s, d, r1, r2, u (or d1, d2 instead of d).
#' @param similarity Logical specifying whether to calculate the similarity
#'   or dissimilarity.
#'
#' @references
#'   Estabrook, G. F., McMorris, F. R., & Meacham, C. A. (1985).
#'   Comparison of undirected phylogenetic trees based on subtrees of four
#'   evolutionary units. Systematic Zoology, 34(2), 193-200.
#'
#'   Steel, M. A. & Penny, D. (1993). Distributions of tree comparison
#'   metrics -- some new results. Systematic Biology, 42(2), 126-141.
#'
#' @export
SimilarityMetrics <- function (elementStatus, similarity = TRUE) {
  elementStatus <- .StatusToMatrix(elementStatus)
  rows <- nrow(elementStatus)
  RS <- function (x) .rowSums(elementStatus[, x], rows, length(x))
  ddr1r2 <- RS(c("2d", "r1", "r2"))
  result <- cbind(
    DoNotConflict = elementStatus[, "2d"] / elementStatus[, "N"],
    ExplicitlyAgree = 1 - (2L * elementStatus[, "s"]) / elementStatus[, "N"],
    StrictJointAssertions = elementStatus[, "2d"] / RS(c("2d", "s", "s")),
    SemiStrictJointAssertions = SemiStrictJointAssertions(elementStatus,
                                                          similarity = FALSE),
    SymmetricDifference = ddr1r2 / RS(c("2d", "s", "s", "r1", "r2")),
    MarczewskiSteinhaus = ddr1r2 / RS(c("2d", "s", "r1", "r2")),
    SteelPenny = SteelPenny(elementStatus, similarity = FALSE),
    QuartetDivergence = ddr1r2 / elementStatus[, "N"]
  )
  rownames(result) <- rownames(elementStatus)
  if (similarity) 1 - result else result
}


#' Normalize element statuses to generate metric
#'
#' Handles vectors and matrices of two or three dimensions.
#'
#' @param elementStatus Status vector/matrix.
#' @param numerator,denominator Character vector listing elements to sum in
#'   numerator / denominator.
#' @param takeFromOne Logical specifying whether to deduct value from one.
#'
#' @keywords internal
#' @export
.NormalizeStatus <- function (elementStatus, numerator, denominator, takeFromOne) {
  dims <- dim(elementStatus)
  if (is.null(dims) || length(dims) == 2L) {
    elementStatus <- .StatusToMatrix(elementStatus)
    result <- rowSums(elementStatus[, numerator, drop = FALSE]) /
      rowSums(elementStatus[, denominator, drop = FALSE])
  } else {
    elementStatus <- .StatusToArray(elementStatus)
    result <- rowSums(elementStatus[, , numerator, drop = FALSE], dims = 2L) /
      rowSums(elementStatus[, , denominator, drop = FALSE], dims = 2L)
  }
  if (takeFromOne) 1 - result else result
}

#' Status vector to matrix
#'
#' Converts a vector to a matrix that can be analysed by the DoNotConflict()
#' function family.
#'
#' @param statusVector Either (i) a named vector of integers, with
#'   names N, s, r1, r2, either d or d1 and d2, and optionally u;
#'   or (ii) a matrix whose named rows correspond to the same quantities.
#' @return A matrix, containing the input columns plus 2d, representing
#'   either 2 * d or d1 + d2, and row names.
#'
#' @keywords internal
#' @export
.StatusToMatrix <- function (statusVector) {
  if (is.null(dim(statusVector))) {
    statusVector <- matrix(statusVector, 1L,
                           dimnames = list("tree", names(statusVector)))
  }
  if ("2d" %in% colnames(statusVector)) {
    # Repeat visitor; return unadulterated
    statusVector
  } else if ("d" %in% colnames(statusVector)) {
    statusVector <- cbind(statusVector, "2d" = 2L * unname(statusVector[, "d"]))
  } else {
    twoD <- unname(statusVector[, "d1"] + statusVector[, "d2"])
    statusVector <- cbind(statusVector, "2d" = twoD, "d" = twoD / 2L)

    if (!"u" %in% colnames(statusVector)) {
      statusVector <- cbind(statusVector,
                          "u" = unname(statusVector[, "d1"] * 0))
    }
  }

  # Return:
  statusVector
}


#' @rdname SimilarityMetrics
#' @export
DoNotConflict <- function (elementStatus, similarity = TRUE) {
  .NormalizeStatus(elementStatus, "2d", "N", similarity)
}

#' @rdname SimilarityMetrics
#' @export
ExplicitlyAgree <- function (elementStatus, similarity = TRUE) {
  .NormalizeStatus(elementStatus, c("s", "s"), "N", !similarity)
}

#' @rdname SimilarityMetrics
#' @export
StrictJointAssertions <- function (elementStatus, similarity = TRUE) {
  .NormalizeStatus(elementStatus, "2d", c("2d", "s", "s"), similarity)
}

#' @rdname SimilarityMetrics
#' @export
SemiStrictJointAssertions <- function (elementStatus, similarity = TRUE) {
  if (all(c("s", "d", "u") %in% c(names(elementStatus),
                                  unlist(dimnames(elementStatus))))) {
    .NormalizeStatus(elementStatus, if (similarity) "s" else "d",
                     c("s", "d", "u"), FALSE)
  } else {
    NA
  }
}

#' @rdname SimilarityMetrics
#' @export
SymmetricDifference <- function (elementStatus, similarity = TRUE) {
  .NormalizeStatus(elementStatus, c("2d", "r1", "r2"),
                     c("2d", "s", "s", "r1", "r2"), similarity)
}

#' @rdname SimilarityMetrics
#' @export
MarczewskiSteinhaus <- function (elementStatus, similarity = TRUE) {
  .NormalizeStatus(elementStatus, c("2d", "r1", "r2"), c("2d", "s", "r1", "r2"),
                   similarity)
}

#' @rdname SimilarityMetrics
#' @export
SteelPenny <- function (elementStatus, similarity = TRUE) {
  # Defined in Steel & Penny, p. 133; "dq would be written as D + R".
  # dq = D + R in Day's (1986) terminology, where D = d/Q, R = (r1 + r2)/Q
  .NormalizeStatus(elementStatus, c("2d", "r1", "r1", "r2", "r2"), "N",
                   similarity)
}

#' @rdname SimilarityMetrics
#' @export
QuartetDivergence <- function (elementStatus, similarity = TRUE) {
  .NormalizeStatus(elementStatus, c("2d", "r1", "r2"), "N", similarity)
}
