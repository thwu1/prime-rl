package main

import (
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"sort"
)


func main() {
	inputDir := flag.String("input", "", "Input directory containing .ach files")
	outputFile := flag.String("output", "", "Output merged ACH file path")
	reportFile := flag.String("report", "", "Output JSON validation report path")
	flag.Parse()

	if *inputDir == "" || *outputFile == "" {
		fmt.Fprintf(os.Stderr, "Usage: achpipe --input <dir> --output <file> [--report <file>]\n")
		os.Exit(1)
	}

	files, err := filepath.Glob(filepath.Join(*inputDir, "*.ach"))
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error listing files: %v\n", err)
		os.Exit(1)
	}
	sort.Strings(files)

	if len(files) == 0 {
		fmt.Fprintf(os.Stderr, "No .ach files found in %s\n", *inputDir)
		os.Exit(1)
	}

	var achFiles []*ACHFile
	for _, f := range files {
		ach, err := ParseACHFile(f)
		if err != nil {
			fmt.Fprintf(os.Stderr, "Error parsing %s: %v\n", f, err)
			os.Exit(1)
		}
		achFiles = append(achFiles, ach)
	}

	// Validate all files
	allErrors := []ValidationError{}
	totalBatches := 0
	totalEntries := 0
	for _, ach := range achFiles {
		errs := ValidateFile(ach)
		allErrors = append(allErrors, errs...)
		for _, batch := range ach.Batches {
			totalBatches++
			for _, rec := range batch.Records {
				if getRecordType(rec) == '6' {
					totalEntries++
				}
			}
		}
	}

	// Merge all files
	merged, err := MergeFiles(achFiles)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error merging: %v\n", err)
		os.Exit(1)
	}

	if err := WriteACHFile(merged, *outputFile); err != nil {
		fmt.Fprintf(os.Stderr, "Error writing merged file: %v\n", err)
		os.Exit(1)
	}

	// Write validation report if requested
	if *reportFile != "" {
		report := ValidationReport{
			FilesProcessed: len(achFiles),
			TotalBatches:   totalBatches,
			TotalEntries:   totalEntries,
			Errors:         allErrors,
			Valid:          len(allErrors) == 0,
		}
		if err := WriteReport(report, *reportFile); err != nil {
			fmt.Fprintf(os.Stderr, "Error writing report: %v\n", err)
			os.Exit(1)
		}
	}
}
