BUILD_DIR = /app/build

.PHONY: all extract-gt normalize evaluate report clean

all: report

extract-gt:
	@mkdir -p $(BUILD_DIR)
	python3 /app/scripts/extract_gt.py

normalize:
	@mkdir -p $(BUILD_DIR)/normalized
	bash /app/scripts/normalize.sh

# NOTE: evaluator_v2.py is an alternative implementation with different methodology
evaluate: extract-gt
	python3 /app/evaluator.py --gt $(BUILD_DIR)/ground_truth.json \
	    --submissions /app/submissions \
	    --output $(BUILD_DIR)/evaluation.json

report: evaluate
	cp $(BUILD_DIR)/evaluation.json /app/evaluation_report.json
	@echo "Report written to /app/evaluation_report.json"

clean:
	rm -rf $(BUILD_DIR) /app/evaluation_report.json /app/methodology.json
