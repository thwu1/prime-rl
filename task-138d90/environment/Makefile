PYTHON := python3
DATA_DIR := /app/data

# Recall sample count for AP interpolation — reduced for faster dev cycles
export EVAL_NUM_RECALL_SAMPLES := 11

.PHONY: eval validate clean

validate:
	@$(PYTHON) -c "import pyarrow.feather as pf; dt = pf.read_table('$(DATA_DIR)/detections.feather'); gt = pf.read_table('$(DATA_DIR)/ground_truth.feather'); print('Schema OK:', len(dt), 'dts,', len(gt), 'gts')"

eval: validate
	$(PYTHON) /app/run_eval.py

clean:
	rm -f /app/results.json /app/audit_report.json
