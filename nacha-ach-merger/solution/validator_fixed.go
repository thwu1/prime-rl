package main


// ValidateFile checks all entries in an ACH file and returns validation errors.
func ValidateFile(ach *ACHFile) []ValidationError {
	var errors []ValidationError

	for batchIdx, batch := range ach.Batches {
		batchNum := batchIdx + 1
		scc := getServiceClassCode(batch.Header)
		odfiID := getODFIID(batch.Header)

		entrySeq := 0
		for _, rec := range batch.Records {
			if getRecordType(rec) != '6' {
				continue
			}
			entrySeq++

			// Check digit validation
			routing := getRoutingNumber(rec)
			if !validateCheckDigit(routing) {
				errors = append(errors, ValidationError{
					BatchNum: batchNum,
					EntrySeq: entrySeq,
					Code:     "CHECKDIGIT",
					Field:    "routing_number",
					Message:  "Invalid ABA routing number check digit: " + routing,
				})
			}

			// Service class code consistency
			sccErrs := validateSCCEntry(scc, getTransactionCode(rec), batchNum, entrySeq)
			errors = append(errors, sccErrs...)

			// FIX: Call amount range validation
			amtErrs := validateAmountRange(getAmount(rec), batchNum, entrySeq)
			errors = append(errors, amtErrs...)
		}

		// FIX: Call duplicate trace detection
		dupErrs := validateDuplicateTraces(batch.Records, batchNum)
		errors = append(errors, dupErrs...)

		// FIX: Call trace ODFI prefix validation
		odfiErrs := validateTraceODFI(batch.Records, odfiID, batchNum)
		errors = append(errors, odfiErrs...)

		// Addenda validation
		indErrs := validateAddendaIndicator(batch.Records, batchNum)
		errors = append(errors, indErrs...)

		seqErrs := validateAddendaSequence(batch.Records, batchNum)
		errors = append(errors, seqErrs...)
	}

	return errors
}

// validateCheckDigit checks whether a 9-digit routing number has a valid
// check digit per the ABA modulus-10 algorithm.
func validateCheckDigit(routing string) bool {
	if len(routing) != 9 {
		return false
	}
	// FIX: Use ABA modulus-10 weights [3,7,1,3,7,1,3,7,1]
	weights := [9]int{3, 7, 1, 3, 7, 1, 3, 7, 1}
	sum := 0
	for i := 0; i < 9; i++ {
		d := int(routing[i] - '0')
		sum += d * weights[i]
	}
	return sum%10 == 0
}

// validateSCCEntry checks if an entry's transaction code is consistent
// with the batch service class code.
func validateSCCEntry(scc, txCode string, batchNum, entrySeq int) []ValidationError {
	var errors []ValidationError
	credit := isCredit(txCode)
	debit := isDebit(txCode)

	switch scc {
	case "200":
		// FIX: Mixed — both credits and debits allowed, no validation needed
		_ = credit
		_ = debit
	case "220":
		if debit {
			errors = append(errors, ValidationError{
				BatchNum: batchNum, EntrySeq: entrySeq,
				Code: "SCC_MISMATCH", Field: "transaction_code",
				Message: "Debit entry in credits-only batch (SCC 220)",
			})
		}
	case "225":
		if credit {
			errors = append(errors, ValidationError{
				BatchNum: batchNum, EntrySeq: entrySeq,
				Code: "SCC_MISMATCH", Field: "transaction_code",
				Message: "Credit entry in debits-only batch (SCC 225)",
			})
		}
	default:
		errors = append(errors, ValidationError{
			BatchNum: batchNum, EntrySeq: entrySeq,
			Code: "SCC_MISMATCH", Field: "service_class_code",
			Message: "Unknown service class code: " + scc,
		})
	}

	return errors
}

// validateAmountRange checks if an entry amount exceeds the NACHA limit
// of $25,000,000.00 (2,500,000,000 cents).
func validateAmountRange(amount int, batchNum, entrySeq int) []ValidationError {
	// FIX: Implement amount range check
	const maxAmount = 2500000000
	if amount > maxAmount {
		return []ValidationError{{
			BatchNum: batchNum, EntrySeq: entrySeq,
			Code: "AMOUNT_RANGE", Field: "amount",
			Message: "Entry amount exceeds $25,000,000.00 limit",
		}}
	}
	return nil
}

// validateDuplicateTraces checks for duplicate trace numbers within a batch.
func validateDuplicateTraces(records []string, batchNum int) []ValidationError {
	// FIX: Implement duplicate trace detection
	seen := make(map[string]int)
	var errors []ValidationError
	entrySeq := 0
	for _, rec := range records {
		if getRecordType(rec) != '6' {
			continue
		}
		entrySeq++
		trace := getTraceNumber(rec)
		if _, exists := seen[trace]; exists {
			errors = append(errors, ValidationError{
				BatchNum: batchNum, EntrySeq: entrySeq,
				Code: "DUPLICATE_TRACE", Field: "trace_number",
				Message: "Duplicate trace number in batch: " + trace,
			})
		} else {
			seen[trace] = entrySeq
		}
	}
	return errors
}

// validateTraceODFI checks that the first 8 characters of each entry's
// trace number match the batch ODFI identification.
func validateTraceODFI(records []string, odfiID string, batchNum int) []ValidationError {
	// FIX: Implement trace ODFI prefix validation
	var errors []ValidationError
	entrySeq := 0
	for _, rec := range records {
		if getRecordType(rec) != '6' {
			continue
		}
		entrySeq++
		tracePrefix := rec[79:87]
		if tracePrefix != odfiID {
			errors = append(errors, ValidationError{
				BatchNum: batchNum, EntrySeq: entrySeq,
				Code: "TRACE_ODFI", Field: "trace_number",
				Message: "Trace ODFI prefix " + tracePrefix + " does not match batch ODFI " + odfiID,
			})
		}
	}
	return errors
}
