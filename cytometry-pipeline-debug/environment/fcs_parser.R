# fcs_parser.R — FCS 3.0 Binary File Parser
#
# Implements parsing of Flow Cytometry Standard (FCS) 3.0 files.
# Reads the HEADER, TEXT, and DATA segments to produce an expression matrix.
#

#' Parse an FCS 3.0 file
#' @param filename Path to the FCS file
#' @return A list with components:
#'   - exprs: numeric matrix (events x parameters)
#'   - keywords: named character vector of TEXT segment keywords
#'   - param_names: character vector of parameter names
parse_fcs <- function(filename) {
  if (!file.exists(filename)) {
    stop("FCS file not found: ", filename)
  }

  con <- file(filename, open = "rb")
  on.exit(close(con))

  # Read HEADER segment (first 58 bytes)
  header <- read_fcs_header(con)

  # Read TEXT segment (delimiter-separated key-value pairs)
  keywords <- read_fcs_text(con, header$text_start, header$text_end)

  # Extract data segment parameters from TEXT keywords
  n_params <- as.integer(keywords[["$PAR"]])
  n_events <- as.integer(keywords[["$TOT"]])
  datatype <- keywords[["$DATATYPE"]]
  byteord  <- keywords[["$BYTEORD"]]

  if (is.null(n_params) || is.null(n_events)) {
    stop("Missing required FCS keywords $PAR or $TOT")
  }

  # Resolve data segment offsets: prefer HEADER, fall back to TEXT keywords
  # when HEADER stores zeros (allowed for large files per FCS 3.0 spec)
  data_start <- header$data_start
  data_end   <- header$data_end
  if (data_start == 0 || data_end == 0) {
    data_start <- as.integer(keywords[["$BEGINDATA"]])
    data_end   <- as.integer(keywords[["$ENDDATA"]])
  }

  # Collect per-parameter bitwidths ($PnB keywords)
  bitwidths <- integer(n_params)
  for (i in seq_len(n_params)) {
    bitwidths[i] <- as.integer(keywords[[paste0("$P", i, "B")]])
  }

  # Read the binary DATA segment
  exprs <- read_fcs_data(con, data_start, data_end,
                         n_params, n_events,
                         datatype, byteord, bitwidths)

  # Attach parameter names from $PnN keywords
  param_names <- character(n_params)
  for (i in seq_len(n_params)) {
    param_names[i] <- keywords[[paste0("$P", i, "N")]]
  }
  colnames(exprs) <- param_names

  list(
    exprs       = exprs,
    keywords    = keywords,
    param_names = param_names
  )
}

# ---------------------------------------------------------------------------
# HEADER segment (exactly 58 bytes)
#   Bytes  0- 5 : version string, e.g. "FCS3.0"
#   Bytes  6- 9 : four ASCII spaces
#   Bytes 10-57 : six 8-character right-justified integer offset fields
#                 (text_start, text_end, data_start, data_end,
#                  analysis_start, analysis_end)
# ---------------------------------------------------------------------------
read_fcs_header <- function(con) {
  seek(con, 0)
  version <- readChar(con, 6)
  if (!version %in% c("FCS2.0", "FCS3.0", "FCS3.1", "FCS3.2")) {
    stop("Not a valid FCS file. Version string: ", version)
  }

  # Skip 4 ASCII spaces
  readChar(con, 4)

  # Read six 8-character offset fields
  offsets <- numeric(6)
  for (i in seq_len(6)) {
    field <- readChar(con, 8)
    offsets[i] <- as.integer(trimws(field))
  }

  list(
    version        = version,
    text_start     = offsets[1],
    text_end       = offsets[2],
    data_start     = offsets[3],
    data_end       = offsets[4],
    analysis_start = offsets[5],
    analysis_end   = offsets[6]
  )
}

# ---------------------------------------------------------------------------
# TEXT segment
#   First byte is the delimiter character.
#   Remainder is alternating key-delimiter-value-delimiter sequences.
#   A doubled delimiter inside a value represents a literal delimiter char.
# ---------------------------------------------------------------------------
read_fcs_text <- function(con, text_start, text_end) {
  seek(con, text_start)
  n_bytes <- text_end - text_start + 1
  raw_bytes <- readBin(con, "raw", n_bytes)
  txt <- rawToChar(raw_bytes)

  # First character is the delimiter
  delimiter <- substr(txt, 1, 1)
  body <- substr(txt, 2, nchar(txt))

  # Strip trailing delimiter
  if (endsWith(body, delimiter)) {
    body <- substr(body, 1, nchar(body) - 1)
  }

  # Split the body on the delimiter character
  parts <- strsplit(body, delimiter, fixed = TRUE)[[1]]

  # Pair up consecutive elements as key / value
  if (length(parts) %% 2 != 0) {
    parts <- parts[seq_len(length(parts) - 1)]
  }

  keys   <- parts[seq(1, length(parts), by = 2)]
  values <- parts[seq(2, length(parts), by = 2)]

  result <- values
  names(result) <- toupper(trimws(keys))

  result
}

# ---------------------------------------------------------------------------
# DATA segment
#   Binary data in list mode ($MODE=L): values stored event-by-event, with
#   each event containing n_params consecutive values.
#   $DATATYPE:  F = 32-bit float,  D = 64-bit double,  I = integer
#   $BYTEORD:   byte significance order
# ---------------------------------------------------------------------------
read_fcs_data <- function(con, data_start, data_end,
                          n_params, n_events,
                          datatype, byteord, bitwidths) {
  seek(con, data_start)
  n_bytes <- data_end - data_start + 1

  # Map $BYTEORD keyword to R endianness string
  endian <- switch(byteord,
    "4,3,2,1" = "little",
    "1,2,3,4" = "big",
    stop("Unsupported byte order: ", byteord)
  )

  # Map $DATATYPE to R type and element size in bytes
  what <- switch(datatype,
    "F" = "numeric",
    "D" = "numeric",
    "I" = "integer",
    stop("Unsupported data type: ", datatype)
  )

  elem_size <- switch(datatype,
    "F" = 4L,
    "D" = 8L,
    "I" = as.integer(bitwidths[1] / 8)
  )

  # Read all binary values
  total_values <- as.integer(n_params) * as.integer(n_events)
  dat <- readBin(con, what = what, n = total_values,
                 size = elem_size, endian = endian)

  if (length(dat) != total_values) {
    stop("DATA segment size mismatch: expected ", total_values,
         " values, got ", length(dat))
  }

  # Reshape into events x parameters matrix (FCS list mode = row-major)
  matrix(dat, nrow = n_events, ncol = n_params, byrow = TRUE)
}
