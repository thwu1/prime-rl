package main

import (
	"bufio"
	"fmt"
	"os"
	"strings"
)


// ParseACHFile reads a NACHA ACH file and returns the parsed structure.
// Batch control and file control records are discarded (they will be recomputed).
func ParseACHFile(path string) (*ACHFile, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()

	var records []string
	scanner := bufio.NewScanner(f)
	for scanner.Scan() {
		line := scanner.Text()
		if strings.TrimSpace(line) == "" {
			continue
		}
		// Normalize to exactly 94 characters
		if len(line) < RecordLength {
			line = spacePadRight(line, RecordLength)
		} else if len(line) > RecordLength {
			line = line[:RecordLength]
		}
		records = append(records, line)
	}
	if err := scanner.Err(); err != nil {
		return nil, err
	}

	return parseRecords(records)
}

func parseRecords(records []string) (*ACHFile, error) {
	if len(records) == 0 {
		return nil, fmt.Errorf("empty file")
	}

	ach := &ACHFile{}

	if getRecordType(records[0]) != '1' {
		return nil, fmt.Errorf("expected file header (type 1), got type %c", records[0][0])
	}
	ach.Header = records[0]

	var currentBatch *Batch
	for i := 1; i < len(records); i++ {
		rec := records[i]
		switch getRecordType(rec) {
		case '5': // Batch Header
			currentBatch = &Batch{Header: rec}
		case '6': // Entry Detail
			if currentBatch == nil {
				return nil, fmt.Errorf("entry detail without batch header at record %d", i)
			}
			currentBatch.Records = append(currentBatch.Records, rec)
		case '7': // Addenda
			if currentBatch == nil {
				return nil, fmt.Errorf("addenda without batch header at record %d", i)
			}
			currentBatch.Records = append(currentBatch.Records, rec)
		case '8': // Batch Control — discard, will recompute
			if currentBatch != nil {
				ach.Batches = append(ach.Batches, *currentBatch)
				currentBatch = nil
			}
		case '9': // File Control or padding — skip
			continue
		}
	}

	return ach, nil
}
