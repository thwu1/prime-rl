package main

import "strconv"


// validateAddendaIndicator checks that the addenda record indicator on each
// entry detail is consistent with whether addenda records actually follow it.
func validateAddendaIndicator(records []string, batchNum int) []ValidationError {
	var errors []ValidationError
	entrySeq := 0

	for i := 0; i < len(records); i++ {
		if getRecordType(records[i]) != '6' {
			continue
		}
		entrySeq++

		// Check if addenda follow this entry
		hasAddenda := false
		for j := i + 1; j < len(records); j++ {
			if getRecordType(records[j]) == '7' {
				hasAddenda = true
			} else {
				break
			}
		}

		// FIX: Use index 78 (position 79 in 1-based, 0-indexed = 78)
		indicator := records[i][78]

		if hasAddenda && indicator != '1' {
			errors = append(errors, ValidationError{
				BatchNum: batchNum, EntrySeq: entrySeq,
				Code: "ADDENDA_IND", Field: "addenda_indicator",
				Message: "Entry has addenda but indicator is not '1'",
			})
		} else if !hasAddenda && indicator == '1' {
			errors = append(errors, ValidationError{
				BatchNum: batchNum, EntrySeq: entrySeq,
				Code: "ADDENDA_IND", Field: "addenda_indicator",
				Message: "Entry indicator is '1' but no addenda follow",
			})
		}
	}
	return errors
}

// validateAddendaSequence checks that type 05 addenda records have sequential
// sequence numbers starting from 1 for each parent entry.
func validateAddendaSequence(records []string, batchNum int) []ValidationError {
	var errors []ValidationError
	entrySeq := 0
	expectedSeq := 1

	for _, rec := range records {
		rt := getRecordType(rec)
		if rt == '6' {
			entrySeq++
			expectedSeq = 1 // FIX: Reset sequence counter for each new entry
			continue
		}
		if rt == '7' {
			// Addenda type 05: sequence number at positions 84-87 (indices 83-87)
			if len(rec) >= 87 {
				seqStr := rec[83:87]
				seq, err := strconv.Atoi(seqStr)
				if err == nil && seq != expectedSeq {
					errors = append(errors, ValidationError{
						BatchNum: batchNum, EntrySeq: entrySeq,
						Code: "ADDENDA_SEQ", Field: "addenda_sequence",
						Message: "Addenda sequence " + seqStr + ", expected " + strconv.Itoa(expectedSeq),
					})
				}
				expectedSeq++
			}
		}
	}
	return errors
}
