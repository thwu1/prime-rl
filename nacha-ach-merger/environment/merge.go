package main

import (
	"fmt"
	"strconv"
	"strings"
)


// MergeFiles combines batches from multiple ACH files into a single merged file.
func MergeFiles(files []*ACHFile) (*MergedFile, error) {
	if len(files) == 0 {
		return nil, fmt.Errorf("no files to merge")
	}

	merged := &MergedFile{
		Header: files[0].Header,
	}

	batchNum := 1
	for _, f := range files {
		for _, batch := range f.Batches {
			mb := MergedBatch{
				Header:  setBatchNumber(batch.Header, batchNum),
				Records: batch.Records,
				Control: computeBatchControl(batch, batchNum),
			}
			merged.Batches = append(merged.Batches, mb)
			batchNum++
		}
	}

	merged.Control = computeFileControl(merged)
	return merged, nil
}

// setBatchNumber returns a copy of the batch header with the batch number
// field (positions 88-94) set to num.
func setBatchNumber(header string, num int) string {
	numStr := zeroPadLeft(strconv.Itoa(num), 7)
	return header[:87] + numStr
}

// computeBatchControl builds a new batch control record (type 8) by
// scanning the entries and addenda in the batch.
func computeBatchControl(batch Batch, batchNum int) string {
	serviceClassCode := getServiceClassCode(batch.Header)
	companyID := getCompanyID(batch.Header)
	odfiID := getODFIID(batch.Header)

	entryCount := 0
	entryHash := 0
	totalDebit := 0
	totalCredit := 0

	for _, rec := range batch.Records {
		if getRecordType(rec) == '6' {
			entryCount++

			// Sum routing numbers for entry hash
			routing := getRoutingNumber(rec)
			rn, _ := strconv.Atoi(routing)
			entryHash += rn

			amount := getAmount(rec)
			txCode := getTransactionCode(rec)
			if isCredit(txCode) {
				totalCredit += amount
			} else if isDebit(txCode) {
				totalDebit += amount
			}
		}
		// NOTE: addenda records (type 7) are not counted here
	}

	// Truncate entry hash to 10 digits if needed
	entryHashStr := strconv.Itoa(entryHash)
	if len(entryHashStr) > 10 {
		entryHashStr = entryHashStr[len(entryHashStr)-10:]
	}

	// Build the 94-character batch control record:
	// Pos 1:     Record type "8"
	// Pos 2-4:   Service class code (3)
	// Pos 5-10:  Entry/addenda count (6)
	// Pos 11-20: Entry hash (10)
	// Pos 21-32: Total debit (12)
	// Pos 33-44: Total credit (12)
	// Pos 45-54: Company identification (10)
	// Pos 55-73: Message authentication code (19, blank)
	// Pos 74-79: Reserved (6, blank)
	// Pos 80-87: ODFI identification (8)
	// Pos 88-94: Batch number (7)
	control := "8" +
		serviceClassCode +
		zeroPadLeft(strconv.Itoa(entryCount), 6) +
		zeroPadLeft(entryHashStr, 10) +
		zeroPadLeft(strconv.Itoa(totalDebit), 12) +
		zeroPadLeft(strconv.Itoa(totalCredit), 12) +
		spacePadRight(companyID, 10) +
		spacePadRight("", 19) +
		spacePadRight("", 6) +
		spacePadRight(odfiID, 8) +
		zeroPadLeft(strconv.Itoa(getBatchNumber(batch.Header)), 7)

	return control
}

// computeFileControl builds the file control record (type 9) by
// aggregating values from all batch controls.
func computeFileControl(merged *MergedFile) string {
	batchCount := len(merged.Batches)

	// Count total records in the file
	totalRecords := 2 // file header + file control
	for _, batch := range merged.Batches {
		totalRecords += 2 + len(batch.Records) // batch header + records + batch control
	}

	// Calculate block count
	blockCount := totalRecords / 10

	// Aggregate batch control values
	entryAddendaCount := 0
	entryHash := 0
	totalDebit := 0
	totalCredit := 0

	for _, batch := range merged.Batches {
		bc := batch.Control
		eac, _ := strconv.Atoi(strings.TrimSpace(bc[4:10]))
		eh, _ := strconv.Atoi(strings.TrimSpace(bc[10:20]))
		td, _ := strconv.Atoi(strings.TrimSpace(bc[20:32]))
		tc, _ := strconv.Atoi(strings.TrimSpace(bc[32:44]))

		entryAddendaCount += eac
		entryHash += eh
		totalDebit += td
		totalCredit += tc
	}

	// Build 94-character file control record
	control := "9" +
		zeroPadLeft(strconv.Itoa(batchCount), 6) +
		zeroPadLeft(strconv.Itoa(blockCount), 6) +
		zeroPadLeft(strconv.Itoa(entryAddendaCount), 8) +
		zeroPadLeft(strconv.Itoa(entryHash), 10) +
		zeroPadLeft(strconv.Itoa(totalDebit), 12) +
		zeroPadLeft(strconv.Itoa(totalCredit), 12) +
		spacePadRight("", 39)

	return control
}
