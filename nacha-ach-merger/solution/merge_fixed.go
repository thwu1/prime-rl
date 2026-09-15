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

	entryAddendaCount := 0
	entryHash := 0
	totalDebit := 0
	totalCredit := 0

	for _, rec := range batch.Records {
		rt := getRecordType(rec)
		if rt == '6' {
			entryAddendaCount++

			// FIX 1: Use 8-digit RDFI Identification, not 9-digit routing number
			rdfiID := getRDFIIdentification(rec)
			rn, _ := strconv.Atoi(rdfiID)
			entryHash += rn

			amount := getAmount(rec)
			txCode := getTransactionCode(rec)
			if isCredit(txCode) {
				totalCredit += amount
			} else if isDebit(txCode) {
				totalDebit += amount
			}
		} else if rt == '7' {
			// FIX 2: Count addenda records in EntryAddendaCount
			entryAddendaCount++
		}
	}

	// Truncate entry hash to 10 least-significant digits
	entryHashStr := strconv.Itoa(entryHash)
	if len(entryHashStr) > 10 {
		entryHashStr = entryHashStr[len(entryHashStr)-10:]
	}

	// Build the 94-character batch control record
	control := "8" +
		serviceClassCode +
		zeroPadLeft(strconv.Itoa(entryAddendaCount), 6) +
		zeroPadLeft(entryHashStr, 10) +
		zeroPadLeft(strconv.Itoa(totalDebit), 12) +
		zeroPadLeft(strconv.Itoa(totalCredit), 12) +
		spacePadRight(companyID, 10) +
		spacePadRight("", 19) +
		spacePadRight("", 6) +
		spacePadRight(odfiID, 8) +
		zeroPadLeft(strconv.Itoa(batchNum), 7) // FIX 3: Use reassigned batch number

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

	// FIX 4: Use ceiling division for block count
	blockCount := (totalRecords + 9) / 10

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

	// FIX 5: Truncate file-level entry hash to 10 least-significant digits
	entryHashStr := strconv.Itoa(entryHash)
	if len(entryHashStr) > 10 {
		entryHashStr = entryHashStr[len(entryHashStr)-10:]
	}

	// Build 94-character file control record
	control := "9" +
		zeroPadLeft(strconv.Itoa(batchCount), 6) +
		zeroPadLeft(strconv.Itoa(blockCount), 6) +
		zeroPadLeft(strconv.Itoa(entryAddendaCount), 8) +
		zeroPadLeft(entryHashStr, 10) +
		zeroPadLeft(strconv.Itoa(totalDebit), 12) +
		zeroPadLeft(strconv.Itoa(totalCredit), 12) +
		spacePadRight("", 39)

	return control
}
