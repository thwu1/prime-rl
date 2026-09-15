# IDRiD Evaluation Pipeline
# Orchestrates data generation, evaluation, and reporting

EVAL := python3 /app/src/evaluate.py
GEN := python3 /app/src/generate_synthetic.py
NUM_IMAGES := 20
SEED := 42
NOISE := 0.2

DATA_DIR := /app/output/data
RESULTS_DIR := /app/output/results
REPORT := /app/output/report.json

.PHONY: all generate evaluate report clean

all: evaluate

generate:
	@mkdir -p $(DATA_DIR)
	$(GEN) --task lesion_segmentation --num-images $(NUM_IMAGES) --output-dir $(DATA_DIR)/seg --seed $(SEED) --noise-level $(NOISE)
	$(GEN) --task disease_grading --num-images $(NUM_IMAGES) --output-dir $(DATA_DIR)/grade --seed $(SEED) --noise-level $(NOISE)
	$(GEN) --task localization --num-images $(NUM_IMAGES) --output-dir $(DATA_DIR)/loc --seed $(SEED) --noise-level $(NOISE)

evaluate: generate
	@mkdir -p $(RESULTS_DIR)
	$(EVAL) --task lesion_segmentation --predictions $(DATA_DIR)/seg/pred --ground-truth $(DATA_DIR)/seg/gt --output-json $(RESULTS_DIR)/seg.json
	$(EVAL) --task disease_grading --predictions $(DATA_DIR)/grade/pred.csv --ground-truth $(DATA_DIR)/grade/gt.csv --output-json $(RESULTS_DIR)/grade.json
	$(EVAL) --task localization --predictions $(DATA_DIR)/loc/pred.csv --ground-truth $(DATA_DIR)/loc/gt.csv --output-json $(RESULTS_DIR)/loc.json

report: generate
	jq -s '{segmentation: .[0], grading: .[1], localization: .[2], pipeline_version: "1.0"}' $(RESULT_DIR)/seg.json $(RESULT_DIR)/grade.json $(RESULT_DIR)/loc.json > $(REPORT)

clean:
	rm -rf /app/output
