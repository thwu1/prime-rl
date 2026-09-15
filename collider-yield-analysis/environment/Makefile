# VLQ T->tH Analysis Pipeline
# Usage: make -C /app/pipeline all

SHELL := /bin/bash

ROOT_FILE   := /app/data/signal.root
CALIB_DB    := /app/calibration/calib.db
INTERMEDIATE := /app/intermediate
RESULTS     := /app/results/results.yaml

.PHONY: all clean

all: $(RESULTS)

$(INTERMEDIATE)/events.npz: $(ROOT_FILE)
	@mkdir -p $(INTERMEDIATE)
	python3 /app/pipeline/extract.py

$(RESULTS): $(INTERMEDIATE)/events.npz $(CALIB_DB) /app/pipeline/analyze.py
	python3 /app/pipeline/analyze.py

clean:
	rm -rf $(INTERMEDIATE)
