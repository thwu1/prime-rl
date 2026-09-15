package main

import (
	"encoding/json"
	"fmt"
	"os"
	"strings"
)


// WriteACHFile writes the merged file to the given path.
func WriteACHFile(merged *MergedFile, path string) error {
	f, err := os.Create(path)
	if err != nil {
		return err
	}
	defer f.Close()

	// Write file header
	if _, err := fmt.Fprintln(f, merged.Header); err != nil {
		return err
	}

	// Write each batch: header, entries/addenda, control
	for _, batch := range merged.Batches {
		if _, err := fmt.Fprintln(f, batch.Header); err != nil {
			return err
		}
		for _, rec := range batch.Records {
			if _, err := fmt.Fprintln(f, rec); err != nil {
				return err
			}
		}
		if _, err := fmt.Fprintln(f, batch.Control); err != nil {
			return err
		}
	}

	// Write file control
	if _, err := fmt.Fprintln(f, merged.Control); err != nil {
		return err
	}

	// Pad with all-9s records to reach a multiple of 10 lines
	totalRecords := 2 // file header + file control
	for _, batch := range merged.Batches {
		totalRecords += 2 + len(batch.Records)
	}

	padding := strings.Repeat("9", RecordLength)
	remainder := totalRecords % 10
	if remainder != 0 {
		for i := 0; i < 10-remainder; i++ {
			if _, err := fmt.Fprintln(f, padding); err != nil {
				return err
			}
		}
	}

	return nil
}

// WriteReport writes the validation report as JSON to the given path.
func WriteReport(report ValidationReport, path string) error {
	f, err := os.Create(path)
	if err != nil {
		return err
	}
	defer f.Close()

	enc := json.NewEncoder(f)
	enc.SetIndent("", "  ")
	return enc.Encode(report)
}
