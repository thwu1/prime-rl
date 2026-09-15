package main

import "strconv"


const RecordLength = 94

// ACHFile represents a parsed NACHA ACH file.
type ACHFile struct {
	Header  string  // raw file header record (type 1)
	Batches []Batch // parsed batches
}

// Batch holds a batch header and its entry/addenda records.
// The batch control record is not stored; it is recomputed during merge.
type Batch struct {
	Header  string   // raw batch header record (type 5)
	Records []string // entry detail (type 6) and addenda (type 7) records in order
}

// MergedFile is the output of the merge operation.
type MergedFile struct {
	Header  string
	Batches []MergedBatch
	Control string
}

// MergedBatch is a batch in the merged output.
type MergedBatch struct {
	Header  string   // batch header with updated batch number
	Records []string // entry detail and addenda records in order
	Control string   // recomputed batch control record
}

// ValidationError represents a single validation finding.
type ValidationError struct {
	BatchNum int    `json:"batch_num"`
	EntrySeq int    `json:"entry_seq"`
	Code     string `json:"err_code"`
	Field    string `json:"field"`
	Message  string `json:"message"`
}

// ValidationReport is the JSON structure written to the report file.
type ValidationReport struct {
	FilesProcessed int               `json:"files_processed"`
	TotalBatches   int               `json:"total_batches"`
	TotalEntries   int               `json:"total_entries"`
	Errors         []ValidationError `json:"errors"`
	Valid          bool              `json:"valid"`
}

// --- Field extraction helpers (0-indexed Go slicing) ---

func getRecordType(record string) byte {
	if len(record) > 0 {
		return record[0]
	}
	return 0
}

// Batch header field extractors

func getServiceClassCode(batchHeader string) string {
	return batchHeader[1:4] // positions 2-4
}

func getCompanyName(batchHeader string) string {
	return batchHeader[4:20] // positions 5-20
}

func getCompanyDiscData(batchHeader string) string {
	return batchHeader[20:40] // positions 21-40
}

func getCompanyID(batchHeader string) string {
	return batchHeader[40:50] // positions 41-50
}

func getSECCode(batchHeader string) string {
	return batchHeader[50:53] // positions 51-53
}

func getODFIID(batchHeader string) string {
	return batchHeader[79:87] // positions 80-87
}

func getBatchNumber(record string) int {
	n, _ := strconv.Atoi(record[87:94])
	return n
}

// Entry detail field extractors

func getTransactionCode(entry string) string {
	return entry[1:3] // positions 2-3
}

func getRoutingNumber(entry string) string {
	// Returns full 9-digit routing number (positions 4-12, indices 3-12)
	return entry[3:12]
}

func getRDFIIdentification(entry string) string {
	// Returns first 8 digits of routing (positions 4-11, indices 3-11)
	return entry[3:11]
}

func getCheckDigit(entry string) byte {
	return entry[11] // position 12
}

func getAmount(entry string) int {
	n, _ := strconv.Atoi(entry[29:39]) // positions 30-39
	return n
}

func getTraceNumber(entry string) string {
	return entry[79:94] // positions 80-94
}

func isCredit(txCode string) bool {
	if len(txCode) < 2 {
		return false
	}
	// Credits: second digit is 1 (return/NOC of credit), 2 (credit),
	// 3 (prenote credit), 4 (zero dollar credit)
	switch txCode[1] {
	case '1', '2', '3', '4':
		return true
	}
	return false
}

func isDebit(txCode string) bool {
	if len(txCode) < 2 {
		return false
	}
	// Debits: second digit is 6 (return/NOC of debit), 7 (debit),
	// 8 (prenote debit), 9 (zero dollar debit)
	switch txCode[1] {
	case '6', '7', '8', '9':
		return true
	}
	return false
}

// --- Formatting helpers ---

func zeroPadLeft(s string, width int) string {
	for len(s) < width {
		s = "0" + s
	}
	if len(s) > width {
		s = s[len(s)-width:]
	}
	return s
}

func spacePadRight(s string, width int) string {
	for len(s) < width {
		s = s + " "
	}
	if len(s) > width {
		s = s[:width]
	}
	return s
}
