#!/bin/bash
INPUT_DIR=/app/input            // Input directory for log files
OUTPUT_DIR=/app/output          // Output base directory
ARCHIVE_DIR=/app/output/archive // Archive output directory
HEADER_FILE=/app/header.txt     // Header template file
ALERT_THRESHOLD=3               // Minimum errors for burst detection
BURST_WINDOW=60                 // Burst window in seconds
