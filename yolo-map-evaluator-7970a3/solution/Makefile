# Detection evaluation pipeline (fixed)
#

.PHONY: evaluate clean

DB       := /app/data/annotations.db
CONFIG   := /app/data/meta.yaml
DATA_DIR := /app/data
GT_DIR   := $(DATA_DIR)/ground_truth
PRED_DIR := $(DATA_DIR)/predictions
MANIFEST := $(DATA_DIR)/manifest.json
OUTPUT   := /app/results.json

# Extract annotations from database to YOLO-format files
$(GT_DIR)/.stamp: $(DB) /app/pipeline/extract.py
	python3 /app/pipeline/extract.py --db $(DB) --output-dir $(DATA_DIR)
	touch $@

# Compute evaluation metrics (depends on extraction completing first)
$(OUTPUT): /app/evaluate.py $(CONFIG) $(GT_DIR)/.stamp
	python3 /app/evaluate.py \
		--ground-truth $(GT_DIR) \
		--predictions $(PRED_DIR) \
		--manifest $(MANIFEST) \
		--config $(CONFIG) \
		--output $(OUTPUT)

evaluate: $(OUTPUT)
	@echo "Evaluation complete. Results in $(OUTPUT)"

clean:
	rm -rf $(GT_DIR) $(PRED_DIR) $(MANIFEST) $(OUTPUT)
